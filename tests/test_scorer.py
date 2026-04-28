from src.core.scorer import score_opportunity


class TestPureArbitrage:
    def test_high_net_full_fillable_short_dated_short_basket(self):
        # 5% net return, 3 legs, 5 days out, all fillable → max score
        score, label = score_opportunity(
            gross_return_pct=9.0,
            net_return_pct=5.0,
            all_fillable=True,
            leg_count=3,
            days_to_resolution=5,
        )
        assert score >= 90
        assert label == "Pure arbitrage"

    def test_negative_net_does_not_get_pure_arb_label(self):
        score, label = score_opportunity(
            gross_return_pct=4.0,
            net_return_pct=-0.5,
            all_fillable=True,
            leg_count=3,
            days_to_resolution=5,
        )
        # Even at score >= 80, negative net → not "Pure arbitrage"
        assert label != "Pure arbitrage"


class TestNetReturnComponent:
    def test_5pct_full_50(self):
        score, _ = score_opportunity(5.0, 5.0, True, 3, 5)
        # 50 + 30 + 10 + 10 = 100
        assert score == 100

    def test_above_5_caps_at_50(self):
        score, _ = score_opportunity(20.0, 20.0, True, 3, 5)
        assert score == 100

    def test_negative_return_clamps_low(self):
        score, _ = score_opportunity(2.0, -3.0, True, 3, 5)
        # Net -3 → 0 (clamped). 0 + 30 + 10 + 10 = 50
        assert score == 50


class TestLiquidityComponent:
    # Net=0 → 10 pts of "tail credit" (intentional: rewards near-breakeven EV+).
    # All other components are isolated by setting them low.

    def test_all_fillable_full_30(self):
        score, _ = score_opportunity(0.0, 0.0, True, 3, 5)
        # 10 (tail) + 30 (fillable) + 10 (3 legs) + 10 (5 days) = 60
        assert score == 60

    def test_unknown_partial_15(self):
        score, _ = score_opportunity(0.0, 0.0, None, 3, 5)
        # 10 + 15 + 10 + 10 = 45
        assert score == 45

    def test_not_fillable_zero(self):
        score, _ = score_opportunity(0.0, 0.0, False, 3, 5)
        # 10 + 0 + 10 + 10 = 30
        assert score == 30


class TestLegCountComponent:
    # Use net=-1 → 0 tail pts to isolate legs/days components.
    def test_3_legs_full_10(self):
        score, _ = score_opportunity(0.0, -1.0, False, 3, 200)
        # 0 + 0 + 10 + 0 = 10
        assert score == 10

    def test_10_legs_zero(self):
        score, _ = score_opportunity(0.0, -1.0, False, 10, 200)
        assert score == 0

    def test_more_than_10_legs_zero(self):
        score, _ = score_opportunity(0.0, -1.0, False, 25, 200)
        assert score == 0


class TestDaysComponent:
    # Use net=-1 → 0 tail pts and 25 legs → 0 leg pts to isolate days.
    def test_short_dated_full_10(self):
        score, _ = score_opportunity(0.0, -1.0, False, 25, 5)
        assert score == 10

    def test_30_days_full_10(self):
        score, _ = score_opportunity(0.0, -1.0, False, 25, 30)
        assert score == 10

    def test_31_to_90_half_5(self):
        score, _ = score_opportunity(0.0, -1.0, False, 25, 60)
        assert score == 5

    def test_above_90_zero(self):
        score, _ = score_opportunity(0.0, -1.0, False, 25, 200)
        assert score == 0


class TestLabels:
    def test_below_40_marginal(self):
        _, label = score_opportunity(0.0, -2.0, False, 5, 200)
        assert label == "Marginal"

    def test_60_to_79_strong(self):
        _, label = score_opportunity(3.0, 1.5, True, 5, 30)
        assert label == "Strong EV+ signal"


class TestReturnShape:
    def test_returns_tuple(self):
        out = score_opportunity(0.0, 0.0, True, 3, 5)
        assert isinstance(out, tuple)
        assert len(out) == 2

    def test_score_clamped_0_to_100(self):
        score, _ = score_opportunity(100.0, 100.0, True, 3, 5)
        assert score == 100

    def test_score_never_negative(self):
        score, _ = score_opportunity(-10.0, -10.0, False, 25, 365)
        assert score >= 0
