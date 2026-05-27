"""
data_pipeline/ingest_play_events.py

Phase 1 — Ingest play-by-play events for all games using PlayByPlayV3.

This is the largest ingest — one API call per game (~11,499 calls total).
Expected runtime: 3-4 hours at a safe request rate.

CHECKPOINTING: The script checks which games are already loaded before
making any API call. Safe to stop and restart at any time — it always
resumes from where it left off.

RATE LIMITING: 0.6 second sleep between calls (~100 requests/min).
"""

import os
import re
import time
import psycopg2
import psycopg2.extras
import pandas as pd
from nba_api.stats.endpoints import playbyplayv3
from dotenv import load_dotenv
from tqdm import tqdm

# ── 1. CONFIG ──────────────────────────────────────────────────────────────────
load_dotenv()


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# ── 2. CHECKPOINTING ───────────────────────────────────────────────────────────

def get_all_game_ids(conn):
    """Fetch all game_ids from the games table ordered by date."""
    cursor = conn.cursor()
    cursor.execute("SELECT game_id FROM games ORDER BY game_date")
    ids = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return ids


def get_completed_game_ids(conn):
    """
    Fetch game_ids that already have events loaded.
    These are skipped on re-runs — this is the checkpointing mechanism.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT game_id FROM play_events")
    ids = set(row[0] for row in cursor.fetchall())
    cursor.close()
    return ids


def get_valid_player_ids(conn):
    """
    Load all known player IDs from our players table into a set.
    Used to filter out player references in play-by-play that aren't
    in our database — avoids FK violations on historical/missing players.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT player_id FROM players")
    ids = set(row[0] for row in cursor.fetchall())
    cursor.close()
    print(f"  Loaded {len(ids):,} valid player IDs")
    return ids


# ── 3. EXTRACT ─────────────────────────────────────────────────────────────────

def extract_play_by_play(game_id):
    """
    Pull all events for one game from PlayByPlayV3.
    Returns a DataFrame or None if the request fails.
    """
    try:
        endpoint = playbyplayv3.PlayByPlayV3(game_id=game_id)
        df = endpoint.get_data_frames()[0]
        return df if not df.empty else None
    except Exception as e:
        print(f"\n  ⚠ Failed to fetch {game_id}: {e}")
        return None


# ── 4. TRANSFORM ───────────────────────────────────────────────────────────────

def convert_clock(clock_str):
    """
    Convert V3 ISO 8601 clock format to MM:SS string.
    "PT05M32.00S" → "05:32"
    "PT12M00.00S" → "12:00"
    """
    if not clock_str:
        return "00:00"
    match = re.match(r'PT(\d+)M([\d.]+)S', str(clock_str))
    if match:
        minutes = match.group(1).zfill(2)
        seconds = str(int(float(match.group(2)))).zfill(2)
        return f"{minutes}:{seconds}"
    return str(clock_str)


def clean_player_id(val, valid_ids):
    """
    Return None for missing, zero, team IDs, or players not in our DB.
    - Team IDs (1610612737–1610612766) appear in some events and are not players
    - Some historical players are missing from nba_api static data
    Both cases would cause FK violations, so we set them to NULL instead.
    """
    try:
        v = int(val)
        if v == 0:
            return None
        if 1610612737 <= v <= 1610612766:  # team ID, not a player
            return None
        if v not in valid_ids:             # player not in our DB
            return None
        return v
    except (ValueError, TypeError):
        return None


def clean_team_id(val):
    """Return None for missing or zero team IDs."""
    try:
        v = int(val)
        return v if v != 0 else None
    except (ValueError, TypeError):
        return None


def clean_score(val):
    """Return None for missing or zero scores."""
    try:
        v = int(val)
        return v if pd.notna(val) else None
    except (ValueError, TypeError):
        return None


def transform_events(df, game_id, valid_player_ids):
    """
    Reshape V3 play-by-play rows to match the play_events schema.

    V3 has one player per event (personId + teamId).
    player2_id and player3_id will be NULL — that's fine for the schema.

    Returns a list of tuples ready for batch insert.
    """
    rows = []
    for _, row in df.iterrows():
        rows.append((
            game_id,
            int(row['actionNumber']),
            int(row['period']),
            convert_clock(row.get('clock')),
            str(row.get('actionType') or 'UNKNOWN'),
            str(row.get('subType') or '') or None,
            clean_player_id(row.get('personId'), valid_player_ids),
            clean_team_id(row.get('teamId')),
            None,                                         # player2_id — not in V3
            None,                                         # player2_team_id
            None,                                         # player3_id
            None,                                         # player3_team_id
            str(row.get('description') or '') or None,
            clean_score(row.get('scoreHome')),
            clean_score(row.get('scoreAway')),
        ))
    return rows


# ── 5. LOAD ────────────────────────────────────────────────────────────────────

def load_events(conn, rows):
    """
    Batch insert all events for one game.
    execute_values is much faster than one INSERT per row.
    ON CONFLICT DO NOTHING keeps re-runs safe.
    """
    if not rows:
        return 0

    cursor = conn.cursor()
    psycopg2.extras.execute_values(
        cursor,
        """
        INSERT INTO play_events (
            game_id, event_num, period, game_clock,
            event_type, event_subtype,
            player1_id, player1_team_id,
            player2_id, player2_team_id,
            player3_id, player3_team_id,
            description, home_score, away_score
        )
        VALUES %s
        ON CONFLICT (game_id, event_num) DO NOTHING
        """,
        rows
    )
    conn.commit()
    cursor.close()
    return len(rows)


# ── 6. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = get_connection()

    all_ids         = get_all_game_ids(conn)
    completed_ids   = get_completed_game_ids(conn)
    valid_player_ids = get_valid_player_ids(conn)
    remaining       = [gid for gid in all_ids if gid not in completed_ids]

    print(f"Total games:     {len(all_ids)}")
    print(f"Already loaded:  {len(completed_ids)}")
    print(f"Remaining:       {len(remaining)}")
    print(f"Estimated time:  ~{len(remaining) * 0.6 / 60:.0f} minutes")
    print("\nStarting ingest — safe to stop and restart at any time.\n")

    total_events = 0
    failed_games = []

    for game_id in tqdm(remaining, desc="Games", unit="game"):
        df = extract_play_by_play(game_id)

        if df is None:
            failed_games.append(game_id)
            time.sleep(1)
            continue

        rows = transform_events(df, game_id, valid_player_ids)
        total_events += load_events(conn, rows)
        time.sleep(0.6)

    conn.close()

    print(f"\n── Done ──────────────────────────────────")
    print(f"Events loaded:  {total_events:,}")
    print(f"Failed games:   {len(failed_games)}")
    if failed_games:
        print("Re-run the script to retry failed games.")
