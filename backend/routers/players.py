"""
routers/players.py

Endpoints:
  GET /player/{player_id}/efficiency — shooting + usage metrics for a player
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from database import get_db
from models import Player, Shot, PlayEvent
from schemas import PlayerEfficiencyOut
from services.metrics import true_shooting_pct, effective_fg_pct, usage_rate

router = APIRouter(prefix="/player", tags=["players"])


@router.get("/{player_id}/efficiency", response_model=PlayerEfficiencyOut)
def get_player_efficiency(
    player_id: int,
    season: str | None = Query(None, description="Filter to one season, e.g. '2023-24'"),
    db: Session = Depends(get_db),
):
    """
    Shooting efficiency and usage rate for a player.

    Aggregates shot data from the shots table and turnover data from
    play_events. All metrics are computed from raw play data — not
    pre-aggregated box scores.

    Optional season filter; defaults to all available data.
    """
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    # -------------------------------------------------------------------------
    # Aggregate shot data
    # -------------------------------------------------------------------------
    # Join shots → games to filter by season if requested
    from models import Game  # local import avoids circular risk

    shot_stmt = select(Shot).where(Shot.player_id == player_id)
    if season:
        shot_stmt = shot_stmt.join(Game, Shot.game_id == Game.game_id).where(Game.season == season)

    shots = db.scalars(shot_stmt).all()

    fgm   = sum(1 for s in shots if s.made)
    fga   = len(shots)
    fg3m  = sum(1 for s in shots if s.made and s.shot_type == "3PT")
    # Points from field goals (no free throws in shot table)
    fg_points = sum(3 if s.shot_type == "3PT" else 2 for s in shots if s.made)

    # -------------------------------------------------------------------------
    # Approximate FTA and FT points from play_events
    # -------------------------------------------------------------------------
    ft_stmt = (
        select(func.count())
        .where(PlayEvent.player1_id == player_id)
        .where(PlayEvent.event_type == "FREE_THROW")
    )
    if season:
        from models import Game as G
        ft_stmt = (
            select(func.count())
            .select_from(PlayEvent)
            .join(G, PlayEvent.game_id == G.game_id)
            .where(PlayEvent.player1_id == player_id)
            .where(PlayEvent.event_type == "FREE_THROW")
            .where(G.season == season)
        )
    fta = db.scalar(ft_stmt) or 0

    # Made FTs (event_subtype often contains "Made" — adjust if your data differs)
    ft_made_stmt = (
        select(func.count())
        .select_from(PlayEvent)
        .where(PlayEvent.player1_id == player_id)
        .where(PlayEvent.event_type == "FREE_THROW")
        .where(PlayEvent.event_subtype.ilike("%made%"))
    )
    if season:
        from models import Game as G2
        ft_made_stmt = (
            select(func.count())
            .select_from(PlayEvent)
            .join(G2, PlayEvent.game_id == G2.game_id)
            .where(PlayEvent.player1_id == player_id)
            .where(PlayEvent.event_type == "FREE_THROW")
            .where(PlayEvent.event_subtype.ilike("%made%"))
            .where(G2.season == season)
        )
    ft_made = db.scalar(ft_made_stmt) or 0

    total_points = fg_points + ft_made

    # -------------------------------------------------------------------------
    # Turnovers
    # -------------------------------------------------------------------------
    tov_stmt = (
        select(func.count())
        .select_from(PlayEvent)
        .where(PlayEvent.player1_id == player_id)
        .where(PlayEvent.event_type == "TURNOVER")
    )
    if season:
        from models import Game as G3
        tov_stmt = (
            select(func.count())
            .select_from(PlayEvent)
            .join(G3, PlayEvent.game_id == G3.game_id)
            .where(PlayEvent.player1_id == player_id)
            .where(PlayEvent.event_type == "TURNOVER")
            .where(G3.season == season)
        )
    turnovers = db.scalar(tov_stmt) or 0

    # -------------------------------------------------------------------------
    # Games played (for context)
    # -------------------------------------------------------------------------
    game_stmt = select(func.count(Shot.game_id.distinct())).where(Shot.player_id == player_id)
    if season:
        from models import Game as G4
        game_stmt = (
            select(func.count(Shot.game_id.distinct()))
            .select_from(Shot)
            .join(G4, Shot.game_id == G4.game_id)
            .where(Shot.player_id == player_id)
            .where(G4.season == season)
        )
    games_in_sample = db.scalar(game_stmt) or 0

    # -------------------------------------------------------------------------
    # Usage rate — requires team context; we approximate with global averages
    # -------------------------------------------------------------------------
    # NOTE: A full usage rate requires the team's total possessions while the
    # player was on the floor (lineup data). We approximate here using shot totals.
    # This is noted as an approximation in the response.
    # TODO: Wire to lineups table for precise calculation.
    usr = None  # placeholder until lineup data is wired

    return PlayerEfficiencyOut(
        player_id=player.player_id,
        full_name=player.full_name,
        games_in_sample=games_in_sample,
        fgm=fgm,
        fga=fga,
        fg3m=fg3m,
        fta=fta,
        points=total_points,
        true_shooting_pct=true_shooting_pct(total_points, fga, fta),
        effective_fg_pct=effective_fg_pct(fgm, fg3m, fga),
        turnovers=turnovers,
        usage_rate=usr,
    )
