"""
data_pipeline/ingest_players.py

Phase 1 — Ingest players into the database.

Two data sources:
  1. nba_api static players  → all 5103 players (active + historical), gives names + is_active
  2. CommonAllPlayers        → current season roster, gives team_id for active players

We load ALL players so historical play-by-play data (2019-24) can reference
players who are now retired. Inactive players simply have team_id = NULL.

Position is nullable in the schema — we skip it here and enrich later.
"""

import os
import time
import psycopg2
import pandas as pd
from nba_api.stats.static import players
from nba_api.stats.endpoints import commonallplayers
from dotenv import load_dotenv

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


# ── 2. EXTRACT ─────────────────────────────────────────────────────────────────

def extract_all_players():
    """
    Pull all NBA players from static data — no HTTP request.
    Returns 5000+ players, active and retired.
    Fields: id, full_name, first_name, last_name, is_active
    """
    print("Extracting all players from static data...")
    raw = players.get_players()
    df = pd.DataFrame(raw)
    print(f"  → {len(df)} total players (active + historical)")
    return df


def extract_active_team_mapping():
    """
    Pull current season roster from CommonAllPlayers.
    This gives us the team_id for players currently on a roster.
    Makes one HTTP request to stats.nba.com — give it a few seconds.
    Fields: PERSON_ID, TEAM_ID, ROSTERSTATUS
    """
    print("Extracting active player/team mapping from CommonAllPlayers...")
    time.sleep(1)   # be polite to the NBA API — avoid rate limiting
    endpoint = commonallplayers.CommonAllPlayers(is_only_current_season=1)
    df = endpoint.get_data_frames()[0]
    print(f"  → {len(df)} players returned")

    # Keep only players actually on a roster (ROSTERSTATUS = 1)
    # and only the columns we need
    active = df[df['ROSTERSTATUS'] == 1][['PERSON_ID', 'TEAM_ID']].copy()
    print(f"  → {len(active)} players currently on a roster")
    return active


# ── 3. TRANSFORM ───────────────────────────────────────────────────────────────

def transform(all_players_df, active_team_df):
    """
    Merge the two DataFrames and rename columns to match the DB schema.

    all_players_df: id, full_name, first_name, last_name, is_active
    active_team_df: PERSON_ID, TEAM_ID

    Result: player_id, first_name, last_name, team_id, is_active
    (team_id will be NULL for inactive/retired players)
    """
    print("Transforming player data...")

    # Left join — keeps ALL 5000+ players, adds team_id only where it exists
    merged = all_players_df.merge(
        active_team_df,
        left_on='id',
        right_on='PERSON_ID',
        how='left'
    )

    # Rename to match DB schema
    merged = merged.rename(columns={
        'id':      'player_id',
        'TEAM_ID': 'team_id',
    })

    # team_id of 0 means "no team" in the NBA API — convert to None (NULL in DB)
    merged['team_id'] = merged['team_id'].apply(
        lambda x: int(x) if pd.notna(x) and x != 0 else None
    )

    # Select only the columns our schema needs
    result = merged[['player_id', 'first_name', 'last_name', 'team_id', 'is_active']]

    active_count = result['is_active'].sum()
    with_team = result['team_id'].notna().sum()
    print(f"  → {len(result)} total players")
    print(f"  → {active_count} active, {len(result) - active_count} retired/inactive")
    print(f"  → {with_team} players have a current team_id")
    print(result[result['team_id'].notna()].head(3).to_string(index=False))
    return result


# ── 4. LOAD ────────────────────────────────────────────────────────────────────

def load_players(conn, df):
    """
    Upsert players into the DB.
    Same ON CONFLICT pattern as ingest_teams — safe to re-run.

    Note: position is not set here (it's nullable in the schema).
    Note: team_id is a foreign key — teams must be loaded first.
    """
    print("Loading players into database...")
    cursor = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        cursor.execute("""
            INSERT INTO players (player_id, first_name, last_name, team_id, is_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (player_id) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                last_name  = EXCLUDED.last_name,
                team_id    = EXCLUDED.team_id,
                is_active  = EXCLUDED.is_active,
                updated_at = NOW()
        """, (
            int(row['player_id']),
            row['first_name'],
            row['last_name'],
            int(row['team_id']) if row['team_id'] is not None and str(row['team_id']) != 'nan' else None,
            bool(row['is_active']),
        ))
        inserted += 1

    conn.commit()
    cursor.close()
    print(f"  → {inserted} players loaded successfully")


# ── 5. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Extract
    all_players_df  = extract_all_players()
    active_team_df  = extract_active_team_mapping()

    # Transform
    final_df = transform(all_players_df, active_team_df)

    # Load
    conn = get_connection()
    load_players(conn, final_df)
    conn.close()

    print("\nDone. Players are in the database.")
