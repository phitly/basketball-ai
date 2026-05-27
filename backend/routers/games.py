"""
routers/games.py

Endpoints:
  GET /games                  — paginated list of games
  GET /games/{game_id}/summary — full possession-level summary for one game
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from database import get_db
from models import Game, Team, Possession
from schemas import GameOut, GameListOut, GameSummaryOut, TeamGameSummaryOut, PeriodEfficiencyOut
from services.metrics import summarize_game_possessions

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=GameListOut)
def list_games(
    season: str | None = Query(None, description="Filter by season, e.g. '2023-24'"),
    team_id: int | None = Query(None, description="Filter games involving this team"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Return a paginated list of games.

    Optional filters: season and/or team_id.
    """
    stmt = select(Game)

    if season:
        stmt = stmt.where(Game.season == season)
    if team_id:
        stmt = stmt.where(
            (Game.home_team_id == team_id) | (Game.away_team_id == team_id)
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    games = db.scalars(stmt.order_by(Game.game_date.desc()).offset(offset).limit(limit)).all()

    return GameListOut(total=total or 0, games=[GameOut.model_validate(g) for g in games])


@router.get("/{game_id}/summary", response_model=GameSummaryOut)
def get_game_summary(game_id: str, db: Session = Depends(get_db)):
    """
    Full possession-level summary for a single game.

    Returns per-quarter efficiency, transition vs. half-court breakdown,
    and outcome distribution for both teams.
    """
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail=f"Game {game_id!r} not found")

    home_team = db.get(Team, game.home_team_id)
    away_team = db.get(Team, game.away_team_id)

    # Fetch all possessions for this game
    possessions = db.scalars(
        select(Possession).where(Possession.game_id == game_id)
    ).all()

    def _to_dict(p: Possession) -> dict:
        return {
            "period": p.period,
            "points_scored": p.points_scored,
            "outcome": p.outcome,
            "is_transition": p.is_transition,
            "start_game_clock": p.start_game_clock,
            "end_game_clock": p.end_game_clock,
        }

    home_poss = [_to_dict(p) for p in possessions if p.team_id == game.home_team_id]
    away_poss = [_to_dict(p) for p in possessions if p.team_id == game.away_team_id]

    def _build_summary(rows, team_id) -> TeamGameSummaryOut | None:
        if not rows:
            return None
        s = summarize_game_possessions(rows, game_id, team_id)
        return TeamGameSummaryOut(
            team_id=s.team_id,
            total_possessions=s.total_possessions,
            total_points=s.total_points,
            overall_ppp=s.overall_ppp,
            by_period=[
                PeriodEfficiencyOut(
                    period=p.period,
                    possessions=p.possessions,
                    points_scored=p.points_scored,
                    ppp=p.ppp,
                    transition_possessions=p.transition_possessions,
                    transition_points=p.transition_points,
                )
                for p in s.by_period
            ],
            outcome_counts=s.outcome_counts,
        )

    return GameSummaryOut(
        game_id=game.game_id,
        game_date=game.game_date,
        home_team=home_team,
        away_team=away_team,
        home_score=game.home_score,
        away_score=game.away_score,
        home_summary=_build_summary(home_poss, game.home_team_id),
        away_summary=_build_summary(away_poss, game.away_team_id),
    )
