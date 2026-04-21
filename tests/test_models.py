import pytest
from pydantic import ValidationError

from src.core.models import LiquidityDepth, Opportunity, ScanSummary, VenuePosition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _venue(name="polymarket", side="YES", price_cents=56):
    return VenuePosition(
        name=name,
        market_url=f"https://{name}.com/market/test",
        side=side,
        price_cents=price_cents,
        liquidity_usd=50000,
    )


def _depth(fillable=True, impact=0.3):
    return LiquidityDepth(tested_usd=500, fillable=fillable, price_impact_pct=impact)


def _opp(
    net_spread_pct=2.0,
    signal_score=75,
    event_title="Will the Fed cut rates?",
    venue_a_name="polymarket",
    venue_b_name="kalshi",
):
    opp_id = Opportunity.make_id(event_title, venue_a_name, venue_b_name)
    return Opportunity(
        id=opp_id,
        event_title=event_title,
        resolution_date="2025-06-18",
        venue_a=_venue(name=venue_a_name, side="YES", price_cents=56),
        venue_b=_venue(name=venue_b_name, side="NO", price_cents=41),
        gross_spread_pct=4.0,
        fees_pct=9.0,
        net_spread_pct=net_spread_pct,
        liquidity_depth=_depth(),
        match_confidence=91,
        signal_score=signal_score,
        signal_label="Strong EV+ signal",
    )


# ---------------------------------------------------------------------------
# make_id
# ---------------------------------------------------------------------------

class TestMakeId:
    def test_basic_slug(self):
        slug = Opportunity.make_id("Will the Fed cut rates?", "polymarket", "kalshi")
        assert slug == "will-the-fed-cut-rates-polymarket-kalshi"

    def test_special_chars_stripped(self):
        slug = Opportunity.make_id("BTC/ETH price > $100k!", "polymarket", "kalshi")
        assert "/" not in slug
        assert ">" not in slug
        assert "$" not in slug
        assert "!" not in slug

    def test_max_80_chars(self):
        long_title = "A " * 60
        slug = Opportunity.make_id(long_title, "polymarket", "kalshi")
        assert len(slug) <= 80

    def test_spaces_become_hyphens(self):
        slug = Opportunity.make_id("hello world event", "a", "b")
        assert " " not in slug
        assert "hello-world-event-a-b" == slug

    def test_consecutive_spaces_single_hyphen(self):
        slug = Opportunity.make_id("hello   world", "a", "b")
        assert "--" not in slug

    def test_lowercase(self):
        slug = Opportunity.make_id("FED RATE CUT JUNE", "polymarket", "kalshi")
        assert slug == slug.lower()

    def test_venue_names_appended(self):
        slug = Opportunity.make_id("some event", "polymarket", "kalshi")
        assert slug.endswith("-polymarket-kalshi")


# ---------------------------------------------------------------------------
# ScanSummary.from_opportunities
# ---------------------------------------------------------------------------

class TestScanSummaryFromOpportunities:
    def test_empty_list(self):
        summary = ScanSummary.from_opportunities([], total_pairs_scanned=100)
        assert summary.pure_arb_count == 0
        assert summary.ev_positive_count == 0
        assert summary.avg_net_spread_pct == 0.0
        assert summary.best_opportunity_id is None
        assert summary.total_pairs_scanned == 100

    def test_pure_arb_count(self):
        opps = [
            _opp(net_spread_pct=2.5),
            _opp(net_spread_pct=1.0),
            _opp(net_spread_pct=-1.0),
        ]
        summary = ScanSummary.from_opportunities(opps, total_pairs_scanned=50)
        assert summary.pure_arb_count == 2

    def test_ev_positive_count(self):
        opps = [
            _opp(net_spread_pct=2.0),
            _opp(net_spread_pct=-2.5),
            _opp(net_spread_pct=-5.0),
        ]
        summary = ScanSummary.from_opportunities(opps)
        # ev_positive = net_spread > -3.0 → first two qualify
        assert summary.ev_positive_count == 2

    def test_avg_net_spread(self):
        opps = [_opp(net_spread_pct=2.0), _opp(net_spread_pct=4.0)]
        summary = ScanSummary.from_opportunities(opps)
        assert summary.avg_net_spread_pct == 3.0

    def test_best_opportunity_id_highest_signal_score(self):
        opps = [
            _opp(signal_score=50, net_spread_pct=1.0),
            _opp(signal_score=90, net_spread_pct=0.5),
            _opp(signal_score=70, net_spread_pct=2.0),
        ]
        summary = ScanSummary.from_opportunities(opps)
        assert summary.best_opportunity_id == opps[1].id

    def test_scanned_at_is_iso_format(self):
        summary = ScanSummary.from_opportunities([])
        assert "T" in summary.scanned_at
        assert summary.scanned_at.endswith("Z")


# ---------------------------------------------------------------------------
# Required field validation
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_liquidity_depth_missing_tested_usd(self):
        with pytest.raises(ValidationError):
            LiquidityDepth(fillable=True)

    def test_venue_position_missing_name(self):
        with pytest.raises(ValidationError):
            VenuePosition(
                market_url="https://example.com",
                side="YES",
                price_cents=55,
                liquidity_usd=1000,
            )

    def test_opportunity_missing_event_title(self):
        with pytest.raises(ValidationError):
            Opportunity(
                id="test-id",
                resolution_date="2025-06-18",
                venue_a=_venue(),
                venue_b=_venue("kalshi"),
                gross_spread_pct=2.0,
                fees_pct=9.0,
                net_spread_pct=-1.0,
                liquidity_depth=_depth(),
                match_confidence=80,
                signal_score=60,
                signal_label="EV+ with edge",
            )

    def test_opportunity_missing_venue_a(self):
        with pytest.raises(ValidationError):
            Opportunity(
                id="test-id",
                event_title="Some event",
                resolution_date="2025-06-18",
                venue_b=_venue("kalshi"),
                gross_spread_pct=2.0,
                fees_pct=9.0,
                net_spread_pct=-1.0,
                liquidity_depth=_depth(),
                match_confidence=80,
                signal_score=60,
                signal_label="EV+ with edge",
            )

    def test_scan_summary_missing_scanned_at(self):
        with pytest.raises(ValidationError):
            ScanSummary(
                total_pairs_scanned=10,
                pure_arb_count=1,
                ev_positive_count=3,
                avg_net_spread_pct=1.5,
            )

    def test_optional_fields_default_none(self):
        depth = LiquidityDepth(tested_usd=500)
        assert depth.fillable is None
        assert depth.price_impact_pct is None

        opp = _opp()
        assert opp.notes is None

        summary = ScanSummary.from_opportunities([])
        assert summary.best_opportunity_id is None
