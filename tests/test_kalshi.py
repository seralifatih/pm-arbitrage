import json
import pathlib
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from src.venues.kalshi import KalshiAdapter

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def adapter():
    return KalshiAdapter()


@pytest.fixture
def markets_page():
    return load_fixture("kalshi_markets.json")


@pytest.fixture
def raw_markets(markets_page):
    return markets_page["markets"]


@pytest.fixture
def orderbook():
    return load_fixture("kalshi_orderbook.json")


def _mock_client(responses: list):
    """Build a mock AsyncClient that returns responses in order."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_resp(data: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=data)
    return resp


# ---------------------------------------------------------------------------
# normalize_market
# ---------------------------------------------------------------------------

class TestNormalizeMarket:
    def test_converts_cents_to_float(self, adapter, raw_markets):
        norm = adapter.normalize_market(raw_markets[0])
        assert norm["yes_price"] == pytest.approx(0.46)
        assert norm["no_price"] == pytest.approx(0.56)

    def test_resolution_date_strips_time(self, adapter, raw_markets):
        norm = adapter.normalize_market(raw_markets[0])
        assert norm["resolution_date"] == "2025-06-18"
        assert "T" not in norm["resolution_date"]

    def test_is_binary_always_true(self, adapter, raw_markets):
        for market in raw_markets:
            norm = adapter.normalize_market(market)
            assert norm["is_binary"] is True

    def test_market_url_uses_ticker(self, adapter, raw_markets):
        norm = adapter.normalize_market(raw_markets[0])
        assert norm["market_url"] == "https://kalshi.com/markets/FED-25JUN-T5.25"

    def test_id_is_ticker(self, adapter, raw_markets):
        norm = adapter.normalize_market(raw_markets[0])
        assert norm["id"] == "FED-25JUN-T5.25"

    def test_liquidity_and_volume_are_int(self, adapter, raw_markets):
        norm = adapter.normalize_market(raw_markets[0])
        assert isinstance(norm["liquidity_usd"], int)
        assert isinstance(norm["volume_usd"], int)
        assert norm["liquidity_usd"] == 32000
        assert norm["volume_usd"] == 85000

    def test_raw_preserved(self, adapter, raw_markets):
        raw = raw_markets[1]
        norm = adapter.normalize_market(raw)
        assert norm["raw"] is raw

    def test_required_keys_present(self, adapter, raw_markets):
        norm = adapter.normalize_market(raw_markets[0])
        required = {"id", "title", "resolution_date", "yes_price", "no_price",
                    "liquidity_usd", "volume_usd", "market_url", "is_binary", "raw"}
        assert required.issubset(norm.keys())

    def test_missing_yes_ask_defaults_to_50_cents(self, adapter):
        raw = {"ticker": "TEST-X", "close_time": "2025-01-01T00:00:00Z"}
        norm = adapter.normalize_market(raw)
        assert norm["yes_price"] == pytest.approx(0.5)
        assert norm["no_price"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# fetch_orderbook
# ---------------------------------------------------------------------------

class TestFetchOrderbook:
    @pytest.mark.asyncio
    async def test_normalizes_asks_to_float_prices(self, adapter, orderbook):
        mock_client = _mock_client([_make_resp(orderbook)])
        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("FED-25JUN-T5.25")

        assert result is not None
        assert "asks" in result
        for ask in result["asks"]:
            price = float(ask["price"])
            assert 0.0 <= price <= 1.0, f"Price not in 0–1 range: {price}"

    @pytest.mark.asyncio
    async def test_normalizes_bids_to_float_prices(self, adapter, orderbook):
        mock_client = _mock_client([_make_resp(orderbook)])
        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("FED-25JUN-T5.25")

        for bid in result["bids"]:
            price = float(bid["price"])
            assert 0.0 <= price <= 1.0

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self, adapter):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )
        mock_client = _mock_client([mock_resp])
        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("NONEXISTENT-TICKER")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self, adapter):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("ANY-TICKER")

        assert result is None

    @pytest.mark.asyncio
    async def test_correct_number_of_levels(self, adapter, orderbook):
        mock_client = _mock_client([_make_resp(orderbook)])
        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("FED-25JUN-T5.25")

        assert len(result["asks"]) == 3
        assert len(result["bids"]) == 3


# ---------------------------------------------------------------------------
# fetch_open_markets — pagination
# ---------------------------------------------------------------------------

class TestFetchOpenMarkets:
    @pytest.mark.asyncio
    async def test_single_page(self, adapter, markets_page):
        mock_client = _mock_client([_make_resp(markets_page)])
        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_open_markets()

        assert isinstance(result, list)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_pagination_two_pages(self, adapter, raw_markets):
        page1 = {"markets": raw_markets[:3], "next_cursor": "cursor_abc"}
        page2 = {"markets": raw_markets[3:], "next_cursor": None}

        # Need two separate client mocks since each page opens a new AsyncClient context
        call_count = 0
        pages = [_make_resp(page1), _make_resp(page2)]

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=pages)

        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_open_markets()

        assert len(result) == 5
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_second_page_request_includes_cursor(self, adapter, raw_markets):
        page1 = {"markets": raw_markets[:2], "next_cursor": "cursor_xyz"}
        page2 = {"markets": raw_markets[2:], "next_cursor": None}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=[_make_resp(page1), _make_resp(page2)])

        with patch("src.venues.kalshi.httpx.AsyncClient", return_value=mock_client):
            await adapter.fetch_open_markets()

        second_call_kwargs = mock_client.get.call_args_list[1]
        params = second_call_kwargs[1].get("params", second_call_kwargs[0][1] if len(second_call_kwargs[0]) > 1 else {})
        assert params.get("cursor") == "cursor_xyz"
