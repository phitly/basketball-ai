"""
routers/possessions.py

Endpoints:
  GET /possessions/{game_id}  — raw possession list for a game
  GET /momentum/{game_id}     — per-period momentum windows
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from database import get_db
from models import Game, Possession
from schemas import PossessionListOut, PossessionOut, MomentumOut, MomentumWindowOut
from services.metrics import build_momentum_windows

router = APIRouter(tags=["possessions"])


@router.get("/possessions/{game_id}", response_model=PossessionListOut)
def list_possessions(
    game_id: str,
    team_id: int | None = Query(None, description="Filter to one team"),
    period: int | None = Query(None, ge=1, le=10, description="Filter to one period"),
    db: Session = Depends(get_db),
):
    """
    Raw possession log for a game.

    Useful for debugging the ETL output and building custom analysis.
    Filter by team and/or period.
    """
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail=f"Game {game_id!r} not found")

    stmt = select(Possession).where(Possession.game_id == game_id)
    if team_id:
        stmt = stmt.where(Possession.team_id == team_id)
    if period:
        stmt = stmt.where(Possession.period == period)

    possessions = db.scalars(stmt.order_by(Possession.period, Possession.possession_id)).all()

    return PossessionListOut(
        game_id=game_id,
        total=len(possessions),
        possessions=[PossessionOut.model_validate(p) for p in possessions],
    )


@router.get("/momentum/{game_id}", response_model=MomentumOut)
def get_momentum(game_id: str, db: Session = Depends(get_db)):
    """
    Per-period efficiency breakdown showing momentum shifts.

    Each window summarizes home and away team efficiency (PPP) across
    one period. Future versions will use sliding possession windows for
    finer-grained momentum detection.
    """
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail=f"Game {game_id!r} not found")

    possessions = db.scalars(
        select(Possession)
        .where(Possession.game_id == game_id)
        .order_by(Possession.period, Possession.possession_id)
    ).all()

    rows = [
        {
            "team_id":          p.team_id,
            "period":           p.period,
            "start_game_clock": p.start_game_clock,
            "end_game_clock":   p.end_game_clock,
            "points_scored":    p.points_scored,
            "is_transition":    p.is_transition,
        }
        for p in possessions
    ]

    windows = build_momentum_windows(rows, home_team_id=game.home_team_id)

    return MomentumOut(
        game_id=game_id,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        windows=[
            MomentumWindowOut(
                period=w.period,
                start_clock=w.start_clock,
                end_clock=w.end_clock,
                home_points=w.home_points,
                away_points=w.away_points,
                home_ppp=w.home_ppp,
                away_ppp=w.away_ppp,
                home_possessions=w.home_possessions,
                away_possessions=w.away_possessions,
            )
            for w in windows
        ],
    )
