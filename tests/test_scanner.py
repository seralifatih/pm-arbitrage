from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import Opportunity, ScanSummary
from src.core.scanner import run_scan


def _future_date(days: int = 10) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _mkt(title, resolution_date=None, yes=0.40, no=0.40, liq=10000, mid="m1"):
    return {
        "id": mid,
        "title": title,
        "resolution_date": resolution_date or _future_date(10),
        "yes_price": yes,
        "no_price": no,
        "liquidity_usd": liq,
        "volume_usd": 50000,
        "market_url": f"https://example.com/{mid}",
        "is_binary": True,
        "raw": {},
    }


_ORDERBOOK_DEEP = {
    "bids": [{"price": "0.39", "size": "5000"}],
    "asks": [
        {"price": "0.40", "size": "10000"},
        {"price": "0.401", "size": "10000"},
    ],
}


def _mock_polymarket(markets, orderbook=_ORDERBOOK_DEEP):
    mock = MagicMock()
    mock.name = "polymarket"
    mock.fetch_open_markets = AsyncMock(return_value=[{"raw_marker": True} for _ in markets])
    mock.normalize_market = MagicMock(side_effect=markets)
    mock.fetch_orderbook = AsyncMock(return_value=orderbook)
    mock.test_liquidity_depth = MagicMock(
        return_value={"fillable": True, "price_impact_pct": 0.2}
    )
    return mock


def _mock_kalshi(markets, orderbook=_ORDERBOOK_DEEP):
    mock = MagicMock()
    mock.name = "kalshi"
    mock.fetch_open_markets = AsyncMock(return_value=[{"raw_marker": True} for _ in markets])
    mock.normalize_market = MagicMock(side_effect=markets)
    mock.fetch_orderbook = AsyncMock(return_value=orderbook)
    mock.test_liquidity_depth = MagicMock(
        return_value={"fillable": True, "price_impact_pct": 0.2}
    )
    return mock


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_sorted_opportunities(self):
        # 3 markets per side, all should match (identical titles + dates)
        polymarket_markets = [
            _mkt("Will the Fed cut rates June FOMC?", _future_date(10), mid="p1"),
            _mkt("Will BTC hit 100k end of year?", _future_date(10), mid="p2", yes=0.30, no=0.30),
            _mkt("Will US enter recession 2025?", _future_date(10), mid="p3", yes=0.45, no=0.45),
        ]
        kalshi_markets = [
            _mkt("Will the Fed cut rates June FOMC?", _future_date(10), mid="k1"),
            _mkt("Will BTC hit 100k end of year?", _future_date(10), mid="k2", yes=0.30, no=0.30),
            _mkt("Will US enter recession 2025?", _future_date(10), mid="k3", yes=0.45, no=0.45),
        ]

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps, summary = await run_scan({"min_signal_score": 0, "min_net_spread_pct": -100})

        assert len(opps) == 3
        scores = [o.signal_score for o in opps]
        assert scores == sorted(scores, reverse=True)
        assert isinstance(summary, ScanSummary)
        assert summary.total_pairs_scanned == 3

    @pytest.mark.asyncio
    async def test_opportunity_has_required_fields(self):
        markets = [_mkt("Will the Fed cut rates June FOMC?", _future_date(10))]
        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(markets)):
            opps, _ = await run_scan({"min_signal_score": 0, "min_net_spread_pct": -100})

        assert len(opps) == 1
        opp = opps[0]
        assert isinstance(opp, Opportunity)
        assert opp.venue_a.name == "polymarket"
        assert opp.venue_b.name == "kalshi"
        assert opp.signal_label in {"Pure arbitrage", "Strong EV+ signal", "EV+ with edge", "Marginal"}


# ---------------------------------------------------------------------------
# Venue failure isolation
# ---------------------------------------------------------------------------

class TestVenueFailures:
    @pytest.mark.asyncio
    async def test_venue_a_timeout_returns_empty_no_crash(self):
        # Polymarket fails entirely; Kalshi has data but no pair to match against → 0 opps
        poly_mock = MagicMock()
        poly_mock.name = "polymarket"
        poly_mock.fetch_open_markets = AsyncMock(side_effect=TimeoutError("polymarket timeout"))

        kalshi_markets = [_mkt("Solo Kalshi market", _future_date(10), mid="k1")]
        with patch("src.core.scanner.PolymarketAdapter", return_value=poly_mock), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps, summary = await run_scan({"min_signal_score": 0})

        assert opps == []
        assert summary.total_pairs_scanned == 0
        assert summary.pure_arb_count == 0

    @pytest.mark.asyncio
    async def test_both_venues_fail_returns_empty_summary(self):
        poly_mock = MagicMock()
        poly_mock.name = "polymarket"
        poly_mock.fetch_open_markets = AsyncMock(side_effect=Exception("boom"))

        kalshi_mock = MagicMock()
        kalshi_mock.name = "kalshi"
        kalshi_mock.fetch_open_markets = AsyncMock(side_effect=Exception("boom"))

        with patch("src.core.scanner.PolymarketAdapter", return_value=poly_mock), \
             patch("src.core.scanner.KalshiAdapter", return_value=kalshi_mock):
            opps, summary = await run_scan({})

        assert opps == []
        assert summary.total_pairs_scanned == 0
        assert summary.avg_net_spread_pct == 0.0


# ---------------------------------------------------------------------------
# Zero matches
# ---------------------------------------------------------------------------

class TestZeroMatches:
    @pytest.mark.asyncio
    async def test_unrelated_titles_return_empty(self):
        polymarket_markets = [_mkt("Will the Fed cut rates?", _future_date(10), mid="p1")]
        kalshi_markets = [_mkt("Will Elon Musk leave Tesla?", _future_date(10), mid="k1")]

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps, summary = await run_scan({"min_signal_score": 0})

        assert opps == []
        assert summary.total_pairs_scanned == 0

    @pytest.mark.asyncio
    async def test_low_liquidity_filtered_out(self):
        polymarket_markets = [_mkt("Same event title", _future_date(10), liq=100, mid="p1")]
        kalshi_markets = [_mkt("Same event title", _future_date(10), liq=100, mid="k1")]

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps, _ = await run_scan({"min_liquidity_usd": 5000, "min_signal_score": 0})

        assert opps == []

    @pytest.mark.asyncio
    async def test_resolution_too_far_filtered_out(self):
        polymarket_markets = [_mkt("Same event title", _future_date(200), mid="p1")]
        kalshi_markets = [_mkt("Same event title", _future_date(200), mid="k1")]

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps, _ = await run_scan({"max_days_to_resolution": 90, "min_signal_score": 0})

        assert opps == []


# ---------------------------------------------------------------------------
# Signal score filter
# ---------------------------------------------------------------------------

class TestSignalScoreFilter:
    @pytest.mark.asyncio
    async def test_min_signal_score_filters(self):
        # tight prices = small spread + far resolution = lower score
        polymarket_markets = [_mkt("Same event title", _future_date(60), yes=0.50, no=0.49, mid="p1")]
        kalshi_markets = [_mkt("Same event title", _future_date(60), yes=0.50, no=0.49, mid="k1")]

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            # Wide-open threshold first to confirm one match exists
            opps_loose, _ = await run_scan({"min_signal_score": 0, "min_net_spread_pct": -100})

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps_strict, _ = await run_scan({"min_signal_score": 99, "min_net_spread_pct": -100})

        assert len(opps_loose) == 1
        assert opps_strict == []


# ---------------------------------------------------------------------------
# Output limit
# ---------------------------------------------------------------------------

class TestOutputLimit:
    @pytest.mark.asyncio
    async def test_output_limit_caps_results(self):
        polymarket_markets = [
            _mkt(f"Same event {i}", _future_date(10), mid=f"p{i}")
            for i in range(5)
        ]
        kalshi_markets = [
            _mkt(f"Same event {i}", _future_date(10), mid=f"k{i}")
            for i in range(5)
        ]

        with patch("src.core.scanner.PolymarketAdapter", return_value=_mock_polymarket(polymarket_markets)), \
             patch("src.core.scanner.KalshiAdapter", return_value=_mock_kalshi(kalshi_markets)):
            opps, _ = await run_scan({
                "min_signal_score": 0,
                "min_net_spread_pct": -100,
                "output_limit": 2,
            })

        assert len(opps) == 2
