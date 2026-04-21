from abc import ABC, abstractmethod
from typing import Optional


class VenueAdapter(ABC):
    name: str  # class-level constant, e.g. "polymarket"

    @abstractmethod
    async def fetch_open_markets(self) -> list[dict]:
        ...

    @abstractmethod
    def normalize_market(self, raw: dict) -> dict:
        """
        Normalize raw venue market dict to standard shape:
        {
          "id": str,
          "title": str,
          "resolution_date": str,  # ISO date
          "yes_price": float,       # 0.0–1.0
          "no_price": float,        # 0.0–1.0
          "liquidity_usd": int,
          "volume_usd": int,
          "market_url": str,
          "is_binary": bool,
          "raw": dict               # original payload for debugging
        }
        """
        ...

    @abstractmethod
    async def fetch_orderbook(self, market_id: str) -> Optional[dict]:
        ...

    def test_liquidity_depth(
        self,
        orderbook: Optional[dict],
        test_usd: int,
        yes_price: float,
    ) -> dict:
        if orderbook is None:
            return {"fillable": None, "price_impact_pct": None}

        asks = sorted(orderbook.get("asks", []), key=lambda x: float(x["price"]))

        cumulative_usd = 0.0
        for level in asks:
            level_price = float(level["price"])
            level_size = float(level["size"])

            price_move_pct = abs(level_price - yes_price) / yes_price * 100
            if price_move_pct > 0.5:
                # price has slipped beyond tolerance before fill completed
                return {
                    "fillable": False,
                    "price_impact_pct": round(price_move_pct, 4),
                }

            cumulative_usd += level_size * level_price
            if cumulative_usd >= test_usd:
                final_price_impact = abs(level_price - yes_price) / yes_price * 100
                return {
                    "fillable": True,
                    "price_impact_pct": round(final_price_impact, 4),
                }

        # order book exhausted before fill
        return {"fillable": False, "price_impact_pct": None}
