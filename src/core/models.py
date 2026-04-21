import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict


class LiquidityDepth(BaseModel):
    model_config = ConfigDict(strict=False)

    tested_usd: int
    fillable: Optional[bool] = None
    price_impact_pct: Optional[float] = None


class VenuePosition(BaseModel):
    model_config = ConfigDict(strict=False)

    name: str
    market_url: str
    side: str
    price_cents: int
    liquidity_usd: int


class Opportunity(BaseModel):
    model_config = ConfigDict(strict=False)

    id: str
    event_title: str
    resolution_date: str
    venue_a: VenuePosition
    venue_b: VenuePosition
    gross_spread_pct: float
    fees_pct: float
    net_spread_pct: float
    liquidity_depth: LiquidityDepth
    match_confidence: int
    signal_score: int
    signal_label: str
    notes: Optional[str] = None

    @classmethod
    def make_id(cls, event_title: str, venue_a_name: str, venue_b_name: str) -> str:
        slug = event_title.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug.strip())
        slug = re.sub(r"-+", "-", slug)
        prefix = f"{slug}-{venue_a_name}-{venue_b_name}"
        return prefix[:80]


class ScanSummary(BaseModel):
    model_config = ConfigDict(strict=False)

    scanned_at: str
    total_pairs_scanned: int
    pure_arb_count: int
    ev_positive_count: int
    avg_net_spread_pct: float
    best_opportunity_id: Optional[str] = None

    @classmethod
    def from_opportunities(
        cls,
        opportunities: list["Opportunity"],
        total_pairs_scanned: int = 0,
    ) -> "ScanSummary":
        pure_arb = [o for o in opportunities if o.net_spread_pct > 0]
        ev_positive = [o for o in opportunities if o.net_spread_pct > -3.0]

        if opportunities:
            avg_net = round(
                sum(o.net_spread_pct for o in opportunities) / len(opportunities), 4
            )
            best = max(opportunities, key=lambda o: o.signal_score)
            best_id = best.id
        else:
            avg_net = 0.0
            best_id = None

        return cls(
            scanned_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            total_pairs_scanned=total_pairs_scanned,
            pure_arb_count=len(pure_arb),
            ev_positive_count=len(ev_positive),
            avg_net_spread_pct=avg_net,
            best_opportunity_id=best_id,
        )
