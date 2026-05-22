"""
data_pipeline/ingest_games.py

Phase 1 — Ingest games for seasons 2015-16 through 2023-24.
Includes both Regular Season and Playoffs.

Key insight: LeagueGameFinder returns TWO rows per game (one per team).
We split by home/away using the MATCHUP field, then join on GAME_ID
to produce one row per game with home_team, away_team, and scores.

MATCHUP patterns:
  "GSW vs. CLE"  →  GSW is home  (contains "vs.")
  "CLE @ GSW"    →  CLE is away  (contains "@")
"""

import os
import time
import psycopg2
import pandas as pd
from nba_api.stats.endpoints import leaguegamefinder
from dotenv import load_dotenv

# ── 1. CONFIG ──────────────────────────────────────────────────────────────────
load_dotenv()

# All seasons we want to ingest — Warriors/Cavs era through 2023-24
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


# ── 2. EXTRACT ─────────────────────────────────────────────────────────────────

def extract_games(season, season_type):
    """
    Pull all games for one season + season type from the NBA API.
    Returns raw DataFrame with 2 rows per game (one per team).
    """
    print(f"  Fetching {season} {season_type}...")
    time.sleep(1)  # respect the NBA API rate limit

    finder = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable=season_type
    )
    df = finder.get_data_frames()[0]
    print(f"    → {len(df)} team-game rows ({len(df) // 2} games)")
    return df


# ── 3. TRANSFORM ───────────────────────────────────────────────────────────────

def transform_games(df, season, season_type):
    """
    Convert from 2 rows per game → 1 row per game.

    Step 1: Split into home rows and away rows using MATCHUP
    Step 2: Join on GAME_ID
    Step 3: Rename columns to match schema
    """
    if df.empty:
        return pd.DataFrame()

    # Home team rows: MATCHUP contains "vs."  e.g. "GSW vs. CLE"
    home = df[df['MATCHUP'].str.contains(r'vs\.')].copy()

    # Away team rows: MATCHUP contains "@"  e.g. "CLE @ GSW"
    away = df[df['MATCHUP'].str.contains(' @ ')].copy()

    # Join on GAME_ID — each game now has one row with both teams
    merged = home.merge(
        away[['GAME_ID', 'TEAM_ID', 'PTS']],
        on='GAME_ID',
        suffixes=('_home', '_away')
    )

    # Build the final DataFrame matching our schema
    games = pd.DataFrame({
        'game_id':       merged['GAME_ID'],
        'game_date':     pd.to_datetime(merged['GAME_DATE']).dt.date,
        'season':        season,
        'season_type':   season_type,
        'home_team_id':  merged['TEAM_ID_home'].astype(int),
        'away_team_id':  merged['TEAM_ID_away'].astype(int),
        'home_score':    merged['PTS_home'].astype(int),
        'away_score':    merged['PTS_away'].astype(int),
        'status':        'Final',
    })

    return games


# ── 4. LOAD ────────────────────────────────────────────────────────────────────

def load_games(conn, df):
    """
    Upsert games into the DB.
    ON CONFLICT DO UPDATE means re-running is always safe.
    """
    if df.empty:
        print("    → No games to load, skipping")
        return 0

    cursor = conn.cursor()
    inserted = 0

    for _, row in df.iterrows():
        cursor.execute("""
            INSERT INTO games (
                game_id, game_date, season, season_type,
                home_team_id, away_team_id, home_score, away_score, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (game_id) DO UPDATE SET
                home_score   = EXCLUDED.home_score,
                away_score   = EXCLUDED.away_score,
                status       = EXCLUDED.status,
                updated_at   = NOW()
        """, (
            row['game_id'],
            row['game_date'],
            row['season'],
            row['season_type'],
            int(row['home_team_id']),
            int(row['away_team_id']),
            int(row['home_score']),
            int(row['away_score']),
            row['status'],
        ))
        inserted += 1

    conn.commit()
    cursor.close()
    return inserted


# ── 5. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    conn = get_connection()
    total_games = 0

    for season in SEASONS:
        print(f"\n── Season: {season} ──────────────────────")
        for season_type in SEASON_TYPES:
            # Extract
            raw_df = extract_games(season, season_type)

            # Transform
            games_df = transform_games(raw_df, season, season_type)

            # Load
            count = load_games(conn, games_df)
            total_games += count
            print(f"    → {count} games loaded")

    conn.close()
    print(f"\nDone. {total_games} total games loaded across all seasons.")
