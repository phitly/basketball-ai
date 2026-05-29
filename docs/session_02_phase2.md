# Session 02 — Phase 2: Analytics API

**Date:** May 27–29, 2026
**Goal:** Build a FastAPI backend that queries the Phase 1 database and returns meaningful basketball metrics through HTTP endpoints.

---

## What We Built

By the end of this session, you have a running FastAPI server that hits your real NBA database and returns possession-level efficiency metrics — points per possession, true shooting percentage, momentum breakdowns, and player efficiency — all from the 1.9M rows of data loaded in Phase 1.

---

## Part 1 — Project Structure

The backend lives in `basketball-ai/backend/` and is organized into layers, each with one job:

```
backend/
├── main.py          ← creates the FastAPI app, registers routers
├── config.py        ← all env vars in one place (reads from .env)
├── database.py      ← connection pool + per-request DB session
├── models.py        ← ORM models (Python classes mapped to DB tables)
├── schemas.py       ← Pydantic shapes for JSON input/output
├── routers/         ← one file per domain, defines HTTP endpoints
│   ├── games.py
│   ├── players.py
│   ├── teams.py
│   └── possessions.py
├── services/
│   └── metrics.py   ← all basketball math, no FastAPI imports
└── tests/
    ├── test_metrics.py   ← 29 unit tests, no DB required
    └── test_endpoints.py ← integration tests (SQLite in-memory)
```

**Key design principle:** services/ has no FastAPI imports. Basketball math is pure Python, independently testable without a running server.

---

## Part 2 — Key Concepts Learned

### What is an API?
A middleman between your database and the outside world. Instead of writing SQL, callers send HTTP requests and get back JSON. The React frontend (Phase 5) will use this API — it can't talk to PostgreSQL directly.

### What is FastAPI?
A Python library that handles routing, validation, and serialization automatically. You write a function with a decorator and it becomes an HTTP endpoint. It also auto-generates interactive docs at `/docs`.

### Why separate ORM models from Pydantic schemas?
- `models.py` describes the **database structure**
- `schemas.py` describes the **API contract** (what JSON goes in and out)
- Keeping them separate lets you evolve the API independently of the DB schema

### What is a dependency (get_db)?
FastAPI calls `get_db()` before your route function runs. It opens a DB session, yields it to your function, then closes it when the response is sent — even if an exception occurred. This is how every endpoint gets a database connection without managing it manually.

---

## Part 3 — Endpoints

| Endpoint | What it returns |
|---|---|
| GET /games | Paginated list of games, filterable by season and team |
| GET /games/{id}/summary | Full possession-level breakdown for one game |
| GET /player/{id}/efficiency | TS%, eFG%, FGA, FTA, turnovers for a player |
| GET /team/{id}/lineup-analysis | Five-man lineup ratings (empty — lineups table not populated) |
| GET /possessions/{game_id} | Raw possession log for a game |
| GET /momentum/{game_id} | Per-quarter efficiency comparison between home and away |
| GET /health | Returns 200 — used by Docker healthchecks in Phase 6 |

---

## Part 4 — Bugs Found and Fixed

### Bug 1: possession points_scored was wrong (cumulative player totals)
**Symptom:** Game summary showed Celtics scoring 425 points in one game with Q4 PPP of 10.21.

**Cause:** PlayByPlayV3 descriptions use `(X PTS)` to show a player's cumulative game total, not the points scored on that possession. The `get_shot_points()` function in `derive_possessions.py` was parsing that number.

**Fix:** Changed `get_shot_points()` to check `'3PT' in description` instead of parsing `(X PTS)`. Fixed existing data with a SQL UPDATE — 102,221 rows corrected.

```python
# Before (wrong)
match = re.search(r'\((\d+) PTS\)', str(description or ''))
return int(match.group(1)) if match else 2

# After (correct)
return 3 if '3PT' in str(description or '') else 2
```

### Bug 2: shots table only had made shots
**Symptom:** Player efficiency showed fgm == fga (100% FG) and TS% > 1.0.

**Cause:** `ShotChartDetail` endpoint defaults to `context_measure_simple='FGM'` (made only). Should be `'FGA'` (all attempts).

**Fix:** Added `context_measure_simple='FGA'` to the endpoint call. Truncated shots table and re-ran ingest — went from 929K to 2,008,598 shots. Took 25 minutes.

### Bug 3: momentum endpoint had home/away labels swapped
**Symptom:** Home team PPP matched away team's actual numbers and vice versa.

**Cause:** `build_momentum_windows()` used dict insertion order to assign home/away, not the actual team IDs.

**Fix:** Passed `home_team_id` into the function and explicitly matched teams by ID.

### Bug 4: player efficiency returned zero FTA and turnovers
**Cause:** Router was querying `event_type == "FREE_THROW"` and `"TURNOVER"` but the database stores `"Free Throw"` and `"Turnover"` (title case, not snake case).

**Fix:** Updated all event_type strings in `routers/players.py` to match actual DB values.

### Bug 5: free throw made/missed detection was wrong
**Cause:** Router checked `event_subtype.ilike("%made%")` but subtypes are formatted as "Free Throw 1 of 2" — no made/missed indicator.

**Fix:** Check `description.notlike("MISS%")` instead — missed FTs start with "MISS", made ones do not.

---

## Part 5 — Verified Real Data (Finals Game 5, 2024)

Game: `0042300405` — Celtics 106, Mavericks 88 (Championship clincher)

**Celtics possession efficiency:**
- Q1: 1.14 PPP
- Q2: 1.71 PPP ← dominant, game decided here
- Q3: 0.63 PPP ← completely fell apart
- Q4: 1.21 PPP ← closed it out

**Mavericks:** 13 turnovers vs Celtics' 7 — the real story of the game.

**Jayson Tatum 2023-24:**
- FG: 831/1798 (46.2%)
- 3PM: 268
- FTA: 634
- TS%: 59.3% (real: 59.1% — nearly exact)
- TOV: 238 (2.6/game across 93 games)

---

## Part 6 — Known Gaps (Carried Into Phase 3)

- `lineups` table is still empty (0 rows) — lineup endpoint returns nothing
- `usage_rate` is null in player efficiency — needs lineup data to calculate
- Momentum endpoint uses per-period windows, not true sliding windows
- `arena` field is null for all games — not provided by the LeagueGameFinder endpoint used in Phase 1

---

## Commands Reference

```bash
# Start the database
docker compose up -d

# Activate virtual environment
source venv/Scripts/activate

# Run the API
cd backend
uvicorn main:app --reload --port 8000
# Visit: http://localhost:8000/docs

# Run unit tests (no DB needed)
cd backend
PYTHONPYCACHEPREFIX=/tmp/pc python -m pytest tests/test_metrics.py -v

# Fix shots data (if needed — already done)
# context_measure_simple='FGA' must be set in ingest_shots.py
python data_pipeline/ingest_shots.py
```

---

## What's Next (Phase 3)

Build the shot quality ML model — predict expected points per shot attempt using distance, zone, shot type, game clock, and opponent defensive rating.

- Model 1: Logistic regression baseline
- Model 2: XGBoost upgrade
- Full error analysis comparing both
- Output: expected PPP per shot, surfaced through the API

Start a new chat for Phase 3.
