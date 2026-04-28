"""Polymarket Gamma + CLOB adapter.

Focuses on `/events` (groups of mutually-exclusive child markets) for
multi-outcome arbitrage detection. The legacy `/markets` flat fetch is
kept for tests/back-compat but not used by the v2 scanner.
"""
import json
from typing import Optional

import httpx

_GAMMA_URL = "https://gamma-api.polymarket.com"
_CLOB_URL = "https://clob.polymarket.com"


def _maybe_json_list(value) -> list:
    """Polymarket Gamma API returns array fields as JSON-encoded strings."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


class PolymarketAdapter:
    name = "polymarket"

    # ------------------------------------------------------------------
    # Events (multi-outcome groups)
    # ------------------------------------------------------------------

    async def fetch_open_events(self, max_events: int = 2000) -> list[dict]:
        """Fetch open events sorted by volume desc.

        Returns raw event dicts. Each contains a `markets` array of child
        markets that share the event's outcome space (mutually exclusive).
        """
        events: list[dict] = []
        page_size = 100  # Gamma /events caps at 100 per call

        async with httpx.AsyncClient(timeout=15) as client:
            for offset in range(0, max_events, page_size):
                params: dict = {
                    "closed": "false",
                    "limit": page_size,
                    "offset": offset,
                    "order": "volume",
                    "ascending": "false",
                }
                resp = await client.get(f"{_GAMMA_URL}/events", params=params)
                resp.raise_for_status()
                data = resp.json()

                page = data if isinstance(data, list) else data.get("data", [])
                if not page:
                    break
                events.extend(page)

                if len(page) < page_size:
                    break

        return events

    def normalize_event(self, raw_event: dict) -> dict:
        """Normalize a Polymarket event + its child markets to a flat shape.

        Returns:
            {
              "id": str,                    # event id
              "title": str,                 # event title
              "slug": str,
              "event_url": str,
              "volume_usd": int,            # event-level cumulative
              "liquidity_usd": int,         # event-level cumulative
              "resolution_date": str,       # ISO date of latest child
              "legs": list[dict]            # each is a normalized child market
            }
        """
        slug = raw_event.get("slug", "")
        event_url = f"https://polymarket.com/event/{slug}" if slug else ""

        raw_markets = raw_event.get("markets", []) or []
        legs = [self._normalize_child_market(m) for m in raw_markets]
        legs = [leg for leg in legs if leg is not None]

        # Event-level resolution date = latest child end_date.
        end_dates = [leg["resolution_date"] for leg in legs if leg.get("resolution_date")]
        resolution_date = max(end_dates) if end_dates else ""

        return {
            "id": str(raw_event.get("id", "")),
            "title": raw_event.get("title", ""),
            "slug": slug,
            "event_url": event_url,
            "volume_usd": int(float(raw_event.get("volume", 0) or 0)),
            "liquidity_usd": int(float(raw_event.get("liquidity", 0) or 0)),
            "resolution_date": resolution_date,
            "legs": legs,
            "raw": raw_event,
        }

    def _normalize_child_market(self, raw: dict) -> Optional[dict]:
        """Normalize one child market within an event.

        Returns None if the market lacks YES/NO binary structure.
        """
        outcomes = _maybe_json_list(raw.get("outcomes"))
        if not (len(outcomes) == 2
                and any(str(o).lower() == "yes" for o in outcomes)
                and any(str(o).lower() == "no" for o in outcomes)):
            return None

        outcome_prices = _maybe_json_list(raw.get("outcomePrices"))
        try:
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
        except (IndexError, ValueError, TypeError):
            return None

        # CLOB token IDs — we need the YES side token for orderbook lookup.
        clob_token_ids = _maybe_json_list(raw.get("clobTokenIds"))
        yes_token_id = str(clob_token_ids[0]) if clob_token_ids else ""
        no_token_id = str(clob_token_ids[1]) if len(clob_token_ids) >= 2 else ""

        slug = raw.get("slug", "")
        condition_id = raw.get("conditionId", "")
        market_url = f"https://polymarket.com/event/{slug}" if slug else ""

        end_date = raw.get("endDate", "")
        resolution_date = end_date[:10] if end_date else ""

        # `groupItemTitle` is Polymarket's name for the leg label
        # (e.g. "Lakers", "Celtics") — falls back to question text.
        outcome_label = raw.get("groupItemTitle") or raw.get("question", "")

        return {
            "id": condition_id,
            "market_id": condition_id,
            "question": raw.get("question", ""),
            "outcome_label": outcome_label,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
            "liquidity_usd": int(float(raw.get("liquidity", 0) or 0)),
            "volume_usd": int(float(raw.get("volume", 0) or 0)),
            "market_url": market_url,
            "resolution_date": resolution_date,
        }

    # ------------------------------------------------------------------
    # Order book (for liquidity depth checks)
    # ------------------------------------------------------------------

    async def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch CLOB orderbook for one outcome token (YES or NO)."""
        if not token_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_CLOB_URL}/book",
                    params={"token_id": token_id},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return None

    def test_leg_fillable(
        self,
        orderbook: Optional[dict],
        usd_to_fill: float,
        side: str,
    ) -> Optional[bool]:
        """Walk the orderbook to check if usd_to_fill can be bought.

        side='YES' walks asks of the YES token (buying YES).
        side='NO'  walks asks of the NO token (orderbook should already
                   be the NO token's book — caller's responsibility).

        Returns True/False. Returns None if orderbook is None (unavailable).
        """
        if orderbook is None:
            return None

        # Polymarket CLOB book shape: {"bids":[{"price":"x","size":"y"}], "asks":[...]}
        # Buying = lifting asks. Cost = price × size.
        asks = orderbook.get("asks", [])
        if not asks:
            return False

        # Sort asks ascending by price (best ask first).
        try:
            sorted_asks = sorted(asks, key=lambda a: float(a.get("price", 1)))
        except (ValueError, TypeError):
            return False

        cumulative_cost = 0.0
        for ask in sorted_asks:
            try:
                price = float(ask.get("price", 0))
                size = float(ask.get("size", 0))
            except (ValueError, TypeError):
                continue
            cumulative_cost += price * size
            if cumulative_cost >= usd_to_fill:
                return True

        return False

    # ------------------------------------------------------------------
    # Legacy single-market interface — kept for back-compat tests.
    # The v2 multi-outcome scanner uses fetch_open_events instead.
    # ------------------------------------------------------------------

    async def fetch_open_markets(self) -> list[dict]:
        """Legacy flat-markets fetch. Used only by older tests."""
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
                if len(page) < page_size:
                    break

        return markets

    def normalize_market(self, raw: dict) -> dict:
        """Legacy single-market normalizer."""
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
