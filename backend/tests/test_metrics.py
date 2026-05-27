"""
tests/test_metrics.py — Unit tests for the metrics service.

No database, no server required. Verifies formulas against exact known values.

Run: pytest tests/test_metrics.py -v
"""

import pytest
from services.metrics import (
    true_shooting_pct,
    effective_fg_pct,
    offensive_rating,
    defensive_rating,
    net_rating,
    pace,
    points_per_possession,
    summarize_game_possessions,
    compute_lineup_metrics,
)


# ---------------------------------------------------------------------------
# True Shooting Percentage
# ---------------------------------------------------------------------------

class TestTrueShootingPct:
    def test_perfect_efficiency(self):
        # 20 pts, 10 FGA, 0 FTA → TS% = 20 / (2*10) = 1.0
        assert true_shooting_pct(20, 10, 0) == pytest.approx(1.0, abs=0.0001)

    def test_realistic_line(self):
        # 30 pts, 20 FGA, 5 FTA → 30 / (2*(20+2.2)) = 30/44.4 ≈ 0.6757
        result = true_shooting_pct(30, 20, 5)
        assert result is not None
        assert 0.66 < result < 0.69

    def test_zero_attempts_returns_none(self):
        assert true_shooting_pct(0, 0, 0) is None

    def test_zero_fta(self):
        # 20 pts, 16 FGA, 0 FTA → 20/32 = 0.625
        assert true_shooting_pct(20, 16, 0) == pytest.approx(0.625, abs=0.001)

    def test_only_free_throws(self):
        # 10 pts, 0 FGA, 10 FTA → 10/(2*4.4) = 10/8.8
        assert true_shooting_pct(10, 0, 10) == pytest.approx(10/8.8, abs=0.001)

    def test_rounded_to_4_places(self):
        result = true_shooting_pct(17, 12, 4)
        assert result is not None
        assert len(str(result).split(".")[-1]) <= 4


# ---------------------------------------------------------------------------
# Effective Field Goal Percentage
# ---------------------------------------------------------------------------

class TestEffectiveFgPct:
    def test_no_threes(self):
        # 8 FGM, 0 3PM, 15 FGA → 8/15
        assert effective_fg_pct(8, 0, 15) == pytest.approx(8/15, abs=0.0001)

    def test_all_threes(self):
        # 5 FGM all 3s, 10 FGA → (5+2.5)/10 = 0.75
        assert effective_fg_pct(5, 5, 10) == pytest.approx(0.75, abs=0.0001)

    def test_zero_fga_returns_none(self):
        assert effective_fg_pct(0, 0, 0) is None

    def test_mixed(self):
        # 10 FGM, 4 3PM, 20 FGA → (10+2)/20 = 0.60
        assert effective_fg_pct(10, 4, 20) == pytest.approx(0.60, abs=0.0001)


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------

class TestRatings:
    def test_ortg(self):
        assert offensive_rating(112, 100) == 112.0

    def test_drtg(self):
        assert defensive_rating(108, 100) == 108.0

    def test_zero_possessions_returns_none(self):
        assert offensive_rating(0, 0) is None
        assert defensive_rating(0, 0) is None

    def test_net_rating(self):
        assert net_rating(112.0, 108.0) == 4.0

    def test_net_rating_propagates_none(self):
        assert net_rating(None, 108.0) is None
        assert net_rating(112.0, None) is None


# ---------------------------------------------------------------------------
# Pace
# ---------------------------------------------------------------------------

class TestPace:
    def test_even_pace(self):
        # 100 poss in 48 min → 100.0
        assert pace(100, 48) == 100.0

    def test_fast_team(self):
        assert pace(115, 48) == 115.0

    def test_zero_minutes_returns_none(self):
        assert pace(100, 0) is None


# ---------------------------------------------------------------------------
# Points Per Possession
# ---------------------------------------------------------------------------

class TestPPP:
    def test_typical(self):
        assert points_per_possession(112, 100) == pytest.approx(1.12, abs=0.0001)

    def test_zero_possessions(self):
        assert points_per_possession(0, 0) is None

    def test_elite(self):
        assert points_per_possession(128, 100) == pytest.approx(1.28, abs=0.0001)


# ---------------------------------------------------------------------------
# summarize_game_possessions
# ---------------------------------------------------------------------------

class TestSummarizeGamePossessions:
    def _poss(self, period, points, outcome="made_2", transition=False):
        return {
            "period": period,
            "points_scored": points,
            "outcome": outcome,
            "is_transition": transition,
            "start_game_clock": "10:00",
            "end_game_clock": "09:30",
        }

    def test_empty(self):
        s = summarize_game_possessions([], "G1", 1)
        assert s.total_possessions == 0
        assert s.overall_ppp is None

    def test_totals(self):
        rows = [self._poss(1, 2), self._poss(1, 3, "made_3"), self._poss(2, 0, "turnover")]
        s = summarize_game_possessions(rows, "G1", 1)
        assert s.total_possessions == 3
        assert s.total_points == 5

    def test_ppp(self):
        rows = [self._poss(1, 2) for _ in range(4)]
        s = summarize_game_possessions(rows, "G1", 1)
        assert s.overall_ppp == pytest.approx(2.0, abs=0.001)

    def test_per_period(self):
        rows = [self._poss(1, 2), self._poss(1, 2), self._poss(2, 3, "made_3")]
        s = summarize_game_possessions(rows, "G1", 1)
        assert len(s.by_period) == 2
        q1 = next(p for p in s.by_period if p.period == 1)
        assert q1.possessions == 2
        assert q1.points_scored == 4

    def test_transition(self):
        rows = [self._poss(1, 2, transition=True), self._poss(1, 2)]
        s = summarize_game_possessions(rows, "G1", 1)
        assert s.by_period[0].transition_possessions == 1
        assert s.by_period[0].transition_points == 2

    def test_outcome_counts(self):
        rows = [self._poss(1, 2), self._poss(1, 0, "turnover"), self._poss(1, 0, "turnover")]
        s = summarize_game_possessions(rows, "G1", 1)
        assert s.outcome_counts["turnover"] == 2
        assert s.outcome_counts["made_2"] == 1


# ---------------------------------------------------------------------------
# compute_lineup_metrics
# ---------------------------------------------------------------------------

class TestComputeLineupMetrics:
    def test_basic(self):
        row = {
            "player_ids": [1, 2, 3, 4, 5],
            "time_on_seconds": 600.0,
            "points_for": 12,
            "points_against": 10,
            "plus_minus": 2,
            "possessions_on": 10,
        }
        m = compute_lineup_metrics(row)
        assert m.ortg == pytest.approx(120.0)
        assert m.drtg == pytest.approx(100.0)
        assert m.net_rtg == pytest.approx(20.0)

    def test_zero_possessions(self):
        row = {
            "player_ids": [1, 2, 3, 4, 5],
            "time_on_seconds": 0,
            "points_for": 0,
            "points_against": 0,
            "plus_minus": 0,
            "possessions_on": 0,
        }
        m = compute_lineup_metrics(row)
        assert m.ortg is None
        assert m.drtg is None
        assert m.net_rtg is None
