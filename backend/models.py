"""
models.py — SQLAlchemy ORM models.

Each class maps to one table in schema.sql. Column types, constraints, and
relationships mirror the schema exactly — if you change the schema, update
these models to match.

Note on GENERATED ALWAYS AS columns (full_name, score_margin, plus_minus):
  PostgreSQL computes these automatically. We mark them server_default=""
  so SQLAlchemy never tries to INSERT a value for them.
"""

from datetime import date, datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean, CheckConstraint, Date, ForeignKey, Integer,
    Numeric, SmallInteger, String, Text, TIMESTAMP, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ---------------------------------------------------------------------------
# teams
# ---------------------------------------------------------------------------
class Team(Base):
    __tablename__ = "teams"

    team_id:        Mapped[int]           = mapped_column(Integer, primary_key=True)
    abbreviation:   Mapped[str]           = mapped_column(String(5), nullable=False)
    name:           Mapped[str]           = mapped_column(String(100), nullable=False)
    city:           Mapped[str]           = mapped_column(String(100), nullable=False)
    conference:     Mapped[str]           = mapped_column(String(10), nullable=False)
    division:       Mapped[str]           = mapped_column(String(50), nullable=False)
    created_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))
    updated_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    # Relationships
    players:    Mapped[List["Player"]]    = relationship("Player", back_populates="team")
    home_games: Mapped[List["Game"]]      = relationship("Game", foreign_keys="Game.home_team_id", back_populates="home_team")
    away_games: Mapped[List["Game"]]      = relationship("Game", foreign_keys="Game.away_team_id", back_populates="away_team")

    def __repr__(self) -> str:
        return f"<Team {self.abbreviation}>"


# ---------------------------------------------------------------------------
# players
# ---------------------------------------------------------------------------
class Player(Base):
    __tablename__ = "players"

    player_id:      Mapped[int]           = mapped_column(Integer, primary_key=True)
    first_name:     Mapped[str]           = mapped_column(String(100), nullable=False)
    last_name:      Mapped[str]           = mapped_column(String(100), nullable=False)
    # full_name is a GENERATED column — never write to it
    full_name:      Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    position:       Mapped[Optional[str]] = mapped_column(String(20))
    height_inches:  Mapped[Optional[int]] = mapped_column(SmallInteger)
    weight_lbs:     Mapped[Optional[int]] = mapped_column(SmallInteger)
    birth_date:     Mapped[Optional[date]]= mapped_column(Date)
    team_id:        Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.team_id", ondelete="SET NULL"))
    is_active:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    created_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))
    updated_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    team:           Mapped[Optional["Team"]] = relationship("Team", back_populates="players")

    def __repr__(self) -> str:
        return f"<Player {self.first_name} {self.last_name}>"


# ---------------------------------------------------------------------------
# games
# ---------------------------------------------------------------------------
class Game(Base):
    __tablename__ = "games"

    game_id:        Mapped[str]           = mapped_column(String(12), primary_key=True)
    game_date:      Mapped[date]          = mapped_column(Date, nullable=False)
    season:         Mapped[str]           = mapped_column(String(10), nullable=False)
    season_type:    Mapped[str]           = mapped_column(String(20), nullable=False, default="Regular Season")
    home_team_id:   Mapped[int]           = mapped_column(Integer, ForeignKey("teams.team_id"), nullable=False)
    away_team_id:   Mapped[int]           = mapped_column(Integer, ForeignKey("teams.team_id"), nullable=False)
    home_score:     Mapped[Optional[int]] = mapped_column(SmallInteger)
    away_score:     Mapped[Optional[int]] = mapped_column(SmallInteger)
    status:         Mapped[str]           = mapped_column(String(20), nullable=False, default="Final")
    arena:          Mapped[Optional[str]] = mapped_column(String(100))
    created_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))
    updated_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    home_team:      Mapped["Team"]        = relationship("Team", foreign_keys=[home_team_id], back_populates="home_games")
    away_team:      Mapped["Team"]        = relationship("Team", foreign_keys=[away_team_id], back_populates="away_games")
    play_events:    Mapped[List["PlayEvent"]] = relationship("PlayEvent", back_populates="game", cascade="all, delete-orphan")
    shots:          Mapped[List["Shot"]]  = relationship("Shot", back_populates="game", cascade="all, delete-orphan")
    possessions:    Mapped[List["Possession"]] = relationship("Possession", back_populates="game", cascade="all, delete-orphan")
    lineups:        Mapped[List["Lineup"]] = relationship("Lineup", back_populates="game", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Game {self.game_id} {self.game_date}>"


# ---------------------------------------------------------------------------
# play_events
# ---------------------------------------------------------------------------
class PlayEvent(Base):
    __tablename__ = "play_events"
    __table_args__ = (
        UniqueConstraint("game_id", "event_num", name="uq_play_events_game_event"),
    )

    event_id:       Mapped[int]           = mapped_column(Integer, primary_key=True)
    game_id:        Mapped[str]           = mapped_column(String(12), ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False)
    event_num:      Mapped[int]           = mapped_column(Integer, nullable=False)
    period:         Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    game_clock:     Mapped[str]           = mapped_column(String(10), nullable=False)
    wall_clock:     Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    event_type:     Mapped[str]           = mapped_column(String(50), nullable=False)
    event_subtype:  Mapped[Optional[str]] = mapped_column(String(50))
    player1_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    player1_team_id:Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.team_id"))
    player2_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    player2_team_id:Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.team_id"))
    player3_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.player_id"))
    player3_team_id:Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.team_id"))
    description:    Mapped[Optional[str]] = mapped_column(Text)
    home_score:     Mapped[Optional[int]] = mapped_column(SmallInteger)
    away_score:     Mapped[Optional[int]] = mapped_column(SmallInteger)
    # score_margin is GENERATED — read-only
    score_margin:   Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    created_at:     Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    game: Mapped["Game"] = relationship("Game", back_populates="play_events")

    def __repr__(self) -> str:
        return f"<PlayEvent {self.event_id} {self.event_type}>"


# ---------------------------------------------------------------------------
# shots
# ---------------------------------------------------------------------------
class Shot(Base):
    __tablename__ = "shots"

    shot_id:            Mapped[int]           = mapped_column(Integer, primary_key=True)
    game_id:            Mapped[str]           = mapped_column(String(12), ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False)
    player_id:          Mapped[int]           = mapped_column(Integer, ForeignKey("players.player_id"), nullable=False)
    team_id:            Mapped[int]           = mapped_column(Integer, ForeignKey("teams.team_id"), nullable=False)
    period:             Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    game_clock:         Mapped[str]           = mapped_column(String(10), nullable=False)
    shot_type:          Mapped[str]           = mapped_column(String(10), nullable=False)
    action_type:        Mapped[Optional[str]] = mapped_column(String(100))
    shot_zone_basic:    Mapped[Optional[str]] = mapped_column(String(50))
    shot_zone_area:     Mapped[Optional[str]] = mapped_column(String(50))
    shot_zone_range:    Mapped[Optional[str]] = mapped_column(String(50))
    shot_distance:      Mapped[Optional[int]] = mapped_column(SmallInteger)
    x_coord:            Mapped[Optional[int]] = mapped_column(SmallInteger)
    y_coord:            Mapped[Optional[int]] = mapped_column(SmallInteger)
    made:               Mapped[bool]          = mapped_column(Boolean, nullable=False)
    defender_distance:  Mapped[Optional[float]] = mapped_column(Numeric(4, 1))
    created_at:         Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    game: Mapped["Game"] = relationship("Game", back_populates="shots")

    def __repr__(self) -> str:
        return f"<Shot {self.shot_id} {'made' if self.made else 'missed'}>"


# ---------------------------------------------------------------------------
# possessions
# ---------------------------------------------------------------------------
class Possession(Base):
    __tablename__ = "possessions"

    possession_id:      Mapped[int]           = mapped_column(Integer, primary_key=True)
    game_id:            Mapped[str]           = mapped_column(String(12), ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False)
    team_id:            Mapped[int]           = mapped_column(Integer, ForeignKey("teams.team_id"), nullable=False)
    period:             Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    start_event_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("play_events.event_id"))
    end_event_id:       Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("play_events.event_id"))
    start_game_clock:   Mapped[Optional[str]] = mapped_column(String(10))
    end_game_clock:     Mapped[Optional[str]] = mapped_column(String(10))
    duration_seconds:   Mapped[Optional[float]] = mapped_column(Numeric(5, 1))
    outcome:            Mapped[str]           = mapped_column(String(30), nullable=False)
    points_scored:      Mapped[int]           = mapped_column(SmallInteger, nullable=False, default=0)
    is_transition:      Mapped[bool]          = mapped_column(Boolean, nullable=False, default=False)
    created_at:         Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    game: Mapped["Game"] = relationship("Game", back_populates="possessions")

    def __repr__(self) -> str:
        return f"<Possession {self.possession_id} {self.outcome}>"


# ---------------------------------------------------------------------------
# lineups
# ---------------------------------------------------------------------------
class Lineup(Base):
    __tablename__ = "lineups"

    lineup_id:          Mapped[int]           = mapped_column(Integer, primary_key=True)
    game_id:            Mapped[str]           = mapped_column(String(12), ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False)
    team_id:            Mapped[int]           = mapped_column(Integer, ForeignKey("teams.team_id"), nullable=False)
    player_ids:         Mapped[List[int]]     = mapped_column(ARRAY(Integer), nullable=False)
    period:             Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    start_game_clock:   Mapped[Optional[str]] = mapped_column(String(10))
    end_game_clock:     Mapped[Optional[str]] = mapped_column(String(10))
    time_on_seconds:    Mapped[Optional[float]] = mapped_column(Numeric(6, 1))
    points_for:         Mapped[int]           = mapped_column(SmallInteger, nullable=False, default=0)
    points_against:     Mapped[int]           = mapped_column(SmallInteger, nullable=False, default=0)
    # plus_minus is GENERATED — read-only
    plus_minus:         Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    possessions_on:     Mapped[int]           = mapped_column(SmallInteger, nullable=False, default=0)
    created_at:         Mapped[datetime]      = mapped_column(TIMESTAMP(timezone=True))

    game: Mapped["Game"] = relationship("Game", back_populates="lineups")

    def __repr__(self) -> str:
        return f"<Lineup {self.lineup_id} team={self.team_id}>"
