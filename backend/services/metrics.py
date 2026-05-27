"""
services/metrics.py — Basketball metrics calculations.

All functions here are pure Python. No FastAPI imports, no database calls.
Functions receive pre-fetched data (dicts or lists) and return computed values.

This makes every formula independently testable without a running server or DB.

Sources for formulas:
  - TS%, eFG%:  Basketball Reference Glossary
  - Ortg/Drtg:  Dean Oliver "Basketball on Paper" (simplified version)
  - Pace:       NBA Stats methodology
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Shooting Efficiency
# ---------------------------------------------------------------------------

def true_shooting_pct(
    points: float,
    fga: float,
    fta: float,
) -> Optional[float]:
    """
    True Shooting Percentage (TS%).

    Measures shooting efficiency accounting for 2-pointers, 3-pointers,
    and free throws. The 0.44 coefficient approximates that roughly 44% of
    free throw trips count as a "possession" (accounts for and-ones, technical
    fouls, etc.).

    Formula:  TS% = Points / (2 × (FGA + 0.44 × FTA))

    Returns None when the denominator is zero (player took no shots).
    """
    denominator = 2 * (fga + 0.44 * fta)
    if denominator == 0:
        return None
    return round(points / denominator, 4)


def effective_fg_pct(
    fgm: float,
    fg3m: float,
    fga: float,
) -> Optional[float]:
    """
    Effective Field Goal Percentage (eFG%).

    Adjusts FG% to account for the extra value of 3-pointers. A made 3 is
    worth 1.5x a made 2, so it gets a 0.5 bonus in the numerator.

    Formula:  eFG% = (FGM + 0.5 × 3PM) / FGA

    Returns None when FGA is zero.
    """
    if fga == 0:
        return None
    return round((fgm + 0.5 * fg3m) / fga, 4)


# ---------------------------------------------------------------------------
# Rating / Pace
# ---------------------------------------------------------------------------

def offensive_rating(
    points_scored: float,
    possessions: float,
) -> Optional[float]:
    """
    Offensive Rating (ORtg) — points scored per 100 possessions.

    The per-100 normalization lets you compare teams regardless of pace.
    A team that plays fast will score more points in absolute terms, but
    their efficiency (points per possession) is what tells you how good they are.

    Typical NBA range: 105–120 points per 100 possessions.

    Returns None when possession count is zero.
    """
    if possessions == 0:
        return None
    return round((points_scored / possessions) * 100, 2)


def defensive_rating(
    points_allowed: float,
    possessions: float,
) -> Optional[float]:
    """
    Defensive Rating (DRtg) — points allowed per 100 possessions.

    Lower is better. An elite defensive team allows ~108; a poor one allows ~118.

    Returns None when possession count is zero.
    """
    if possessions == 0:
        return None
    return round((points_allowed / possessions) * 100, 2)


def net_rating(ortg: Optional[float], drtg: Optional[float]) -> Optional[float]:
    """
    Net Rating = ORtg − DRtg.

    The single best predictor of team quality. Elite teams are typically
    +5 to +10; playoff-bubble teams hover near 0; lottery teams go negative.
    """
    if ortg is None or drtg is None:
        return None
    return round(ortg - drtg, 2)


def pace(
    possessions: float,
    minutes_played: float,
    regulation_minutes: float = 48.0,
) -> Optional[float]:
    """
    Pace — estimated possessions per 48 minutes (one regulation game).

    Allows comparison across games of different lengths (overtime) and
    team styles (run-and-gun vs. grind-it-out).

    Formula:  Pace = (Possessions / Minutes) × 48

    Returns None when minutes_played is zero.
    """
    if minutes_played == 0:
        return None
    return round((possessions / minutes_played) * regulation_minutes, 2)


def usage_rate(
    fga: float,
    fta: float,
    turnovers: float,
    team_fga: float,
    team_fta: float,
    team_turnovers: float,
    minutes_played: float,
    team_minutes: float = 240.0,  # 5 players × 48 minutes
) -> Optional[float]:
    """
    Usage Rate — percentage of team possessions a player uses while on the floor.

    A usage rate near 30%+ is a primary option; 15–20% is a role player.
    Useful for contextualizing efficiency — a player shooting 50% TS% with
    30% usage is more impressive than 50% TS% with 10% usage.

    Formula (simplified Dean Oliver):
      USG% = 100 × ((FGA + 0.44×FTA + TOV) × (TeamMinutes/5))
              / (MinutesPlayed × (TeamFGA + 0.44×TeamFTA + TeamTOV))

    Returns None when the denominator is zero.
    """
    if minutes_played == 0:
        return None
    player_possessions = fga + 0.44 * fta + turnovers
    team_possessions = team_fga + 0.44 * team_fta + team_turnovers
    if team_possessions == 0:
        return None
    denominator = minutes_played * team_possessions
    if denominator == 0:
        return None
    return round(
        100 * (player_possessions * (team_minutes / 5)) / denominator,
        2,
    )


# ---------------------------------------------------------------------------
# Possession-Level Analysis
# ---------------------------------------------------------------------------

@dataclass
class PeriodEfficiency:
    """Efficiency breakdown for one period (quarter / OT)."""
    period: int
    possessions: int
    points_scored: int
    ppp: Optional[float]            # points per possession
    transition_possessions: int = 0
    transition_points: int = 0


@dataclass
class GamePossessionSummary:
    """Full possession-level breakdown for one team in one game."""
    game_id: str
    team_id: int
    total_possessions: int
    total_points: int
    overall_ppp: Optional[float]
    by_period: list[PeriodEfficiency] = field(default_factory=list)
    outcome_counts: dict[str, int] = field(default_factory=dict)


def points_per_possession(
    points: float,
    possessions: float,
) -> Optional[float]:
    """
    Points Per Possession (PPP).

    The raw possession-efficiency number. NBA average is roughly 1.12–1.18.
    Anything above 1.20 on meaningful volume is elite; below 1.00 is poor.

    Returns None when possessions is zero.
    """
    if possessions == 0:
        return None
    return round(points / possessions, 4)


def summarize_game_possessions(
    possession_rows: list[dict],
    game_id: str,
    team_id: int,
) -> GamePossessionSummary:
    """
    Build a GamePossessionSummary from a list of possession row dicts.

    Each dict must have keys: period, points_scored, outcome, is_transition.
    These come straight from the possessions table query result.
    """
    if not possession_rows:
        return GamePossessionSummary(
            game_id=game_id,
            team_id=team_id,
            total_possessions=0,
            total_points=0,
            overall_ppp=None,
        )

    # Aggregate totals
    total_points = sum(r["points_scored"] for r in possession_rows)
    total_poss = len(possession_rows)

    # Outcome distribution
    outcome_counts: dict[str, int] = {}
    for r in possession_rows:
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1

    # Per-period breakdown
    periods: dict[int, list[dict]] = {}
    for r in possession_rows:
        periods.setdefault(r["period"], []).append(r)

    by_period: list[PeriodEfficiency] = []
    for period in sorted(periods.keys()):
        poss_list = periods[period]
        pts = sum(p["points_scored"] for p in poss_list)
        transition = [p for p in poss_list if p["is_transition"]]
        by_period.append(PeriodEfficiency(
            period=period,
            possessions=len(poss_list),
            points_scored=pts,
            ppp=points_per_possession(pts, len(poss_list)),
            transition_possessions=len(transition),
            transition_points=sum(p["points_scored"] for p in transition),
        ))

    return GamePossessionSummary(
        game_id=game_id,
        team_id=team_id,
        total_possessions=total_poss,
        total_points=total_points,
        overall_ppp=points_per_possession(total_points, total_poss),
        by_period=by_period,
        outcome_counts=outcome_counts,
    )


# ---------------------------------------------------------------------------
# Lineup Analysis
# ---------------------------------------------------------------------------

@dataclass
class LineupMetrics:
    """Computed metrics for one five-man lineup."""
    player_ids: list[int]
    time_on_seconds: float
    points_for: int
    points_against: int
    plus_minus: int
    possessions_on: int
    ortg: Optional[float]   # offensive rating for this lineup
    drtg: Optional[float]   # defensive rating for this lineup
    net_rtg: Optional[float]


def compute_lineup_metrics(lineup_row: dict) -> LineupMetrics:
    """
    Compute offensive/defensive ratings for a five-man lineup row.

    The lineup row must have keys: player_ids, time_on_seconds,
    points_for, points_against, plus_minus, possessions_on.
    """
    poss = lineup_row.get("possessions_on", 0)
    ortg = offensive_rating(lineup_row["points_for"], poss)
    drtg = defensive_rating(lineup_row["points_against"], poss)
    return LineupMetrics(
        player_ids=lineup_row["player_ids"],
        time_on_seconds=lineup_row.get("time_on_seconds") or 0,
        points_for=lineup_row["points_for"],
        points_against=lineup_row["points_against"],
        plus_minus=lineup_row["plus_minus"],
        possessions_on=poss,
        ortg=ortg,
        drtg=drtg,
        net_rtg=net_rating(ortg, drtg),
    )


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

@dataclass
class MomentumWindow:
    """Score margin and efficiency across a short time window."""
    period: int
    start_clock: str        # MM:SS remaining at window start
    end_clock: str          # MM:SS remaining at window end
    home_points: int
    away_points: int
    home_ppp: Optional[float]
    away_ppp: Optional[float]
    home_possessions: int
    away_possessions: int


def build_momentum_windows(
    possession_rows: list[dict],
    window_size: int = 5,
) -> list[MomentumWindow]:
    """
    Slice possession data into rolling windows of `window_size` possessions per team.

    This surfaces momentum shifts: stretches where one team dominated.
    The window slides possession-by-possession, alternating between teams.

    Returns a list of MomentumWindow objects ordered chronologically.

    NOTE: possession_rows must include both teams' possessions sorted by
    period ASC, then game_clock DESC (descending because clock counts down).
    Each row must have: team_id, period, start_game_clock, end_game_clock,
    points_scored, is_transition.
    """
    if not possession_rows:
        return []

    # Group by period, interleave home and away possessions chronologically
    # For now, emit one window per period summarizing each team's efficiency.
    # A more sophisticated sliding window is straightforward to add later.
    by_period: dict[int, dict] = {}
    for row in possession_rows:
        period = row["period"]
        team = row["team_id"]
        if period not in by_period:
            by_period[period] = {}
        if team not in by_period[period]:
            by_period[period][team] = {"points": 0, "possessions": 0,
                                        "start": None, "end": None}
        by_period[period][team]["points"] += row["points_scored"]
        by_period[period][team]["possessions"] += 1
        if by_period[period][team]["start"] is None:
            by_period[period][team]["start"] = row.get("start_game_clock", "")
        by_period[period][team]["end"] = row.get("end_game_clock", "")

    windows: list[MomentumWindow] = []
    for period in sorted(by_period.keys()):
        teams = list(by_period[period].keys())
        if len(teams) < 2:
            continue
        t1, t2 = teams[0], teams[1]
        d1, d2 = by_period[period][t1], by_period[period][t2]
        windows.append(MomentumWindow(
            period=period,
            start_clock=d1["start"] or "",
            end_clock=d1["end"] or "",
            home_points=d1["points"],
            away_points=d2["points"],
            home_ppp=points_per_possession(d1["points"], d1["possessions"]),
            away_ppp=points_per_possession(d2["points"], d2["possessions"]),
            home_possessions=d1["possessions"],
            away_possessions=d2["possessions"],
        ))

    return windows
