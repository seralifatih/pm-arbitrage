import pytest

from src.core.scorer import score_opportunity


class TestPerfectCase:
    def test_max_score_pure_arbitrage(self):
        score, label = score_opportunity(
            gross_spread_pct=8.0,
            net_spread_pct=5.0,
            fillable=True,
            match_confidence=95,
            days_to_resolution=5,
        )
        # 40 + 25 + 19 + 15 = 99
        assert score >= 85
        assert label == "Pure arbitrage"

    def test_strong_ev_plus_when_negative_spread_high_score(self):
        # Force score >= 80 but net_spread_pct <= 0
        score, label = score_opportunity(
            gross_spread_pct=2.0,
            net_spread_pct=-0.5,
            fillable=True,
            match_confidence=100,
            days_to_resolution=5,
        )
        # 0 + 25 + 20 + 15 = 60 → not >= 80, adjust
        # Try different combo: score still below 80 since net_spread pts is 0
        # Impossible to hit >= 80 with net_spread <= 0 given ceiling 25+20+15 = 60
        # So this path is unreachable in practice; still verify logic below 80.
        assert score <= 80


class TestZeroNetSpread:
    def test_zero_net_spread_no_points_from_spread(self):
        score, label = score_opportunity(
            gross_spread_pct=2.0,
            net_spread_pct=0.0,
            fillable=True,
            match_confidence=90,
            days_to_resolution=10,
        )
        # 0 + 25 + 18 + 15 = 58 → EV+ with edge
        assert score == 58
        assert label == "EV+ with edge"

    def test_zero_net_spread_low_confidence_marginal(self):
        score, label = score_opportunity(
            gross_spread_pct=0.0,
            net_spread_pct=0.0,
            fillable=False,
            match_confidence=70,
            days_to_resolution=100,
        )
        # 0 + 0 + 14 + 0 = 14 → Marginal
        assert score == 14
        assert label == "Marginal"


class TestLiquidityComponent:
    def test_fillable_true_full_25(self):
        s_true, _ = score_opportunity(0, 0, True, 0, 200)
        s_false, _ = score_opportunity(0, 0, False, 0, 200)
        assert s_true - s_false == 25

    def test_fillable_none_partial_12(self):
        s_none, _ = score_opportunity(0, 0, None, 0, 200)
        s_false, _ = score_opportunity(0, 0, False, 0, 200)
        assert s_none - s_false == 12

    def test_fillable_false_zero(self):
        score, _ = score_opportunity(0, 0, False, 0, 200)
        assert score == 0


class TestDaysComponent:
    def test_zero_days_full_15(self):
        score, _ = score_opportunity(0, 0, False, 0, 0)
        assert score == 15

    def test_30_days_full_15(self):
        score, _ = score_opportunity(0, 0, False, 0, 30)
        assert score == 15

    def test_31_days_half(self):
        score, _ = score_opportunity(0, 0, False, 0, 31)
        assert score == 7

    def test_90_days_half(self):
        score, _ = score_opportunity(0, 0, False, 0, 90)
        assert score == 7

    def test_100_days_zero(self):
        score, _ = score_opportunity(0, 0, False, 0, 100)
        assert score == 0

    def test_far_future_zero(self):
        score, _ = score_opportunity(0, 0, False, 0, 500)
        assert score == 0


class TestNetSpreadLinear:
    def test_spread_5_full_40(self):
        score, _ = score_opportunity(10, 5.0, False, 0, 200)
        assert score == 40

    def test_spread_above_5_caps_at_40(self):
        score, _ = score_opportunity(20, 10.0, False, 0, 200)
        assert score == 40

    def test_spread_2_5_half_of_40(self):
        score, _ = score_opportunity(5, 2.5, False, 0, 200)
        assert score == 20  # 2.5/5.0 * 40

    def test_negative_spread_zero(self):
        score, _ = score_opportunity(1, -2.0, False, 0, 200)
        assert score == 0


class TestMatchConfidenceScaling:
    def test_100_confidence_full_20(self):
        score, _ = score_opportunity(0, 0, False, 100, 200)
        assert score == 20

    def test_50_confidence_half(self):
        score, _ = score_opportunity(0, 0, False, 50, 200)
        assert score == 10

    def test_zero_confidence_zero(self):
        score, _ = score_opportunity(0, 0, False, 0, 200)
        assert score == 0


class TestLabelBoundaries:
    def test_label_pure_arb_only_if_net_positive(self):
        # net positive + score >= 80
        score, label = score_opportunity(10, 5.0, True, 100, 10)
        assert score >= 80
        assert label == "Pure arbitrage"

    def test_label_60_to_79_strong_ev_plus(self):
        # Target score 60-79 range: 20 (2.5% net) + 25 + 20 (100 conf) + 15 = 80 → too high
        # 10 (1.25% net) + 25 + 20 + 15 = 70
        score, label = score_opportunity(3, 1.25, True, 100, 10)
        assert 60 <= score <= 79
        assert label == "Strong EV+ signal"

    def test_label_40_to_59_ev_with_edge(self):
        # 0 + 25 + 20 + 0 = 45
        score, label = score_opportunity(0, 0, True, 100, 200)
        assert 40 <= score <= 59
        assert label == "EV+ with edge"

    def test_label_below_40_marginal(self):
        score, label = score_opportunity(0, 0, False, 50, 200)
        assert score < 40
        assert label == "Marginal"


class TestReturnShape:
    def test_returns_tuple(self):
        result = score_opportunity(1.0, 0.5, True, 80, 20)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_score_is_int(self):
        score, _ = score_opportunity(1.0, 0.5, True, 80, 20)
        assert isinstance(score, int)

    def test_label_is_str(self):
        _, label = score_opportunity(1.0, 0.5, True, 80, 20)
        assert isinstance(label, str)

    def test_score_clamped_0_to_100(self):
        score, _ = score_opportunity(100, 50, True, 100, 0)
        assert 0 <= score <= 100
