import json
from typing import Optional

import httpx

from .base import VenueAdapter

_GAMMA_URL = "https://gamma-api.polymarket.com"
_CLOB_URL = "https://clob.polymarket.com"


def _maybe_json_list(value) -> list:
    """Polymarket Gamma API returns outcomes/outcomePrices as JSON-encoded strings."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


class PolymarketAdapter(VenueAdapter):
    name = "polymarket"

    async def fetch_open_markets(self) -> list[dict]:
        # Polymarket Gamma `/markets` returns a flat array, no cursor field.
        # Pagination is offset-based. Cap at 5000 to bound runtime;
        # past that the markets are usually low-liquidity long-tail.
        markets: list[dict] = []
        page_size = 500
        max_markets = 5000

        async with httpx.AsyncClient(timeout=10) as client:
            for offset in range(0, max_markets, page_size):
                params: dict = {
                    "closed": "false",
                    "limit": page_size,
                    "offset": offset,
                }
                resp = await client.get(f"{_GAMMA_URL}/markets", params=params)
                resp.raise_for_status()
                data = resp.json()

                page = data if isinstance(data, list) else data.get("markets", data.get("data", []))
                if not page:
                    break
                markets.extend(page)

                # Last page reached
                if len(page) < page_size:
                    break

        return markets

    def normalize_market(self, raw: dict) -> dict:
        outcome_prices = _maybe_json_list(raw.get("outcomePrices"))
        try:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        except (IndexError, ValueError, TypeError):
            yes_price = 0.5
            no_price = 0.5

        end_date = raw.get("endDate", "")
        resolution_date = end_date[:10] if end_date else ""

        outcomes = _maybe_json_list(raw.get("outcomes"))
        is_binary = (
            len(outcomes) == 2
            and any(str(o).lower() == "yes" for o in outcomes)
            and any(str(o).lower() == "no" for o in outcomes)
        )

        slug = raw.get("slug")
        condition_id = raw.get("conditionId", "")
        if slug:
            market_url = f"https://polymarket.com/event/{slug}"
        else:
            market_url = f"https://polymarket.com/event/{condition_id}"

        return {
            "id": condition_id,
            "title": raw.get("question", ""),
            "resolution_date": resolution_date,
            "yes_price": yes_price,
            "no_price": no_price,
            "liquidity_usd": int(float(raw.get("liquidity", 0) or 0)),
            "volume_usd": int(float(raw.get("volume", 0) or 0)),
            "market_url": market_url,
            "is_binary": is_binary,
            "raw": raw,
        }

    async def fetch_orderbook(self, market_id: str) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_CLOB_URL}/book",
                    params={"token_id": market_id},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return None
