"""
schemas.py — Pydantic request/response models.

These define the API contract: what JSON the API accepts and returns.
They are separate from models.py (SQLAlchemy ORM) intentionally:
  - ORM models describe database structure
  - Pydantic schemas describe API I/O

model_config = ConfigDict(from_attributes=True) allows Pydantic to read
from ORM objects directly (orm_mode in Pydantic v1 parlance).
"""

from __future__ import annotations
from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Shared config mixin
# ---------------------------------------------------------------------------
class _OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
class TeamOut(_OrmBase):
    team_id:        int
    abbreviation:   str
    name:           str
    city:           str
    conference:     str
    division:       str


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------
class PlayerOut(_OrmBase):
    player_id:      int
    first_name:     str
    last_name:      str
    full_name:      Optional[str]
    position:       Optional[str]
    team_id:        Optional[int]
    is_active:      bool


class PlayerEfficiencyOut(BaseModel):
    """Response for GET /player/{id}/efficiency"""
    player_id:      int
    full_name:      Optional[str]
    games_in_sample: int
    # Shooting
    fgm:            int
    fga:            int
    fg3m:           int
    fta:            int
    points:         int
    true_shooting_pct:      Optional[float]
    effective_fg_pct:       Optional[float]
    # Usage
    turnovers:      int
    usage_rate:     Optional[float]


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------
class GameOut(_OrmBase):
    game_id:        str
    game_date:      date
    season:         str
    season_type:    str
    home_team_id:   int
    away_team_id:   int
    home_score:     Optional[int]
    away_score:     Optional[int]
    status:         str
    arena:          Optional[str]


class GameListOut(BaseModel):
    """Response for GET /games"""
    total:  int
    games:  list[GameOut]


class PeriodEfficiencyOut(BaseModel):
    period:                 int
    possessions:            int
    points_scored:          int
    ppp:                    Optional[float]
    transition_possessions: int
    transition_points:      int


class TeamGameSummaryOut(BaseModel):
    team_id:            int
    total_possessions:  int
    total_points:       int
    overall_ppp:        Optional[float]
    by_period:          list[PeriodEfficiencyOut]
    outcome_counts:     dict[str, int]


class GameSummaryOut(BaseModel):
    """Response for GET /games/{id}/summary"""
    game_id:    str
    game_date:  date
    home_team:  TeamOut
    away_team:  TeamOut
    home_score: Optional[int]
    away_score: Optional[int]
    home_summary: Optional[TeamGameSummaryOut]
    away_summary: Optional[TeamGameSummaryOut]


# ---------------------------------------------------------------------------
# Possessions
# ---------------------------------------------------------------------------
class PossessionOut(_OrmBase):
    possession_id:      int
    game_id:            str
    team_id:            int
    period:             int
    start_game_clock:   Optional[str]
    end_game_clock:     Optional[str]
    duration_seconds:   Optional[float]
    outcome:            str
    points_scored:      int
    is_transition:      bool


class PossessionListOut(BaseModel):
    """Response for GET /possessions/{game_id}"""
    game_id:    str
    total:      int
    possessions: list[PossessionOut]


# ---------------------------------------------------------------------------
# Lineup Analysis
# ---------------------------------------------------------------------------
class LineupMetricsOut(BaseModel):
    player_ids:         list[int]
    time_on_seconds:    float
    points_for:         int
    points_against:     int
    plus_minus:         int
    possessions_on:     int
    ortg:               Optional[float]
    drtg:               Optional[float]
    net_rtg:            Optional[float]


class TeamLineupAnalysisOut(BaseModel):
    """Response for GET /team/{id}/lineup-analysis"""
    team_id:    int
    game_id:    Optional[str]
    lineups:    list[LineupMetricsOut]


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------
class MomentumWindowOut(BaseModel):
    period:             int
    start_clock:        str
    end_clock:          str
    home_points:        int
    away_points:        int
    home_ppp:           Optional[float]
    away_ppp:           Optional[float]
    home_possessions:   int
    away_possessions:   int


class MomentumOut(BaseModel):
    """Response for GET /momentum/{game_id}"""
    game_id:    str
    home_team_id: int
    away_team_id: int
    windows:    list[MomentumWindowOut]
