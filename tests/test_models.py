import pytest
from pydantic import ValidationError

from src.core.models import LiquidityCheck, Opportunity, OutcomeLeg, ScanSummary


def _leg(label="Lakers", side="YES", price=0.4, fillable=True) -> OutcomeLeg:
    return OutcomeLeg(
        market_id=f"market-{label}",
        question=f"Will {label} win?",
        outcome_label=label,
        side=side,
        price=price,
        market_url="https://polymarket.com/event/test",
        liquidity_usd=10000,
        fillable=fillable,
    )


def _liq(all_fillable=True, fillable_count=3, total=3) -> LiquidityCheck:
    return LiquidityCheck(
        tested_usd_per_leg=100,
        all_legs_fillable=all_fillable,
        fillable_leg_count=fillable_count,
        total_leg_count=total,
    )


def _opp(net=2.0, score=85, label="Pure arbitrage", id_suffix="") -> Opportunity:
    return Opportunity(
        id=f"test-event-buy_yes_basket{id_suffix}",
        event_title="Test Event",
        event_url="https://polymarket.com/event/test",
        resolution_date="2026-12-31",
        arb_type="buy_yes_basket",
        leg_count=3,
        sum_yes_price=0.92,
        deviation_from_one=-0.08,
        fees_pct=4.0,
        gross_return_pct=net + 4.0,
        net_return_pct=net,
        legs=[_leg("A"), _leg("B"), _leg("C")],
        liquidity=_liq(),
        signal_score=score,
        signal_label=label,
    )


class TestMakeId:
    def test_slug_format(self):
        out = Opportunity.make_id("2028 Democratic Nominee", "buy_yes_basket")
        assert out == "2028-democratic-nominee-buy_yes_basket"

    def test_strips_punctuation(self):
        out = Opportunity.make_id("Who wins NBA 2026?!", "buy_no_basket")
        assert "?" not in out
        assert "!" not in out
        assert out.endswith("-buy_no_basket")

    def test_caps_at_80_chars(self):
        long = "x" * 200
        out = Opportunity.make_id(long, "buy_yes_basket")
        assert len(out) <= 80


class TestScanSummary:
    def test_pure_arb_count(self):
        opps = [_opp(net=2.0, id_suffix="-1"), _opp(net=-0.5, id_suffix="-2"), _opp(net=1.5, id_suffix="-3")]
        s = ScanSummary.from_opportunities(opps, total_events_scanned=100, eligible_events=20)
        assert s.pure_arb_count == 2

    def test_ev_positive_count(self):
        # Default EV+ floor in factory is net > -1.0
        opps = [_opp(net=0.5, id_suffix="-1"), _opp(net=-0.5, id_suffix="-2"), _opp(net=-2.0, id_suffix="-3")]
        s = ScanSummary.from_opportunities(opps, total_events_scanned=10, eligible_events=5)
        assert s.ev_positive_count == 2

    def test_avg_net_return(self):
        opps = [_opp(net=2.0, id_suffix="-1"), _opp(net=4.0, id_suffix="-2")]
        s = ScanSummary.from_opportunities(opps, total_events_scanned=10, eligible_events=2)
        assert s.avg_net_return_pct == 3.0

    def test_best_opportunity_id_is_highest_scoring(self):
        a = _opp(score=70, id_suffix="-a")
        b = _opp(score=92, id_suffix="-b")
        c = _opp(score=80, id_suffix="-c")
        s = ScanSummary.from_opportunities([a, b, c], total_events_scanned=3, eligible_events=3)
        assert s.best_opportunity_id == b.id

    def test_empty_list_zeros(self):
        s = ScanSummary.from_opportunities([], total_events_scanned=50, eligible_events=0)
        assert s.pure_arb_count == 0
        assert s.ev_positive_count == 0
        assert s.avg_net_return_pct == 0.0
        assert s.best_opportunity_id is None
        assert s.total_events_scanned == 50
        assert s.eligible_events == 0


class TestValidation:
    def test_outcome_leg_missing_market_id(self):
        with pytest.raises(ValidationError):
            OutcomeLeg(question="x", outcome_label="x", side="YES",
                       price=0.5, market_url="x", liquidity_usd=1)

    def test_opportunity_missing_event_title(self):
        with pytest.raises(ValidationError):
            Opportunity(
                id="x", event_url="x", resolution_date="2026-01-01",
                arb_type="buy_yes_basket", leg_count=3, sum_yes_price=0.9,
                deviation_from_one=-0.1, fees_pct=4.0,
                gross_return_pct=11.1, net_return_pct=7.1, legs=[],
                liquidity=_liq(), signal_score=70, signal_label="x",
            )

    def test_optional_fields_default_none(self):
        leg = OutcomeLeg(
            market_id="x", question="x", outcome_label="x", side="YES",
            price=0.5, market_url="x", liquidity_usd=1,
        )
        assert leg.fillable is None
