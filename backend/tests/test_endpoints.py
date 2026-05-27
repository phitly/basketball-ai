"""
tests/test_endpoints.py — Integration tests for API endpoints.

These tests use FastAPI's TestClient (httpx under the hood) to make real
HTTP calls against the app, but with a patched database session so no
real PostgreSQL connection is needed.

The pattern:
  1. Create a real SQLite in-memory database for tests (not PostgreSQL).
  2. Override the `get_db` dependency to use the test DB.
  3. Seed minimal data.
  4. Hit endpoints, assert responses.

SQLite works fine for testing because SQLAlchemy abstracts the dialect.
The one exception: PostgreSQL-specific types like ARRAY won't serialize the
same way. The lineups tests work around this by checking structure only.

Run: pytest tests/test_endpoints.py -v
"""

import pytest
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
from models import Team, Game, Player, Possession, Lineup


# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite://"  # in-memory, wiped after each test session

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# SQLite doesn't enforce foreign keys by default — enable them
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Create tables once for the test module, then drop them."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """Fresh session per test, always rolled back."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    """TestClient with get_db overridden to use the test session."""
    def override_get_db():
        try:
            yield db
        finally:
            pass  # rollback handled by `db` fixture

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def make_team(db, team_id: int, abbrev: str, name: str, city: str) -> Team:
    t = Team(
        team_id=team_id,
        abbreviation=abbrev,
        name=name,
        city=city,
        conference="East",
        division="Atlantic",
    )
    db.add(t)
    db.flush()
    return t


def make_game(db, game_id: str, home_id: int, away_id: int) -> Game:
    g = Game(
        game_id=game_id,
        game_date=date(2024, 1, 15),
        season="2023-24",
        season_type="Regular Season",
        home_team_id=home_id,
        away_team_id=away_id,
        home_score=112,
        away_score=108,
        status="Final",
    )
    db.add(g)
    db.flush()
    return g


def make_possession(db, game_id, team_id, period, points, outcome="made_2", is_transition=False):
    p = Possession(
        game_id=game_id,
        team_id=team_id,
        period=period,
        outcome=outcome,
        points_scored=points,
        is_transition=is_transition,
    )
    db.add(p)
    db.flush()
    return p


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /games
# ---------------------------------------------------------------------------

class TestListGames:
    def test_returns_empty_when_no_games(self, client):
        r = client.get("/games")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["games"] == []

    def test_returns_seeded_game(self, client, db):
        t1 = make_team(db, 101, "BOS", "Celtics", "Boston")
        t2 = make_team(db, 102, "MIA", "Heat", "Miami")
        make_game(db, "GAME0001", t1.team_id, t2.team_id)

        r = client.get("/games")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        ids = [g["game_id"] for g in body["games"]]
        assert "GAME0001" in ids

    def test_season_filter(self, client, db):
        t1 = make_team(db, 201, "LAL", "Lakers", "Los Angeles")
        t2 = make_team(db, 202, "GSW", "Warriors", "Golden State")
        g = Game(
            game_id="GAME0002",
            game_date=date(2023, 1, 10),
            season="2022-23",
            season_type="Regular Season",
            home_team_id=t1.team_id,
            away_team_id=t2.team_id,
            status="Final",
        )
        db.add(g)
        db.flush()

        r = client.get("/games?season=2022-23")
        assert r.status_code == 200
        ids = [g["game_id"] for g in r.json()["games"]]
        assert "GAME0002" in ids

    def test_pagination(self, client, db):
        r = client.get("/games?limit=1&offset=0")
        assert r.status_code == 200
        assert len(r.json()["games"]) <= 1


# ---------------------------------------------------------------------------
# GET /games/{game_id}/summary
# ---------------------------------------------------------------------------

class TestGameSummary:
    def test_404_for_unknown_game(self, client):
        r = client.get("/games/NOTAREAL/summary")
        assert r.status_code == 404

    def test_summary_structure(self, client, db):
        t1 = make_team(db, 301, "DEN", "Nuggets", "Denver")
        t2 = make_team(db, 302, "PHX", "Suns", "Phoenix")
        make_game(db, "GAME0003", t1.team_id, t2.team_id)
        for _ in range(3):
            make_possession(db, "GAME0003", t1.team_id, 1, 2)
        for _ in range(2):
            make_possession(db, "GAME0003", t2.team_id, 1, 3, outcome="made_3")

        r = client.get("/games/GAME0003/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["game_id"] == "GAME0003"
        assert "home_summary" in body
        assert "away_summary" in body
        home = body["home_summary"]
        assert home["total_possessions"] == 3
        assert home["total_points"] == 6
        assert home["overall_ppp"] == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# GET /possessions/{game_id}
# ---------------------------------------------------------------------------

class TestPossessions:
    def test_404_for_missing_game(self, client):
        r = client.get("/possessions/NOPE")
        assert r.status_code == 404

    def test_returns_possessions(self, client, db):
        t1 = make_team(db, 401, "SAS", "Spurs", "San Antonio")
        t2 = make_team(db, 402, "OKC", "Thunder", "Oklahoma City")
        make_game(db, "GAME0004", t1.team_id, t2.team_id)
        make_possession(db, "GAME0004", t1.team_id, 1, 2)
        make_possession(db, "GAME0004", t2.team_id, 1, 0, outcome="turnover")

        r = client.get("/possessions/GAME0004")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        outcomes = {p["outcome"] for p in body["possessions"]}
        assert "made_2" in outcomes
        assert "turnover" in outcomes

    def test_period_filter(self, client, db):
        t1 = make_team(db, 501, "CLE", "Cavaliers", "Cleveland")
        t2 = make_team(db, 502, "IND", "Pacers", "Indianapolis")
        make_game(db, "GAME0005", t1.team_id, t2.team_id)
        make_possession(db, "GAME0005", t1.team_id, 1, 2)
        make_possession(db, "GAME0005", t1.team_id, 2, 3)

        r = client.get("/possessions/GAME0005?period=1")
        assert r.status_code == 200
        assert r.json()["total"] == 1


# ---------------------------------------------------------------------------
# GET /momentum/{game_id}
# ---------------------------------------------------------------------------

class TestMomentum:
    def test_404_for_missing_game(self, client):
        r = client.get("/momentum/NOPE")
        assert r.status_code == 404

    def test_momentum_structure(self, client, db):
        t1 = make_team(db, 601, "MIL", "Bucks", "Milwaukee")
        t2 = make_team(db, 602, "CHI", "Bulls", "Chicago")
        make_game(db, "GAME0006", t1.team_id, t2.team_id)
        for _ in range(4):
            make_possession(db, "GAME0006", t1.team_id, 1, 2)
        for _ in range(4):
            make_possession(db, "GAME0006", t2.team_id, 1, 2)

        r = client.get("/momentum/GAME0006")
        assert r.status_code == 200
        body = r.json()
        assert body["game_id"] == "GAME0006"
        assert isinstance(body["windows"], list)
        assert len(body["windows"]) >= 1
        w = body["windows"][0]
        assert "period" in w
        assert "home_ppp" in w
        assert "away_ppp" in w
