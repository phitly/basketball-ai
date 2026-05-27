"""
data_pipeline/ingest_shots.py

Phase 1 — Ingest shot chart data for all teams, all seasons.

Strategy: pull by team + season + season_type (540 API calls total).
Much faster than per-game — ~10 minutes to run.

CHECKPOINTING: tracks which (team_id, season, season_type) combos are
already loaded. Safe to stop and restart.

NOTE: defender_distance is not available from ShotChartDetail.
That column stays NULL and will be enriched in a later phase.
"""

import os
import time
import psycopg2
import psycopg2.extras
import pandas as pd
from nba_api.stats.endpoints import shotchartdetail
from nba_api.stats.static import teams
from dotenv import load_dotenv
from tqdm import tqdm

# ── 1. CONFIG ──────────────────────────────────────────────────────────────────
load_dotenv()

SEASONS = [
    '2015-16', '2016-17', '2017-18', '2018-19', '2019-20',
    '2020-21', '2021-22', '2022-23', '2023-24'
]
SEASON_TYPES = ['Regular Season', 'Playoffs']


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# ── 2. CHECKPOINTING ───────────────────────────────────────────────────────────

def get_completed_combos(conn):
    """
    Return a set of (team_id, season, season_type) already in the shots table.
    We join shots → games to get the season info since shots doesn't store it directly.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT s.team_id, g.season, g.season_type
        FROM shots s
        JOIN games g ON s.game_id = g.game_id
    """)
    completed = set(tuple(row) for row in cursor.fetchall())
    cursor.close()
    return completed


def get_valid_player_ids(conn):
    """Load all known player IDs to filter FK violations."""
    cursor = conn.cursor()
    cursor.execute("SELECT player_id FROM players")
    ids = set(row[0] for row in cursor.fetchall())
    cursor.close()
    return ids


# ── 3. EXTRACT ─────────────────────────────────────────────────────────────────

def extract_shots(team_id, season, season_type, retries=3):
    """
    Pull all shots for one team/season/type from ShotChartDetail.
    player_id=0 means "all players on this team".

    Retries up to 3 times with increasing wait on timeout.
    Timeout set to 60s — some playoff shot charts are large and slow.
    """
    for attempt in range(1, retries + 1):
        try:
            endpoint = shotchartdetail.ShotChartDetail(
                team_id=team_id,
                player_id=0,
                season_nullable=season,
                season_type_all_star=season_type,
                timeout=60
            )
            df = endpoint.get_data_frames()[0]
            return df   # empty DataFrame = team didn't make playoffs, not an error
        except Exception as e:
            if attempt < retries:
                wait = attempt * 5   # wait 5s, then 10s before final attempt
                print(f"\n  ⚠ Attempt {attempt} failed for {team_id} {season} {season_type} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"\n  ✗ All {retries} attempts failed for {team_id} {season} {season_type}: {e}")
                return None


# ── 4. TRANSFORM ───────────────────────────────────────────────────────────────

def transform_shots(df, valid_player_ids):
    """
    Clean and reshape shot rows to match the shots schema.

    Key transforms:
    - SHOT_TYPE: '3PT Field Goal' → '3PT', '2PT Field Goal' → '2PT'
    - game_clock: combine MINUTES_REMAINING + SECONDS_REMAINING → "MM:SS"
    - SHOT_MADE_FLAG: 1/0 → True/False
    - Filter out player_ids not in our DB (same pattern as play_events)
    """
    rows = []
    for _, row in df.iterrows():
        player_id = int(row['PLAYER_ID'])
        if player_id not in valid_player_ids:
            continue  # skip players not in our DB

        # "3PT Field Goal" → "3PT", "2PT Field Goal" → "2PT"
        shot_type_raw = str(row.get('SHOT_TYPE', ''))
        shot_type = '3PT' if '3PT' in shot_type_raw else '2PT'

        # Combine minutes + seconds remaining into "MM:SS"
        mins = int(row.get('MINUTES_REMAINING', 0))
        secs = int(row.get('SECONDS_REMAINING', 0))
        game_clock = f"{mins:02d}:{secs:02d}"

        rows.append((
            str(row['GAME_ID']),
            player_id,
            int(row['TEAM_ID']),
            int(row['PERIOD']),
            game_clock,
            shot_type,
            str(row.get('ACTION_TYPE') or '') or None,   # e.g. "Jump Shot"
            str(row.get('SHOT_ZONE_BASIC') or '') or None,
            str(row.get('SHOT_ZONE_AREA') or '') or None,
            str(row.get('SHOT_ZONE_RANGE') or '') or None,
            int(row['SHOT_DISTANCE']) if pd.notna(row.get('SHOT_DISTANCE')) else None,
            int(row['LOC_X']) if pd.notna(row.get('LOC_X')) else None,
            int(row['LOC_Y']) if pd.notna(row.get('LOC_Y')) else None,
            bool(row['SHOT_MADE_FLAG']),
            None,    # defender_distance — not available from this endpoint
        ))
    return rows


# ── 5. LOAD ────────────────────────────────────────────────────────────────────

def load_shots(conn, rows):
    """Batch insert shots. No unique constraint on shots so we just INSERT."""
    if not rows:
        return 0
    cursor = conn.cursor()
    psycopg2.extras.execute_values(
        cursor,
        """
        INSERT INTO shots (
            game_id, player_id, team_id, period, game_clock,
            shot_type, action_type,
            shot_zone_basic, shot_zone_area, shot_zone_range,
            shot_distance, x_coord, y_coord,
            made, defender_distance
        )
        VALUES %s
        """,
        rows
    )
    conn.commit()
    cursor.close()
    return len(rows)


# ── 6. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = get_connection()

    all_teams        = teams.get_teams()
    completed_combos = get_completed_combos(conn)
    valid_player_ids = get_valid_player_ids(conn)

    # Build full list of (team_id, season, season_type) combos to process
    all_combos = [
        (t['id'], season, season_type)
        for t in all_teams
        for season in SEASONS
        for season_type in SEASON_TYPES
    ]
    remaining = [c for c in all_combos if c not in completed_combos]

    print(f"Total combos:    {len(all_combos)}")
    print(f"Already loaded:  {len(completed_combos)}")
    print(f"Remaining:       {len(remaining)}")
    print(f"Estimated time:  ~{len(remaining) * 1 / 60:.0f} minutes")
    print("\nStarting shot ingest — safe to stop and restart.\n")

    total_shots  = 0
    failed_combos = []

    for team_id, season, season_type in tqdm(remaining, desc="Combos", unit="combo"):
        df = extract_shots(team_id, season, season_type)

        if df is None:
            # Real API error — log it for retry
            failed_combos.append((team_id, season, season_type))
            time.sleep(1)
            continue

        if df.empty:
            # Team didn't make the playoffs — nothing to load, not an error
            continue

        rows = transform_shots(df, valid_player_ids)
        total_shots += load_shots(conn, rows)
        time.sleep(1)   # slightly longer sleep — this endpoint is stricter

    conn.close()

    print(f"\n── Done ──────────────────────────────────")
    print(f"Shots loaded:   {total_shots:,}")
    print(f"Failed combos:  {len(failed_combos)}")
    if failed_combos:
        print("Re-run the script to retry failed combos.")
