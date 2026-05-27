"""
routers/teams.py

Endpoints:
  GET /team/{team_id}/lineup-analysis — five-man lineup efficiency for a team
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from database import get_db
from models import Team, Lineup, Game
from schemas import TeamLineupAnalysisOut, LineupMetricsOut
from services.metrics import compute_lineup_metrics

router = APIRouter(prefix="/team", tags=["teams"])


@router.get("/{team_id}/lineup-analysis", response_model=TeamLineupAnalysisOut)
def get_lineup_analysis(
    team_id: int,
    game_id: str | None = Query(None, description="Scope to a single game"),
    season: str | None = Query(None, description="Filter by season, e.g. '2023-24'"),
    min_possessions: int = Query(5, ge=1, description="Minimum possessions to include a lineup"),
    db: Session = Depends(get_db),
):
    """
    Five-man lineup efficiency for a team.

    Returns offensive/defensive ratings and net rating for every lineup
    that logged at least `min_possessions` possessions. Filter by a specific
    game or season.

    Results are sorted by net rating descending (best lineups first).
    """
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")

    stmt = select(Lineup).where(
        Lineup.team_id == team_id,
        Lineup.possessions_on >= min_possessions,
    )

    if game_id:
        stmt = stmt.where(Lineup.game_id == game_id)
    elif season:
        stmt = stmt.join(Game, Lineup.game_id == Game.game_id).where(Game.season == season)

    lineups = db.scalars(stmt).all()

    metrics: list[LineupMetricsOut] = []
    for lu in lineups:
        m = compute_lineup_metrics({
            "player_ids":       lu.player_ids,
            "time_on_seconds":  lu.time_on_seconds or 0,
            "points_for":       lu.points_for,
            "points_against":   lu.points_against,
            "plus_minus":       lu.plus_minus or 0,
            "possessions_on":   lu.possessions_on,
        })
        metrics.append(LineupMetricsOut(
            player_ids=m.player_ids,
            time_on_seconds=m.time_on_seconds,
            points_for=m.points_for,
            points_against=m.points_against,
            plus_minus=m.plus_minus,
            possessions_on=m.possessions_on,
            ortg=m.ortg,
            drtg=m.drtg,
            net_rtg=m.net_rtg,
        ))

    # Sort best lineups first
    metrics.sort(key=lambda x: x.net_rtg or -999, reverse=True)

    return TeamLineupAnalysisOut(
        team_id=team_id,
        game_id=game_id,
        lineups=metrics,
    )
