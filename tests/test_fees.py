import pytest

from src.utils.fees import VENUE_FEES, calculate_spread


class TestCalculateSpread:
    def test_pure_arb_net_positive(self):
        # YES=0.40 + NO=0.40 = 0.80 total → gross = 25%, fees poly+kalshi = 9% → net = 16%
        result = calculate_spread(0.40, 0.40, "polymarket", "kalshi")
        assert result["gross_spread_pct"] > result["fees_pct"]
        assert result["net_spread_pct"] > 0

    def test_marginal_net_negative(self):
        # YES=0.55 + NO=0.44 = 0.99 → gross ≈ 1.01%, fees = 9% → net < 0
        result = calculate_spread(0.55, 0.44, "polymarket", "kalshi")
        assert result["gross_spread_pct"] < result["fees_pct"]
        assert result["net_spread_pct"] < 0

    def test_zero_gross_spread(self):
        # YES + NO = 1.0 → gross = 0.0
        result = calculate_spread(0.56, 0.44, "polymarket", "kalshi")
        assert result["gross_spread_pct"] == 0.0
        assert result["fees_pct"] == 9.0
        assert result["net_spread_pct"] == -9.0

    def test_unknown_venue_raises_key_error(self):
        with pytest.raises(KeyError):
            calculate_spread(0.5, 0.4, "polymarket", "unknown_venue")

    def test_unknown_venue_a_raises_key_error(self):
        with pytest.raises(KeyError):
            calculate_spread(0.5, 0.4, "fake_venue", "kalshi")

    def test_fees_pct_polymarket_kalshi(self):
        result = calculate_spread(0.5, 0.4, "polymarket", "kalshi")
        assert result["fees_pct"] == pytest.approx(9.0)

    def test_fees_pct_manifold_zero(self):
        result = calculate_spread(0.5, 0.4, "manifold", "manifold")
        assert result["fees_pct"] == 0.0
        assert result["net_spread_pct"] == result["gross_spread_pct"]

    def test_return_keys_present(self):
        result = calculate_spread(0.5, 0.45, "polymarket", "kalshi")
        assert set(result.keys()) == {"gross_spread_pct", "fees_pct", "net_spread_pct"}

    def test_venue_fees_dict_has_all_venues(self):
        for venue in ("polymarket", "kalshi", "manifold", "myriad"):
            assert venue in VENUE_FEES
