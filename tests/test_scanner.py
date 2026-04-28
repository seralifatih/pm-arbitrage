"""End-to-end scanner tests with a fully-mocked PolymarketAdapter.

We feed `normalize_event` output shape directly through `_filter_active_legs`
+ `_compute_arb` + `run_scan` to validate the multi-outcome arb math and
end-to-end orchestration without touching real APIs.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.core.scanner import _compute_arb, _filter_active_legs, run_scan


def _leg(label: str, yes: float, liquidity: int = 5000) -> dict:
    return {
        "id": f"cond-{label}",
        "market_id": f"cond-{label}",
        "question": f"Will {label} win?",
        "outcome_label": label,
        "yes_price": yes,
        "no_price": round(1.0 - yes, 4),
        "yes_token_id": f"yes-token-{label}",
        "no_token_id": f"no-token-{label}",
        "liquidity_usd": liquidity,
        "volume_usd": 50000,
        "market_url": f"https://polymarket.com/event/{label}",
        "resolution_date": (date.today() + timedelta(days=10)).isoformat(),
    }


def _event(legs: list[dict], event_liq: int = 50000) -> dict:
    return {
        "id": "evt-1",
        "title": "Test Multi-Outcome Event",
        "slug": "test-event",
        "event_url": "https://polymarket.com/event/test-event",
        "volume_usd": 1_000_000,
        "liquidity_usd": event_liq,
        "resolution_date": (date.today() + timedelta(days=10)).isoformat(),
        "legs": legs,
        "raw": {},
    }


# ---------------------------------------------------------------------------
# Active-leg filter
# ---------------------------------------------------------------------------

class TestActiveLegFilter:
    def test_drops_dead_placeholders_at_zero_price(self):
        legs = [
            _leg("A", 0.4),
            _leg("B", 0.0),  # placeholder
            _leg("C", 0.5),
        ]
        active = _filter_active_legs(legs, min_liquidity_per_leg=100)
        assert len(active) == 2
        assert {l["outcome_label"] for l in active} == {"A", "C"}

    def test_drops_legs_below_min_liquidity(self):
        legs = [
            _leg("A", 0.5, liquidity=10000),
            _leg("B", 0.4, liquidity=50),  # below 200
        ]
        active = _filter_active_legs(legs, min_liquidity_per_leg=200)
        assert [l["outcome_label"] for l in active] == ["A"]


# ---------------------------------------------------------------------------
# Arb math
# ---------------------------------------------------------------------------

class TestComputeArb:
    def test_buy_yes_basket_when_sum_below_one(self):
        # Σ YES = 0.85; buying basket costs $0.85 to guarantee $1 payout
        legs = [_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.25)]
        arb = _compute_arb(_event(legs), legs, {})
        assert arb["arb_type"] == "buy_yes_basket"
        assert arb["sum_yes_price"] == 0.85
        # Gross = (1 - 0.85) / 0.85 = 17.65%; net = 17.65 - 4 = 13.65
        assert arb["gross_return_pct"] == pytest.approx(17.6471, rel=1e-3)
        assert arb["net_return_pct"] == pytest.approx(13.6471, rel=1e-3)

    def test_buy_no_basket_when_sum_above_one(self):
        # Σ YES = 1.15; sell side via NO basket
        legs = [_leg("A", 0.45), _leg("B", 0.40), _leg("C", 0.30)]
        arb = _compute_arb(_event(legs), legs, {})
        assert arb["arb_type"] == "buy_no_basket"
        # NO cost = 3 - 1.15 = 1.85, payout N-1 = 2 → gross = (2 - 1.85)/1.85
        assert arb["gross_return_pct"] == pytest.approx(8.1081, rel=1e-3)

    def test_sum_exactly_one_yields_zero_return(self):
        legs = [_leg("A", 0.5), _leg("B", 0.5)]
        arb = _compute_arb(_event(legs), legs, {})
        assert arb["gross_return_pct"] == 0.0

    def test_deviation_field_signed(self):
        legs = [_leg("A", 0.3), _leg("B", 0.3)]
        arb = _compute_arb(_event(legs), legs, {})
        # 0.6 - 1.0 = -0.4
        assert arb["deviation_from_one"] == pytest.approx(-0.4)


# ---------------------------------------------------------------------------
# End-to-end run_scan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunScan:
    async def test_happy_path_returns_opportunity(self):
        legs = [_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.25)]
        ev = _event(legs)
        # Adapter returns 1 raw event; normalize_event returns our pre-normalized one.
        adapter_inst = AsyncMock()
        adapter_inst.fetch_open_events.return_value = [{"id": "raw"}]
        adapter_inst.normalize_event = lambda raw: ev
        # All orderbooks return a fillable book
        adapter_inst.fetch_orderbook.return_value = {
            "bids": [],
            "asks": [{"price": "0.5", "size": "10000"}],
        }
        adapter_inst.test_leg_fillable = lambda book, usd, side: True

        with patch("src.core.scanner.PolymarketAdapter", return_value=adapter_inst):
            opps, summary = await run_scan({"min_signal_score": 0})

        assert len(opps) == 1
        opp = opps[0]
        assert opp.event_title == "Test Multi-Outcome Event"
        assert opp.arb_type == "buy_yes_basket"
        assert opp.leg_count == 3
        assert summary.eligible_events == 1
        assert summary.pure_arb_count == 1

    async def test_no_eligible_events_returns_empty(self):
        # Event with only 2 legs → below min_legs=3
        legs = [_leg("A", 0.4), _leg("B", 0.4)]
        ev = _event(legs)
        adapter_inst = AsyncMock()
        adapter_inst.fetch_open_events.return_value = [{"id": "raw"}]
        adapter_inst.normalize_event = lambda raw: ev

        with patch("src.core.scanner.PolymarketAdapter", return_value=adapter_inst):
            opps, summary = await run_scan({})

        assert opps == []
        assert summary.eligible_events == 0
        assert summary.pure_arb_count == 0

    async def test_min_signal_score_filters(self):
        legs = [_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.25)]
        ev = _event(legs)
        adapter_inst = AsyncMock()
        adapter_inst.fetch_open_events.return_value = [{"id": "raw"}]
        adapter_inst.normalize_event = lambda raw: ev
        adapter_inst.fetch_orderbook.return_value = None  # fillable=None
        adapter_inst.test_leg_fillable = lambda book, usd, side: None

        # Set very high threshold — should exclude
        with patch("src.core.scanner.PolymarketAdapter", return_value=adapter_inst):
            opps, _ = await run_scan({"min_signal_score": 99})

        assert opps == []

    async def test_output_limit_caps_results(self):
        legs = [_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.25)]
        events = [_event(legs) for _ in range(5)]
        # Make each unique by slug so make_id differs
        for i, e in enumerate(events):
            e["id"] = f"evt-{i}"
            e["slug"] = f"test-event-{i}"

        adapter_inst = AsyncMock()
        adapter_inst.fetch_open_events.return_value = [{"id": f"r{i}"} for i in range(5)]
        # Return different normalized events in order
        normalized_iter = iter(events)
        adapter_inst.normalize_event = lambda raw: next(normalized_iter)
        adapter_inst.fetch_orderbook.return_value = None
        adapter_inst.test_leg_fillable = lambda book, usd, side: None

        with patch("src.core.scanner.PolymarketAdapter", return_value=adapter_inst):
            opps, _ = await run_scan({"min_signal_score": 0, "output_limit": 3})

        assert len(opps) == 3
