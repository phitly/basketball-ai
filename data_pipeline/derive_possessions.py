"""
data_pipeline/derive_possessions.py

Phase 1 — Derive possessions from play-by-play events.

No API calls — we read our own play_events table and compute
where each possession starts and ends.

Possession rules (simplified for Phase 1):
  ENDS on:      Made Shot, Defensive Rebound, Turnover, End of Period
  CONTINUES on: Offensive Rebound (same team keeps the ball)

Known simplifications:
  - Free throws are skipped (treated as possession continuations)
  - Technical fouls and jump balls mid-game are ignored
  - Team-less events (player1_team_id = NULL) are skipped

This gives us a good-faith approximation suitable for efficiency
metrics, momentum tracking, and the Phase 3 ML model.
"""

import os
import re
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from tqdm import tqdm

# ── 1. CONFIG ──────────────────────────────────────────────────────────────────
load_dotenv()

# Events that can END a possession
POSSESSION_ENDING_EVENTS = {'Made Shot', 'Missed Shot', 'Turnover', 'End Period'}

# Events we skip entirely — they don't change who has the ball
SKIP_EVENTS = {'Foul', 'Substitution', 'Timeout', 'Violation',
               'Ejection', 'Jump Ball', 'Start Period', 'Free Throw'}


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# ── 2. HELPERS ─────────────────────────────────────────────────────────────────

def get_shot_points(description):
    """
    Parse point value from shot description.
    e.g. "Thompson 3' Layup (2 PTS) (Irving 1 AST)" → 2
         "Green 26' 3PT Pullup Jump Shot (3 PTS)"    → 3
    Falls back to 2 if not found.
    """
    match = re.search(r'\((\d+) PTS\)', str(description or ''))
    return int(match.group(1)) if match else 2


def other_team(team_id, home_team_id, away_team_id):
    """Return the opposing team's ID."""
    if team_id == home_team_id:
        return away_team_id
    return home_team_id


# ── 3. FETCH DATA ──────────────────────────────────────────────────────────────

def get_games_to_process(conn):
    """
    Get all games that have play_events but no possessions yet.
    This is our checkpointing — safe to restart.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT g.game_id, g.home_team_id, g.away_team_id
        FROM games g
        JOIN play_events pe ON pe.game_id = g.game_id
        WHERE g.game_id NOT IN (
            SELECT DISTINCT game_id FROM possessions
        )
        ORDER BY g.game_id
    """)
    games = cursor.fetchall()
    cursor.close()
    return games


def get_game_events(conn, game_id):
    """
    Fetch all events for one game in order.
    Returns list of tuples: (event_id, period, clock, event_type, team_id, description)
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT event_id, period, game_clock, event_type,
               player1_team_id, description
        FROM play_events
        WHERE game_id = %s
        ORDER BY period, event_num
    """, (game_id,))
    events = cursor.fetchall()
    cursor.close()
    return events


# ── 4. STATE MACHINE ───────────────────────────────────────────────────────────

def derive_game_possessions(game_id, home_team_id, away_team_id, events):
    """
    Process one game's events and return a list of possession dicts.

    State tracked:
      possession_team       — who currently has the ball
      possession_start_eid  — event_id when this possession started
      possession_start_clock— game_clock when this possession started
      possession_period     — which quarter this possession is in
      last_shot_team        — who just attempted a shot (for rebound logic)
    """
    possessions = []

    # ── State variables ──────────────────────────────────────
    possession_team        = None
    possession_start_eid   = None
    possession_start_clock = None
    possession_period      = None
    last_shot_team         = None
    # ─────────────────────────────────────────────────────────

    def close_possession(end_eid, end_clock, outcome, points):
        """Write completed possession to our list."""
        if possession_team is None:
            return
        possessions.append((
            game_id,
            possession_team,
            possession_period,
            possession_start_eid,
            end_eid,
            possession_start_clock,
            end_clock,
            outcome,
            int(points),
        ))

    def start_possession(team_id, event_id, clock, period):
        """Update state to reflect new possession."""
        nonlocal possession_team, possession_start_eid
        nonlocal possession_start_clock, possession_period, last_shot_team
        possession_team        = team_id
        possession_start_eid   = event_id
        possession_start_clock = clock
        possession_period      = period
        last_shot_team         = None

    # ── Process events ────────────────────────────────────────
    for event_id, period, clock, event_type, team_id, description in events:

        # Skip events that don't affect possession
        if event_type in SKIP_EVENTS:
            continue

        # ── Made Shot ────────────────────────────────────────
        if event_type == 'Made Shot':
            if team_id is None:
                continue
            points = get_shot_points(description)
            close_possession(event_id, clock, 'made_shot', points)
            # Other team inbounds after the made basket
            start_possession(other_team(team_id, home_team_id, away_team_id),
                             event_id, clock, period)

        # ── Missed Shot ──────────────────────────────────────
        elif event_type == 'Missed Shot':
            if team_id is None:
                continue
            # If we don't know who has possession yet, assume it's the shooter
            if possession_team is None:
                start_possession(team_id, event_id, clock, period)
            last_shot_team = team_id

        # ── Rebound ──────────────────────────────────────────
        elif event_type == 'Rebound':
            if team_id is None or last_shot_team is None:
                continue

            if team_id == last_shot_team:
                # OFFENSIVE rebound — same team keeps possession, reset last shot
                last_shot_team = None

            else:
                # DEFENSIVE rebound — possession changes
                close_possession(event_id, clock, 'defensive_rebound', 0)
                start_possession(team_id, event_id, clock, period)

        # ── Turnover ─────────────────────────────────────────
        elif event_type == 'Turnover':
            if team_id is None:
                continue
            close_possession(event_id, clock, 'turnover', 0)
            start_possession(other_team(team_id, home_team_id, away_team_id),
                             event_id, clock, period)

        # ── End Period ───────────────────────────────────────
        elif event_type == 'End Period':
            close_possession(event_id, clock, 'end_of_period', 0)
            possession_team = None
            last_shot_team  = None

    return possessions


# ── 5. LOAD ────────────────────────────────────────────────────────────────────

def load_possessions(conn, possessions):
    """Batch insert all possessions for one game."""
    if not possessions:
        return 0
    cursor = conn.cursor()
    psycopg2.extras.execute_values(
        cursor,
        """
        INSERT INTO possessions (
            game_id, team_id, period,
            start_event_id, end_event_id,
            start_game_clock, end_game_clock,
            outcome, points_scored
        )
        VALUES %s
        """,
        possessions
    )
    conn.commit()
    cursor.close()
    return len(possessions)


# ── 6. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = get_connection()

    games = get_games_to_process(conn)
    print(f"Games to process: {len(games)}")
    print("Deriving possessions — this runs locally, no API calls.\n")

    total_possessions = 0

    for game_id, home_team_id, away_team_id in tqdm(games, desc="Games", unit="game"):
        events     = get_game_events(conn, game_id)
        possessions = derive_game_possessions(game_id, home_team_id, away_team_id, events)
        total_possessions += load_possessions(conn, possessions)

    conn.close()

    print(f"\n── Done ──────────────────────────────────")
    print(f"Total possessions derived: {total_possessions:,}")
    avg = total_possessions / len(games) if games else 0
    print(f"Average per game:          {avg:.0f}")
