# Session 01 — Phase 1: Data Foundation

**Date:** May 22, 2026  
**Goal:** Get the development environment set up and real NBA data into a structured, queryable PostgreSQL database.

---

## What We Built

By the end of this session, you have a fully running local data pipeline that has pulled real NBA data from the internet and loaded it into your own PostgreSQL database — 9 seasons, regular season and playoffs, ready to query.

---

## Part 1 — Environment Setup

### Tools Installed / Configured
- **Docker Desktop** — runs PostgreSQL locally inside a container so you don't need to install Postgres directly on your machine
- **Python virtual environment (`venv`)** — isolates your project's packages from your system Python. Activate it with `source venv/Scripts/activate` every time you open a new terminal
- **Python packages installed:**
  - `nba_api` — pulls NBA play-by-play, box scores, shot data from stats.nba.com
  - `pandas` — cleans and reshapes raw data before loading into the DB
  - `psycopg2-binary` — lets Python talk to PostgreSQL
  - `python-dotenv` — reads your `.env` credentials file so passwords never touch your code
  - `sqlalchemy` — Python-friendly database querying (used in later phases)
  - `tqdm` — progress bars for long loops

### Key Files Created
| File | Purpose |
|---|---|
| `.env` | Database credentials — never committed to GitHub |
| `.gitignore` | Tells Git to ignore `venv/`, `.env`, `__pycache__/` |
| `docker-compose.yml` | Defines the PostgreSQL container |
| `schema.sql` | DDL for all 8 database tables |
| `test_connection.py` | Verified Python could talk to the DB |

### Lessons Learned
- `(venv)` must appear in your prompt before running any Python — if it's not there, run `source venv/Scripts/activate`
- `>>>` prompt = inside Python. `$` prompt = inside the terminal. They are different modes
- Git Bash on Windows uses `/c/Users/...` path format, not `C:\Users\...`
- `git config core.autocrlf input` prevents line-ending issues when switching between Mac and Windows

---

## Part 2 — Database Schema

### The 8 Tables

```
teams        — 30 NBA teams with conference and division
players      — all 5,103 NBA players (active + historical)
games        — one row per game with home/away teams and final score
play_events  — raw play-by-play (every event in every game)
shots        — one row per shot attempt with location and outcome
possessions  — DERIVED from play_events (computed, not pulled from API)
lineups      — five-man unit stints derived from substitution tracking
pipeline_runs — ingest log for monitoring and safe re-runs
```

### Key Design Decisions
- **NBA native IDs** are used throughout — `team_id`, `player_id`, `game_id` all match NBA API values exactly, so joins never break
- **`possessions` is derived** — it gets computed from `play_events` in a second pass, it is not a raw API field
- **`defender_distance` is nullable** — tracking data only exists from 2013-14 onward; older seasons get NULL
- **Upsert pattern everywhere** — every ingest uses `INSERT ... ON CONFLICT DO UPDATE`, making all scripts safe to re-run without creating duplicates

### How to Apply the Schema
```bash
docker compose up -d        # starts Postgres — schema.sql runs automatically on first boot
python test_connection.py   # confirms all 8 tables exist
```

---

## Part 3 — ETL Pipeline (Extract, Transform, Load)

Every ingest script follows the same three-step pattern:

1. **Extract** — call the NBA API, get raw data back as a list or DataFrame
2. **Transform** — rename columns, merge sources, clean types to match the schema
3. **Load** — upsert into PostgreSQL

### Script 1: `data_pipeline/ingest_teams.py`

**What it does:** Loads all 30 NBA teams into the `teams` table.

**Why two API calls?**  
The static teams endpoint gives you name, abbreviation, city — but not conference or division. Those only exist in the standings endpoint. We pull both and merge them on `team_id`.

**Result:** 30 teams loaded

```
Atlanta Hawks       East   Southeast
Boston Celtics      East   Atlantic
Cleveland Cavaliers East   Central
Golden State Warriors West  Pacific
...
```

---

### Script 2: `data_pipeline/ingest_players.py`

**What it does:** Loads all 5,103 NBA players (active and retired) into the `players` table.

**Why load retired players?**  
Our play-by-play data goes back to 2015-16. Players like LeBron James, Kevin Durant mid-career, Kyrie Irving on the Cavs — all appear in those events. Without their player records, the foreign key would fail.

**Why two API calls?**  
Static data gives names and `is_active` but no team info. `CommonAllPlayers` gives us current `team_id` for active players. We merge them — active players get a team, retired players get NULL.

**Key fix learned:** pandas uses floats to represent nullable integers. `1610612758.0` needs to be cast to `int()` before PostgreSQL will accept it.

**Result:** 5,103 players loaded (530 active, 4,573 retired/inactive)

---

### Script 3: `data_pipeline/ingest_games.py`

**What it does:** Loads every game from 2015-16 through 2023-24 (regular season + playoffs).

**Scope decision:** Started at 2015-16 specifically to capture the Golden State Warriors and Cleveland Cavaliers Finals rivalry (2015–2018). All seasons fall within the modern tracking era so data quality is consistent.

**The key transform trick:**  
`LeagueGameFinder` returns 2 rows per game — one per team. The `MATCHUP` field tells you who is home:
- `"GSW vs. CLE"` → GSW is home (using `vs.`)
- `"CLE @ GSW"` → CLE is away (using `@`)

We split on this, then join on `GAME_ID` to produce one row per game.

**COVID note:** 2019-20 shows 1,059 regular season games instead of 1,230 — the league cancelled 8 games per team when COVID hit. The data reflects reality.

**Result:** 11,499 total games loaded

| Season | Regular Season | Playoffs |
|---|---|---|
| 2015-16 | 1,230 | 86 |
| 2016-17 | 1,230 | 79 |
| 2017-18 | 1,230 | 82 |
| 2018-19 | 1,230 | 82 |
| 2019-20 | 1,059 | 83 |
| 2020-21 | 1,080 | 85 |
| 2021-22 | 1,230 | 87 |
| 2022-23 | 1,230 | 84 |
| 2023-24 | 1,230 | 82 |

---

## Current State of the Database

```
teams        →  30 rows
players      →  5,103 rows
games        →  11,499 rows
play_events  →  0 rows  (next session)
shots        →  0 rows  (next session)
possessions  →  0 rows  (derived — later)
lineups      →  0 rows  (derived — later)
pipeline_runs→  0 rows  (to be wired in)
```

---

## What's Next (Session 02)

- **Play-by-play ingest** — one API call per game = ~11,499 requests. Needs rate limiting and checkpointing so it can resume if interrupted
- **Shots ingest** — `ShotChartDetail` endpoint, one call per team per season
- **Possession derivation** — compute possessions from raw play events

---

## Commands Reference

```bash
# Start the database
docker compose up -d

# Activate your virtual environment (do this every time you open a terminal)
source venv/Scripts/activate

# Run ingest scripts
python data_pipeline/ingest_teams.py
python data_pipeline/ingest_players.py
python data_pipeline/ingest_games.py

# Check what's in the DB
python test_connection.py

# Git workflow
git add .
git commit -m "your message"
git push
```
