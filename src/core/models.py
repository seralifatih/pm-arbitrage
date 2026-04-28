"""Pydantic models for Polymarket multi-outcome arbitrage scanner.

A multi-outcome event is a group of mutually-exclusive binary YES/NO markets
(e.g. "2028 Democratic Nominee" with one market per candidate). For a fully
specified event the YES prices must sum to 1.0. Deviations are arbitrage:

  - sum_yes < 1.0 - fees → BUY all YES baskets, profit on convergence
  - sum_yes > 1.0 + fees → BUY all NO baskets, profit on convergence
"""
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OutcomeLeg(BaseModel):
    """One leg of a basket trade — buying YES or NO on one child market."""
    model_config = ConfigDict(strict=False)

    market_id: str
    question: str          # e.g. "Will Lakers win the 2026 NBA Finals?"
    outcome_label: str     # human-readable, e.g. "Lakers" / "Celtics"
    side: str              # "YES" or "NO"
    price: float           # 0.0–1.0
    market_url: str
    liquidity_usd: int
    fillable: Optional[bool] = None       # None if orderbook unavailable


class LiquidityCheck(BaseModel):
    model_config = ConfigDict(strict=False)

    tested_usd_per_leg: int
    all_legs_fillable: Optional[bool] = None  # None if any leg's book unavailable
    fillable_leg_count: int
    total_leg_count: int


class Opportunity(BaseModel):
    """A multi-outcome arbitrage opportunity on a single Polymarket event."""
    model_config = ConfigDict(strict=False)

    id: str
    event_title: str
    event_url: str
    resolution_date: str        # ISO date of the latest child resolution
    arb_type: str               # "buy_yes_basket" | "buy_no_basket"
    leg_count: int
    sum_yes_price: float        # raw sum BEFORE fees, for transparency
    deviation_from_one: float   # sum_yes - 1.0 (negative = underpriced; positive = overpriced)
    fees_pct: float             # round-trip fee drag for the basket
    gross_return_pct: float     # before fees
    net_return_pct: float       # after fees, the headline number
    legs: list[OutcomeLeg]
    liquidity: LiquidityCheck
    signal_score: int           # 0–100 composite
    signal_label: str           # "Pure arbitrage" / "Strong EV+ signal" / etc.
    notes: Optional[str] = None

    @classmethod
    def make_id(cls, event_slug: str, arb_type: str) -> str:
        slug = event_slug.lower()
        slug = re.sub(r"[^a-z0-9-]", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return f"{slug}-{arb_type}"[:80]


class ScanSummary(BaseModel):
    model_config = ConfigDict(strict=False)

    scanned_at: str
    total_events_scanned: int
    eligible_events: int            # events with ≥3 active legs
    pure_arb_count: int             # net_return_pct > 0
    ev_positive_count: int          # net_return_pct > -1% (configurable upstream)
    avg_net_return_pct: float
    best_opportunity_id: Optional[str] = None

    @classmethod
    def from_opportunities(
        cls,
        opportunities: list["Opportunity"],
        total_events_scanned: int,
        eligible_events: int,
    ) -> "ScanSummary":
        pure_arb = [o for o in opportunities if o.net_return_pct > 0]
        ev_positive = [o for o in opportunities if o.net_return_pct > -1.0]

        if opportunities:
            avg = round(
                sum(o.net_return_pct for o in opportunities) / len(opportunities), 4
            )
            best = max(opportunities, key=lambda o: o.signal_score)
            best_id = best.id
        else:
            avg = 0.0
            best_id = None

        return cls(
            scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            total_events_scanned=total_events_scanned,
            eligible_events=eligible_events,
            pure_arb_count=len(pure_arb),
            ev_positive_count=len(ev_positive),
            avg_net_return_pct=avg,
            best_opportunity_id=best_id,
        )
