"""
data_pipeline/ingest_teams.py

Phase 1 — Ingest teams into the database.

ETL pattern:
  Extract  → pull raw data from nba_api
  Transform → rename columns, merge in conference/division, clean up
  Load     → insert into PostgreSQL with upsert (safe to re-run)
"""

import os
import psycopg2
import pandas as pd
from nba_api.stats.static import teams
from nba_api.stats.endpoints import leaguestandings
from dotenv import load_dotenv

# ── 1. CONFIG ──────────────────────────────────────────────────────────────────
# load_dotenv() reads your .env file and makes the values available via os.getenv
load_dotenv()

def get_connection():
    """Return a psycopg2 connection using credentials from .env"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


# ── 2. EXTRACT ─────────────────────────────────────────────────────────────────

def extract_teams():
    """
    Pull all 30 NBA teams from nba_api's static data.
    This is built into the package — no HTTP request needed.
    Returns a DataFrame with: id, full_name, abbreviation, city, nickname, etc.
    """
    print("Extracting teams from nba_api static data...")
    raw = teams.get_teams()           # returns a list of dicts
    df = pd.DataFrame(raw)            # convert to DataFrame for easy manipulation
    print(f"  → {len(df)} teams extracted")
    return df


def extract_conference_division():
    """
    Pull conference and division from the LeagueStandings endpoint.
    This DOES make an HTTP request to stats.nba.com.
    Returns a DataFrame with: TeamID, Conference, Division
    """
    print("Extracting conference/division from LeagueStandings...")
    standings = leaguestandings.LeagueStandings()
    df = standings.get_data_frames()[0]
    print(f"  → {len(df)} rows returned")
    return df[['TeamID', 'Conference', 'Division']]


# ── 3. TRANSFORM ───────────────────────────────────────────────────────────────

def transform(teams_df, conf_df):
    """
    Merge the two DataFrames together and rename columns to match the DB schema.

    teams_df columns:  id, full_name, abbreviation, nickname, city, state, year_founded
    conf_df columns:   TeamID, Conference, Division
    Schema columns:    team_id, abbreviation, name, city, conference, division
    """
    print("Transforming data...")

    # Merge on team ID — left join keeps all 30 teams even if standings is missing one
    merged = teams_df.merge(
        conf_df,
        left_on='id',
        right_on='TeamID',
        how='left'
    )

    # Rename to match the DB schema column names
    merged = merged.rename(columns={
        'id':        'team_id',
        'full_name': 'name',
        'Conference':'conference',
        'Division':  'division',
    })

    # Select only the columns our schema needs
    result = merged[['team_id', 'abbreviation', 'name', 'city', 'conference', 'division']]

    print(f"  → {len(result)} teams ready to load")
    print(result.head(3).to_string(index=False))   # preview first 3 rows
    return result


# ── 4. LOAD ────────────────────────────────────────────────────────────────────

def load_teams(conn, df):
    """
    Insert teams into the DB using an upsert (INSERT ... ON CONFLICT DO UPDATE).

    Why upsert and not plain INSERT?
    If you run this script twice, a plain INSERT would fail with a duplicate key error.
    ON CONFLICT DO UPDATE means: if a team_id already exists, update it instead.
    This makes the script safe to re-run at any time.
    """
    print("Loading teams into database...")
    cursor = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        cursor.execute("""
            INSERT INTO teams (team_id, abbreviation, name, city, conference, division)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (team_id) DO UPDATE SET
                abbreviation = EXCLUDED.abbreviation,
                name         = EXCLUDED.name,
                city         = EXCLUDED.city,
                conference   = EXCLUDED.conference,
                division     = EXCLUDED.division,
                updated_at   = NOW()
        """, (
            int(row['team_id']),
            row['abbreviation'],
            row['name'],
            row['city'],
            row['conference'],
            row['division'],
        ))
        inserted += 1

    conn.commit()      # write everything to the DB in one go
    cursor.close()
    print(f"  → {inserted} teams loaded successfully")


# ── 5. RUN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Extract
    teams_df = extract_teams()
    conf_df  = extract_conference_division()

    # Transform
    final_df = transform(teams_df, conf_df)

    # Load
    conn = get_connection()
    load_teams(conn, final_df)
    conn.close()

    print("\nDone. Teams are in the database.")
