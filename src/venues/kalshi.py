import time
from typing import Optional

import httpx

from .base import VenueAdapter

_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_DEFAULT_MAX_DAYS = 90


class KalshiAdapter(VenueAdapter):
    name = "kalshi"

    def __init__(self, max_days_to_resolution: int = _DEFAULT_MAX_DAYS):
        self._max_days = max_days_to_resolution

    async def fetch_open_markets(self) -> list[dict]:
        markets = []
        cursor = None

        # Server-side date filter — without this, the markets endpoint returns
        # 200 inactive long-tail markets with zero liquidity (Kalshi quirk).
        max_close_ts = int(time.time()) + self._max_days * 86400

        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                params: dict = {
                    "status": "open",
                    "limit": 200,
                    "max_close_ts": max_close_ts,
                }
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(f"{_BASE_URL}/markets", params=params)
                resp.raise_for_status()
                data = resp.json()

                markets.extend(data.get("markets", []))
                cursor = data.get("next_cursor")
                if not cursor:
                    break

        return markets

    def normalize_market(self, raw: dict) -> dict:
        # Kalshi v2 (as of 2026-04): prices in *_dollars as 0–1 strings; legacy
        # yes_ask / no_ask (cents 0–100 ints) still supported as fallback.
        def _price(dollars_key: str, cents_key: str) -> float:
            dollars = raw.get(dollars_key)
            if dollars is not None and dollars != "":
                try:
                    return float(dollars)
                except (ValueError, TypeError):
                    pass
            cents = raw.get(cents_key)
            if cents is not None:
                try:
                    return float(cents) / 100
                except (ValueError, TypeError):
                    pass
            return 0.5

        yes_price = _price("yes_ask_dollars", "yes_ask")
        no_price = _price("no_ask_dollars", "no_ask")

        close_time = raw.get("close_time", "")
        resolution_date = close_time[:10] if close_time else ""

        ticker = raw.get("ticker", "")

        # Kalshi v2 quirk: liquidity_dollars is frequently '0.0000' even on active
        # markets. Fall back to open_interest_fp (positions outstanding) and then
        # volume_fp as proxies so we don't filter out every tradeable market.
        def _f(*keys) -> float:
            for k in keys:
                v = raw.get(k)
                if v in (None, ""):
                    continue
                try:
                    fv = float(v)
                    if fv > 0:
                        return fv
                except (ValueError, TypeError):
                    continue
            return 0.0

        liquidity_usd = int(_f("liquidity_dollars", "open_interest_fp", "volume_fp", "liquidity"))
        volume_usd = int(_f("volume_fp", "volume_24h_fp", "volume"))

        market_type = raw.get("market_type", "binary")
        is_binary = market_type == "binary"

        return {
            "id": ticker,
            "title": raw.get("title", ""),
            "resolution_date": resolution_date,
            "yes_price": yes_price,
            "no_price": no_price,
            "liquidity_usd": liquidity_usd,
            "volume_usd": volume_usd,
            "market_url": f"https://kalshi.com/markets/{ticker}",
            "is_binary": is_binary,
            "raw": raw,
        }

    async def fetch_orderbook(self, market_id: str) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/markets/{market_id}/orderbook",
                    params={"depth": 10},
                )
                resp.raise_for_status()
                data = resp.json()

            # Kalshi orderbook prices are in cents (0–100); normalize to 0.0–1.0
            # Kalshi shape: {"orderbook": {"yes": [[price_cents, size], ...], "no": [...]}}
            raw_book = data.get("orderbook", data)
            yes_levels = raw_book.get("yes", [])
            no_levels = raw_book.get("no", [])

            asks = [
                {"price": str(round(p / 100, 4)), "size": str(float(s))}
                for p, s in yes_levels
            ]
            bids = [
                {"price": str(round((100 - p) / 100, 4)), "size": str(float(s))}
                for p, s in no_levels
            ]

            return {"bids": bids, "asks": asks}
        except Exception:
            return None
