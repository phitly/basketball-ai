"""
database.py — SQLAlchemy engine and session factory.

Two things live here:
  1. `engine`   — the connection pool (created once at import time).
  2. `get_db()` — a FastAPI dependency that opens a session per request
                  and closes it when the response is sent.

Usage in a router:
    from database import get_db
    from sqlalchemy.orm import Session

    @router.get("/example")
    def example(db: Session = Depends(get_db)):
        ...
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# pool_pre_ping=True makes SQLAlchemy test the connection before using it.
# This quietly reconnects after the DB was restarted without crashing the API.
engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    echo=settings.debug,   # prints SQL statements when DEBUG=true — useful for dev
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# autocommit=False  → you control when transactions commit
# autoflush=False   → SQLAlchemy won't emit SQL until you explicitly flush/commit
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Base class for ORM models
# ---------------------------------------------------------------------------
# All models in models.py inherit from this.
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db():
    """
    Yield a database session for the duration of one request.

    FastAPI calls this before your route function runs and closes the session
    after the response is sent — even if an exception was raised.
    The `finally` block guarantees cleanup regardless of what happens.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
