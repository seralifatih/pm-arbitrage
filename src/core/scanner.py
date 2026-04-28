"""Multi-outcome arbitrage scanner.

Detects mispriced mutually-exclusive Polymarket events.

Math:
  For an event with N mutually-exclusive child markets, exactly one resolves
  YES. So under perfect pricing:  Σ P(outcome_i = YES) = 1.0

  Buy-YES-basket arb: when Σ YES < 1.0
    Cost to buy 1 share of every YES outcome = Σ YES * $1 (per $-share)
    Guaranteed payout = $1 (one of them resolves YES)
    Gross return = (1.0 - Σ YES) / Σ YES

  Buy-NO-basket arb: when Σ YES > 1.0
    Cost to buy 1 share of NO on every outcome = N - Σ YES (since NO_i = 1 - YES_i)
    At resolution, exactly one NO resolves NO ($0); the other (N-1) resolve YES ($1 each)
    Guaranteed payout = N - 1
    Gross return = ((N - 1) - (N - Σ YES)) / (N - Σ YES)
                 = (Σ YES - 1.0) / (N - Σ YES)

Fees: each leg incurs the platform fee (Polymarket ~2% per fill).
Total round-trip fee drag = 2 * fee_rate (open + close, applied to leg cost).
For estimation we use a flat fees_pct = 2 * FEE_POLYMARKET * 100 = 4%.
"""
import asyncio
from datetime import date, datetime, timezone
from typing import Optional

from ..utils.fees import FEE_POLYMARKET
from ..utils.logger import logger
from ..venues.polymarket import PolymarketAdapter
from .models import LiquidityCheck, Opportunity, OutcomeLeg, ScanSummary
from .scorer import score_opportunity

# Round-trip fee for entering and exiting a position. Conservative: assumes
# both fills are takers (worst case). Maker rebates would lower this.
ROUND_TRIP_FEE_PCT = 2 * FEE_POLYMARKET * 100  # 4%

# Minimum YES price to count a leg as "active" (not a dead placeholder).
# Many Polymarket events have placeholder markets ("Person X") at $0 — they
# inflate the leg count but contribute zero to the YES sum, breaking the
# Σ = 1.0 invariant. Filtering them is mandatory.
MIN_LEG_YES_PRICE = 0.005  # 0.5¢


def _days_to_resolution(resolution_date: str) -> int:
    try:
        d = date.fromisoformat(resolution_date[:10])
        return max(0, (d - date.today()).days)
    except (ValueError, TypeError):
        return 99999


def _filter_active_legs(legs: list[dict], min_liquidity_per_leg: int) -> list[dict]:
    """Keep only legs that look real: priced above floor + meet min liquidity."""
    return [
        leg for leg in legs
        if leg["yes_price"] >= MIN_LEG_YES_PRICE
        and leg["liquidity_usd"] >= min_liquidity_per_leg
    ]


def _compute_arb(
    event: dict,
    active_legs: list[dict],
    config: dict,
) -> Optional[dict]:
    """Compute the best-direction arb on this event's active legs.

    Returns a dict with all economics, or None if no edge exists.
    """
    sum_yes = sum(leg["yes_price"] for leg in active_legs)
    n = len(active_legs)
    deviation = round(sum_yes - 1.0, 4)

    # We use ROUND_TRIP_FEE_PCT as the fee drag to be conservative.
    fees_pct = ROUND_TRIP_FEE_PCT

    if sum_yes < 1.0:
        # BUY-YES-BASKET arb
        gross_return_pct = round((1.0 - sum_yes) / sum_yes * 100, 4)
        net_return_pct = round(gross_return_pct - fees_pct, 4)
        arb_type = "buy_yes_basket"
    else:
        # BUY-NO-BASKET arb
        # NO basket cost = N - sum_yes;  guaranteed payout = N - 1
        no_basket_cost = n - sum_yes
        if no_basket_cost <= 0:
            return None  # degenerate
        gross_return_pct = round((sum_yes - 1.0) / no_basket_cost * 100, 4)
        net_return_pct = round(gross_return_pct - fees_pct, 4)
        arb_type = "buy_no_basket"

    return {
        "sum_yes_price": round(sum_yes, 4),
        "deviation_from_one": deviation,
        "leg_count": n,
        "arb_type": arb_type,
        "gross_return_pct": gross_return_pct,
        "net_return_pct": net_return_pct,
        "fees_pct": fees_pct,
    }


async def _liquidity_check_legs(
    adapter: PolymarketAdapter,
    active_legs: list[dict],
    arb_type: str,
    test_usd_per_leg: int,
) -> tuple[list[Optional[bool]], LiquidityCheck]:
    """Probe orderbook for each leg, return per-leg fillable + summary."""
    if arb_type == "buy_yes_basket":
        token_ids = [leg["yes_token_id"] for leg in active_legs]
        side = "YES"
    else:
        token_ids = [leg["no_token_id"] for leg in active_legs]
        side = "NO"

    books = await asyncio.gather(
        *(adapter.fetch_orderbook(tid) for tid in token_ids),
        return_exceptions=True,
    )

    per_leg_fillable: list[Optional[bool]] = []
    for book in books:
        if isinstance(book, Exception):
            per_leg_fillable.append(None)
        else:
            per_leg_fillable.append(adapter.test_leg_fillable(book, test_usd_per_leg, side))

    fillable_count = sum(1 for f in per_leg_fillable if f is True)
    has_unknown = any(f is None for f in per_leg_fillable)

    if has_unknown:
        all_fillable: Optional[bool] = None
    else:
        all_fillable = all(f is True for f in per_leg_fillable)

    return per_leg_fillable, LiquidityCheck(
        tested_usd_per_leg=test_usd_per_leg,
        all_legs_fillable=all_fillable,
        fillable_leg_count=fillable_count,
        total_leg_count=len(active_legs),
    )


def _build_legs(
    active_legs: list[dict],
    arb_type: str,
    per_leg_fillable: list[Optional[bool]],
) -> list[OutcomeLeg]:
    legs: list[OutcomeLeg] = []
    side = "YES" if arb_type == "buy_yes_basket" else "NO"
    for raw_leg, fillable in zip(active_legs, per_leg_fillable):
        price = raw_leg["yes_price"] if side == "YES" else (1.0 - raw_leg["yes_price"])
        legs.append(OutcomeLeg(
            market_id=raw_leg["market_id"],
            question=raw_leg["question"],
            outcome_label=raw_leg["outcome_label"],
            side=side,
            price=round(price, 4),
            market_url=raw_leg["market_url"],
            liquidity_usd=raw_leg["liquidity_usd"],
            fillable=fillable,
        ))
    return legs


async def _build_opportunity(
    adapter: PolymarketAdapter,
    event: dict,
    active_legs: list[dict],
    config: dict,
) -> Optional[Opportunity]:
    arb = _compute_arb(event, active_legs, config)
    if arb is None:
        return None

    min_net = float(config.get("min_net_return_pct", -1.0))
    if arb["net_return_pct"] < min_net:
        return None

    test_usd = int(config.get("liquidity_test_amount_usd", 100))
    per_leg_fillable, liq_check = await _liquidity_check_legs(
        adapter, active_legs, arb["arb_type"], test_usd,
    )

    days = _days_to_resolution(event["resolution_date"])
    score, label = score_opportunity(
        gross_return_pct=arb["gross_return_pct"],
        net_return_pct=arb["net_return_pct"],
        all_fillable=liq_check.all_legs_fillable,
        leg_count=arb["leg_count"],
        days_to_resolution=days,
    )

    min_score = int(config.get("min_signal_score", 30))
    if score < min_score:
        return None

    notes = None
    if liq_check.all_legs_fillable is None:
        notes = (
            f"Order book unavailable on {sum(1 for f in per_leg_fillable if f is None)} "
            f"of {arb['leg_count']} legs; partial fillability reported."
        )
    elif not liq_check.all_legs_fillable:
        notes = (
            f"Only {liq_check.fillable_leg_count}/{arb['leg_count']} legs "
            f"can be filled at ${test_usd}; basket execution incomplete."
        )

    legs = _build_legs(active_legs, arb["arb_type"], per_leg_fillable)

    return Opportunity(
        id=Opportunity.make_id(event.get("slug", event["id"]), arb["arb_type"]),
        event_title=event["title"],
        event_url=event["event_url"],
        resolution_date=event["resolution_date"],
        arb_type=arb["arb_type"],
        leg_count=arb["leg_count"],
        sum_yes_price=arb["sum_yes_price"],
        deviation_from_one=arb["deviation_from_one"],
        fees_pct=arb["fees_pct"],
        gross_return_pct=arb["gross_return_pct"],
        net_return_pct=arb["net_return_pct"],
        legs=legs,
        liquidity=liq_check,
        signal_score=score,
        signal_label=label,
        notes=notes,
    )


async def run_scan(input_config: dict) -> tuple[list[Opportunity], ScanSummary]:
    adapter = PolymarketAdapter()

    max_events = int(input_config.get("max_events_to_scan", 1000))
    min_legs = int(input_config.get("min_legs_per_event", 3))
    min_event_liquidity = int(input_config.get("min_event_liquidity_usd", 5000))
    min_liquidity_per_leg = int(input_config.get("min_liquidity_per_leg_usd", 200))
    max_days = int(input_config.get("max_days_to_resolution", 365))

    raw_events = await adapter.fetch_open_events(max_events=max_events)
    logger.info(f"Fetched {len(raw_events)} raw events from Polymarket Gamma")

    normalized = [adapter.normalize_event(re_) for re_ in raw_events]

    # Filter to candidate events.
    eligible: list[tuple[dict, list[dict]]] = []
    for ev in normalized:
        if ev["liquidity_usd"] < min_event_liquidity:
            continue
        if not ev["resolution_date"]:
            continue
        if _days_to_resolution(ev["resolution_date"]) > max_days:
            continue
        active_legs = _filter_active_legs(ev["legs"], min_liquidity_per_leg)
        if len(active_legs) < min_legs:
            continue
        eligible.append((ev, active_legs))

    logger.info(
        f"Eligibility: {len(normalized)} normalized → {len(eligible)} pass filters "
        f"(≥{min_legs} legs, event liq ≥${min_event_liquidity:,}, "
        f"leg liq ≥${min_liquidity_per_leg:,}, ≤{max_days}d to resolve)"
    )

    # Build opportunities concurrently.
    opp_results = await asyncio.gather(
        *(_build_opportunity(adapter, ev, legs, input_config) for ev, legs in eligible),
        return_exceptions=True,
    )

    opportunities: list[Opportunity] = []
    for r in opp_results:
        if isinstance(r, Exception):
            logger.warning(f"Opportunity build failed: {r}")
        elif r is not None:
            opportunities.append(r)

    opportunities.sort(key=lambda o: o.signal_score, reverse=True)
    output_limit = int(input_config.get("output_limit", 50))
    opportunities = opportunities[:output_limit]

    summary = ScanSummary.from_opportunities(
        opportunities,
        total_events_scanned=len(normalized),
        eligible_events=len(eligible),
    )
    return opportunities, summary
