import json
import pathlib
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from src.venues.polymarket import PolymarketAdapter

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def adapter():
    return PolymarketAdapter()


@pytest.fixture
def markets():
    return load_fixture("polymarket_markets.json")


@pytest.fixture
def orderbook():
    return load_fixture("polymarket_orderbook.json")


# ---------------------------------------------------------------------------
# normalize_market
# ---------------------------------------------------------------------------

class TestNormalizeMarket:
    def test_parses_prices_from_strings(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        assert norm["yes_price"] == 0.56
        assert norm["no_price"] == 0.44

    def test_is_binary_true_for_yes_no_market(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        assert norm["is_binary"] is True

    def test_is_binary_false_for_multi_outcome(self, adapter, markets):
        # markets[2] has 4 outcomes (UK election)
        norm = adapter.normalize_market(markets[2])
        assert norm["is_binary"] is False

    def test_is_binary_false_for_three_outcomes(self, adapter, markets):
        # markets[4] has 3 outcomes (NBA)
        norm = adapter.normalize_market(markets[4])
        assert norm["is_binary"] is False

    def test_resolution_date_strips_time(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        assert norm["resolution_date"] == "2025-06-18"
        assert "T" not in norm["resolution_date"]

    def test_market_url_uses_slug(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        assert norm["market_url"] == "https://polymarket.com/event/fed-rate-cut-june-2025"

    def test_market_url_falls_back_to_condition_id(self, adapter, markets):
        # markets[2] has null slug
        norm = adapter.normalize_market(markets[2])
        assert norm["market_url"] == "https://polymarket.com/event/0xabc003"

    def test_liquidity_and_volume_are_int(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        assert isinstance(norm["liquidity_usd"], int)
        assert isinstance(norm["volume_usd"], int)
        assert norm["liquidity_usd"] == 87300
        assert norm["volume_usd"] == 1240500

    def test_raw_field_preserved(self, adapter, markets):
        raw = markets[0]
        norm = adapter.normalize_market(raw)
        assert norm["raw"] is raw

    def test_id_is_condition_id(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        assert norm["id"] == "0xabc001"

    def test_missing_prices_defaults_to_half(self, adapter):
        raw = {"conditionId": "0xtest", "outcomes": ["Yes", "No"]}
        norm = adapter.normalize_market(raw)
        assert norm["yes_price"] == 0.5
        assert norm["no_price"] == 0.5

    def test_required_keys_present(self, adapter, markets):
        norm = adapter.normalize_market(markets[0])
        required = {"id", "title", "resolution_date", "yes_price", "no_price",
                    "liquidity_usd", "volume_usd", "market_url", "is_binary", "raw"}
        assert required.issubset(norm.keys())


# ---------------------------------------------------------------------------
# fetch_orderbook
# ---------------------------------------------------------------------------

class TestFetchOrderbook:
    @pytest.mark.asyncio
    async def test_returns_orderbook_on_success(self, adapter, orderbook):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=orderbook)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.venues.polymarket.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("token_yes_001")

        assert result is not None
        assert "asks" in result
        assert "bids" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self, adapter):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.venues.polymarket.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("bad_token")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self, adapter):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.venues.polymarket.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_orderbook("any_token")

        assert result is None


# ---------------------------------------------------------------------------
# fetch_open_markets
# ---------------------------------------------------------------------------

class TestFetchOpenMarkets:
    @pytest.mark.asyncio
    async def test_returns_list_response(self, adapter, markets):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value=markets)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.venues.polymarket.httpx.AsyncClient", return_value=mock_client):
            result = await adapter.fetch_open_markets()

        assert isinstance(result, list)
        assert len(result) == 5
