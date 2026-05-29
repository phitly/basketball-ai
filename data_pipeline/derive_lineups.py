"""
data_pipeline/derive_lineups.py

Phase 2 — Derive five-man lineup stints from play-by-play substitution events.

How it works:
  1. For each game, infer starting lineups by collecting the first 5 unique
     player IDs per team from the period's first events.
  2. Track substitutions:
       - player1_id = player going OUT (stored directly)
       - Incoming player = parse name from "SUB: X FOR Y", look up by last name
  3. At each substitution or end of period, close the current lineup stint
     and record points scored for/against using the running score columns.
  4. Load completed stints into the lineups table.

Known simplifications:
  - Starting lineup inference looks at first 10 events per team per period.
    If a player doesn't appear in those events, they may be missed.
  - Name lookup uses last name only — rare conflicts handled by team context.
  - Points include free throws (unlike possessions table which skips FTs).

CHECKPOINTING: skips games that already have lineups. Safe to stop and restart.
"""

import os
import re
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# ── 1. HELPERS ─────────────────────────────────────────────────────────────────

def parse_incoming_name(description):
    """
    Extract the incoming player's name from a substitution description.
    e.g. "SUB: Lively II FOR Gafford" → "Lively II"
         "SUB: Green FOR Jones Jr."    → "Green"
    """
    match = re.match(r'SUB:\s+(.+?)\s+FOR\s+', str(description or ''))
    return match.group(1).strip() if match else None


def build_name_lookup(conn, team_id, game_id):
    """
    Build a last-name → player_id lookup for players who appear in this game.
    Scoped to one team to avoid cross-team name conflicts.

    We use all player1_ids from this game's events for this team as the
    candidate pool — avoids loading the full 5,103-player table.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT pe.player1_id, p.last_name, p.full_name
        FROM play_events pe
        JOIN players p ON p.player_id = pe.player1_id
        WHERE pe.game_id = %s
          AND pe.player1_team_id = %s
          AND pe.player1_id IS NOT NULL
    """, (game_id, team_id))
    rows = cur.fetchall()
    cur.close()

    # last_name (lowercased) → player_id
    # In case of conflict, keep both — will be resolved by context later
    lookup = {}
    for player_id, last_name, full_name in rows:
        key = last_name.lower()
        lookup[key] = player_id

        # Also index by full last name including suffix (e.g. "lively ii")
        if full_name:
            parts = full_name.lower().split()
            if len(parts) >= 2:
                # Try "jones jr." style keys
                for i in range(1, len(parts)):
                    suffix_key = " ".join(parts[i:])
                    lookup[suffix_key] = player_id

    return lookup


def lookup_incoming(name, name_lookup):
    """
    Find a player_id from the parsed incoming name.
    Tries full name first, then last word only.
    """
    if not name:
        return None
    key = name.lower()
    if key in name_lookup:
        return name_lookup[key]
    # Try last word only (e.g. "Lively II" → try "ii", then "lively ii")
    parts = key.split()
    for i in range(len(parts)):
        partial = " ".join(parts[i:])
        if partial in name_lookup:
            return name_lookup[partial]
    return None


# ── 2. FETCH DATA ──────────────────────────────────────────────────────────────

def get_games_to_process(conn):
    """Games that have play_events but no lineups yet."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT g.game_id, g.home_team_id, g.away_team_id
        FROM games g
        JOIN play_events pe ON pe.game_id = g.game_id
        WHERE g.game_id NOT IN (
            SELECT DISTINCT game_id FROM lineups
        )
        ORDER BY g.game_id
    """)
    games = cur.fetchall()
    cur.close()
    return games


def get_game_events(conn, game_id):
    """
    Fetch all events for a game in order.
    Returns: (event_id, period, event_num, event_type, player1_id,
               player1_team_id, description, home_score, away_score)
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT event_id, period, event_num, event_type,
               player1_id, player1_team_id, description,
               home_score, away_score
        FROM play_events
        WHERE game_id = %s
        ORDER BY period, event_num
    """, (game_id,))
    events = cur.fetchall()
    cur.close()
    return events


# ── 3. LINEUP STATE MACHINE ────────────────────────────────────────────────────

def infer_starting_lineup(events, team_id, period, max_events=200):
    """
    Collect the first 5 unique player1_ids for a team in a given period.
    These are the players we assume started that period.
    """
    seen = []
    count = 0
    for ev in events:
        _, ev_period, _, ev_type, player1_id, player1_team_id, _, _, _ = ev
        if ev_period != period:
            continue
        if ev_type == 'Substitution':
            # Outgoing player — they were on the floor, so count them
            if player1_team_id == team_id and player1_id and player1_id not in seen:
                seen.append(player1_id)
        elif player1_team_id == team_id and player1_id and player1_id not in seen:
            seen.append(player1_id)
        count += 1
        if count >= max_events or len(seen) >= 5:
            break
    return seen[:5]


def derive_game_lineups(game_id, home_team_id, away_team_id, events, conn):
    """
    Process one game's events and return a list of lineup stint tuples.

    For each team, tracks:
      - current 5 players on the floor
      - score when lineup came on (to compute points for/against)
      - event when lineup came on
    """
    lineups = []

    # Build name→ID lookups for both teams
    home_lookup = build_name_lookup(conn, home_team_id, game_id)
    away_lookup = build_name_lookup(conn, away_team_id, game_id)

    # Get the last valid score from events
    def get_last_score(events_so_far):
        for ev in reversed(events_so_far):
            h, a = ev[7], ev[8]
            if h is not None and a is not None:
                return h, a
        return 0, 0

    # Per-team state
    state = {
        home_team_id: {"lineup": [], "start_event": None, "start_score": (0, 0), "period": None},
        away_team_id: {"lineup": [], "start_event": None, "start_score": (0, 0), "period": None},
    }

    def close_lineup(team_id, end_event_num, current_score, period):
        """Record a completed lineup stint."""
        s = state[team_id]
        if len(s["lineup"]) < 1 or s["start_event"] is None:
            return

        start_home, start_away = s["start_score"]
        curr_home,  curr_away  = current_score

        if team_id == home_team_id:
            pts_for     = max(0, curr_home - start_home)
            pts_against = max(0, curr_away - start_away)
        else:
            pts_for     = max(0, curr_away - start_away)
            pts_against = max(0, curr_home - start_home)

        player_ids = sorted(s["lineup"])  # sort for consistent deduplication

        lineups.append((
            game_id,
            team_id,
            player_ids,
            period,
            pts_for,
            pts_against,
        ))

    # Get all periods in this game
    periods = sorted(set(ev[1] for ev in events))

    for period in periods:
        period_events = [ev for ev in events if ev[1] == period]

        # Infer starting lineups for this period
        for team_id in [home_team_id, away_team_id]:
            starter_ids = infer_starting_lineup(period_events, team_id, period)
            if starter_ids:
                score = get_last_score(
                    [ev for ev in events if ev[1] < period]
                ) if period > 1 else (0, 0)

                # Close previous lineup if one was open
                close_lineup(team_id, None, score, period - 1)

                state[team_id] = {
                    "lineup":      list(starter_ids),
                    "start_event": period_events[0][0] if period_events else None,
                    "start_score": score,
                    "period":      period,
                }

        # Build a running score map: event_num → (home_score, away_score)
        # Substitution events have null scores — we need the last real score
        # before each substitution.
        # Initialize from end of previous period so Q2/Q3/Q4 subs don't reset to (0,0).
        running_score = get_last_score([ev for ev in events if ev[1] < period])
        score_at_event = {}
        for ev in period_events:
            if ev[7] is not None and ev[8] is not None:
                running_score = (ev[7], ev[8])
            score_at_event[ev[2]] = running_score  # keyed by event_num

        for ev in period_events:
            ev_id, ev_period, ev_num, ev_type, p1_id, p1_team_id, desc, h_score, a_score = ev

            if ev_type != 'Substitution':
                continue
            if p1_team_id not in state:
                continue

            team_id   = p1_team_id
            s         = state[team_id]
            lookup    = home_lookup if team_id == home_team_id else away_lookup

            # p1_id = player going OUT
            player_out = p1_id

            # Parse player coming IN from description
            incoming_name = parse_incoming_name(desc)
            player_in     = lookup_incoming(incoming_name, lookup)

            if player_out is None or player_in is None:
                continue
            if player_out not in s["lineup"]:
                continue

            # Use last real score before this substitution
            curr_score = score_at_event.get(ev_num, running_score)

            # Close current lineup stint
            close_lineup(team_id, ev_id, curr_score, period)

            # Start new lineup with the swap — guard against duplicates
            new_lineup = [p for p in s["lineup"] if p != player_out]
            if player_in not in new_lineup:
                new_lineup = new_lineup + [player_in]
            state[team_id] = {
                "lineup":      new_lineup,
                "start_event": ev_id,
                "start_score": curr_score,
                "period":      period,
            }

        # End of period — close all open lineups
        final_score = get_last_score(period_events)
        for team_id in [home_team_id, away_team_id]:
            close_lineup(team_id, None, final_score, period)
            # Reset for next period
            state[team_id] = {"lineup": [], "start_event": None,
                               "start_score": final_score, "period": None}

    return lineups


# ── 4. LOAD ────────────────────────────────────────────────────────────────────

def load_lineups(conn, lineups):
    """Batch insert lineup stints for one game."""
    if not lineups:
        return 0
    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO lineups (
            game_id, team_id, player_ids, period,
            points_for, points_against
        )
        VALUES %s
        """,
        lineups
    )
    conn.commit()
    cur.close()
    return len(lineups)


# ── 5. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = get_connection()
    games = get_games_to_process(conn)
    print(f"Games to process: {len(games):,}")
    print("Deriving lineups — no API calls, reads from play_events.\n")

    total_lineups = 0
    failed = 0

    for game_id, home_team_id, away_team_id in tqdm(games, desc="Games", unit="game"):
        try:
            events  = get_game_events(conn, game_id)
            lineups = derive_game_lineups(game_id, home_team_id, away_team_id, events, conn)
            total_lineups += load_lineups(conn, lineups)
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"\n  ✗ {game_id}: {e}")

    conn.close()
    avg = total_lineups / len(games) if games else 0
    print(f"\n── Done ──────────────────────────────────")
    print(f"Total lineup stints: {total_lineups:,}")
    print(f"Average per game:    {avg:.0f}")
    print(f"Failed games:        {failed}")
