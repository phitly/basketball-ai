# Basketball Analytics Engine

A possession-level NBA analytics platform that transforms raw play-by-play data into structured efficiency metrics and plain-English game summaries.

Built to answer not just *what happened* in a game, but *why it mattered* — surfacing non-obvious efficiency patterns that traditional box scores miss.

---

## What It Does

**Example output from the 2024 NBA Finals Game 5 (Celtics 106, Mavericks 88):**

```
Celtics possession efficiency by quarter:
  Q1: 1.14 PPP  — controlled from the start
  Q2: 1.71 PPP  — dominant, game decided here
  Q3: 0.63 PPP  — completely fell apart offensively
  Q4: 1.21 PPP  — closed it out

Mavericks: 13 turnovers vs Celtics' 7 — the real story of the game.
```

This comes from querying 1.9 million derived possessions across 9 NBA seasons.

---

## Architecture

```
NBA API (nba_api)
      ↓
ETL Pipeline (Python + pandas)
      ↓
PostgreSQL Database (Docker)
      ↓
Analytics API (FastAPI)
      ↓
Shot Quality Model (XGBoost)
```

| Layer | Technology |
|---|---|
| Data Ingestion | Python, nba_api, pandas |
| Database | PostgreSQL 16 (Docker) |
| Backend API | FastAPI, SQLAlchemy, Pydantic |
| ML Model | scikit-learn, XGBoost |
| NLP Narratives | Claude API *(Phase 4 — in progress)* |
| Frontend | React, Recharts *(Phase 5 — planned)* |

---

## Database

9 seasons of real NBA data (2015-16 through 2023-24):

| Table | Rows | Source |
|---|---|---|
| teams | 30 | NBA API |
| players | 5,103 | NBA API |
| games | 11,499 | NBA API |
| play_events | 5,614,774 | NBA API (PlayByPlayV3) |
| shots | 2,008,598 | NBA API (ShotChartDetail) |
| possessions | 1,955,234 | Derived from play_events |

Possessions are not an NBA API field — they're derived by running a state machine over the raw play-by-play sequence, tracking ball possession through made shots, rebounds, turnovers, and end-of-period events.

---

## API Endpoints

Once running, visit `http://localhost:8000/docs` for interactive documentation.

| Endpoint | Description |
|---|---|
| `GET /games` | Paginated game list, filterable by season and team |
| `GET /games/{id}/summary` | Per-quarter possession efficiency for both teams |
| `GET /player/{id}/efficiency` | TS%, eFG%, FTA, turnovers from raw play data |
| `GET /possessions/{game_id}` | Raw possession log for a game |
| `GET /momentum/{game_id}` | Quarter-by-quarter efficiency comparison |
| `GET /health` | Service health check |

---

## Shot Quality Model

Trained on 1.6 million shots to predict the probability any shot goes in (xFG%).

**Expected points by zone (XGBoost vs actual):**

| Zone | xPTS | Actual PTS |
|---|---|---|
| Restricted Area | 1.271 | 1.274 |
| Corner 3 | 1.158 | 1.162 |
| Above the Break 3 | 1.060 | 1.050 |
| In Paint (Non-RA) | 0.840 | 0.840 |
| Mid-Range | 0.815 | 0.810 |

Log Loss: 0.653 (vs 0.690 baseline). Well-calibrated across the full probability range.

---

## Running Locally

**Prerequisites:** Python 3.10+, Docker Desktop, Git

```bash
# 1. Clone and set up environment
git clone https://github.com/phitly/basketball-ai.git
cd basketball-ai
python -m venv venv
source venv/Scripts/activate      # Windows (Git Bash)
source venv/bin/activate           # Mac/Linux
pip install -r requirements.txt

# 2. Configure database credentials
cp .env.example .env               # edit if needed (defaults match Docker setup)

# 3. Start the database
docker compose up -d

# 4. Run the API
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Visit http://localhost:8000/docs
```

> **Note:** The database comes empty. To populate it, run the ETL scripts in order — see [docs/session_01_phase1.md](docs/session_01_phase1.md) for the full ingest process. Expect ~5 hours for the full dataset.

---

## Running the ML Model

```bash
# Train both models (requires populated database, ~2 minutes)
python ml/shot_quality/train.py

# Full error analysis
python ml/shot_quality/evaluate.py
```

Pre-trained models are saved at `ml/shot_quality/models/`.

---

## Project Status

| Phase | Description | Status |
|---|---|---|
| 1 | ETL Pipeline + PostgreSQL schema | ✅ Complete |
| 2 | FastAPI analytics endpoints | ✅ Complete |
| 3 | Shot quality ML model | ✅ Complete |
| 4 | NLP narrative generation | 🔄 In progress |
| 5 | React frontend dashboard | ⬜ Planned |
| 6 | Docker + AWS deployment | ⬜ Planned |

---

## Design Decisions

**LLM for translation, not analysis.** The metrics engine computes efficiency numbers. The language model translates them into plain English. Every output is verifiable against the underlying data.

**Possession-level, not box score.** Traditional stats aggregate across full games. This system works at the possession level — surfacing momentum shifts, quarter-by-quarter breakdowns, and lineup efficiency that box scores hide.

**Honest ML.** The shot quality model is documented with its limitations: zone dominates (84% feature importance), defender proximity is missing, player identity is not a feature. A model you can critique is a model you understand.

---

## Repository Structure

```
basketball-ai/
├── data_pipeline/     — ETL scripts (ingest, transform, load)
├── backend/           — FastAPI application
│   ├── routers/       — endpoint definitions
│   ├── services/      — basketball metrics math
│   └── tests/         — unit + integration tests
├── ml/
│   └── shot_quality/  — training, evaluation, saved models
├── docs/              — session notes per phase
├── schema.sql         — PostgreSQL DDL
└── docker-compose.yml
```
