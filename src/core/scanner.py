import asyncio
from datetime import date
from typing import Optional

from ..utils.fees import calculate_spread
from ..utils.logger import logger
from ..venues.base import VenueAdapter
from ..venues.kalshi import KalshiAdapter
from ..venues.polymarket import PolymarketAdapter
from .matcher import match_markets
from .models import LiquidityDepth, Opportunity, ScanSummary, VenuePosition
from .scorer import score_opportunity


def _build_adapters(input_config: dict) -> list[VenueAdapter]:
    max_days = int(input_config.get("max_days_to_resolution", 90))
    adapters: list[VenueAdapter] = [
        PolymarketAdapter(),
        KalshiAdapter(max_days_to_resolution=max_days),
    ]
    if input_config.get("include_manifold"):
        # placeholder — Manifold adapter not implemented in v1
        pass
    return adapters


def _days_to_resolution(resolution_date: str) -> int:
    try:
        d = date.fromisoformat(resolution_date[:10])
        return (d - date.today()).days
    except (ValueError, TypeError):
        return 99999


def _passes_market_filter(market: dict, min_liquidity: int, max_days: int) -> bool:
    if not market.get("is_binary"):
        return False
    if market.get("liquidity_usd", 0) < min_liquidity:
        return False
    if _days_to_resolution(market.get("resolution_date", "")) > max_days:
        return False
    return True


async def _safe_fetch_markets(adapter: VenueAdapter) -> list[dict]:
    try:
        raw = await adapter.fetch_open_markets()
    except Exception as exc:
        logger.warning(f"Venue {adapter.name} fetch failed: {exc}")
        return []

    normalized = []
    for r in raw:
        n = _safe_normalize(adapter, r)
        if n is not None:
            normalized.append(n)
    return normalized


def _safe_normalize(adapter: VenueAdapter, raw: dict) -> Optional[dict]:
    try:
        return adapter.normalize_market(raw)
    except Exception as exc:
        logger.warning(f"Venue {adapter.name} normalize failed: {exc}")
        return None


def _pick_sides(market_a: dict, market_b: dict) -> tuple[str, str, float, float]:
    """
    Choose YES/NO sides so the implied prices sum nearest to 1.0.
    Returns (side_a, side_b, price_a, price_b).
    """
    yes_a, no_a = market_a["yes_price"], market_a["no_price"]
    yes_b, no_b = market_b["yes_price"], market_b["no_price"]

    # YES on A + NO on B (canonical) vs NO on A + YES on B
    cost_yes_no = yes_a + no_b
    cost_no_yes = no_a + yes_b

    if cost_yes_no <= cost_no_yes:
        return ("YES", "NO", yes_a, no_b)
    return ("NO", "YES", no_a, yes_b)


async def _build_opportunity(
    pair: dict,
    adapter_a: VenueAdapter,
    adapter_b: VenueAdapter,
    input_config: dict,
) -> Optional[Opportunity]:
    market_a = pair["market_a"]
    market_b = pair["market_b"]

    side_a, side_b, price_a, price_b = _pick_sides(market_a, market_b)
    spread = calculate_spread(price_a, price_b, adapter_a.name, adapter_b.name)

    min_net = float(input_config.get("min_net_spread_pct", -3.0))
    if spread["net_spread_pct"] < min_net:
        return None

    test_usd = int(input_config.get("liquidity_test_amount_usd", 500))

    book_a, book_b = await asyncio.gather(
        adapter_a.fetch_orderbook(market_a["id"]),
        adapter_b.fetch_orderbook(market_b["id"]),
        return_exceptions=False,
    )

    depth_a = adapter_a.test_liquidity_depth(book_a, test_usd, price_a)
    depth_b = adapter_b.test_liquidity_depth(book_b, test_usd, price_b)

    # Combined fillable: both sides must be fillable. If either is unknown → unknown.
    if depth_a["fillable"] is None or depth_b["fillable"] is None:
        fillable: Optional[bool] = None
    else:
        fillable = depth_a["fillable"] and depth_b["fillable"]

    impacts = [d["price_impact_pct"] for d in (depth_a, depth_b) if d["price_impact_pct"] is not None]
    price_impact = round(max(impacts), 4) if impacts else None

    days = _days_to_resolution(market_a.get("resolution_date", ""))

    score, label = score_opportunity(
        gross_spread_pct=spread["gross_spread_pct"],
        net_spread_pct=spread["net_spread_pct"],
        fillable=fillable,
        match_confidence=pair["match_confidence"],
        days_to_resolution=days,
    )

    min_score = int(input_config.get("min_signal_score", 50))
    if score < min_score:
        return None

    notes = None
    if fillable is None:
        notes = "Order book unavailable on at least one venue; fillable indeterminate."

    opp_id = Opportunity.make_id(market_a.get("title", ""), adapter_a.name, adapter_b.name)

    return Opportunity(
        id=opp_id,
        event_title=market_a.get("title", ""),
        resolution_date=market_a.get("resolution_date", ""),
        venue_a=VenuePosition(
            name=adapter_a.name,
            market_url=market_a.get("market_url", ""),
            side=side_a,
            price_cents=int(round(price_a * 100)),
            liquidity_usd=market_a.get("liquidity_usd", 0),
        ),
        venue_b=VenuePosition(
            name=adapter_b.name,
            market_url=market_b.get("market_url", ""),
            side=side_b,
            price_cents=int(round(price_b * 100)),
            liquidity_usd=market_b.get("liquidity_usd", 0),
        ),
        gross_spread_pct=spread["gross_spread_pct"],
        fees_pct=spread["fees_pct"],
        net_spread_pct=spread["net_spread_pct"],
        liquidity_depth=LiquidityDepth(
            tested_usd=test_usd,
            fillable=fillable,
            price_impact_pct=price_impact,
        ),
        match_confidence=pair["match_confidence"],
        signal_score=score,
        signal_label=label,
        notes=notes,
    )


async def run_scan(input_config: dict) -> tuple[list[Opportunity], ScanSummary]:
    adapters = _build_adapters(input_config)

    # Step 2: concurrent venue fetches
    raw_results = await asyncio.gather(
        *(_safe_fetch_markets(a) for a in adapters),
        return_exceptions=True,
    )

    venue_markets: dict[str, list[dict]] = {}
    for adapter, result in zip(adapters, raw_results):
        if isinstance(result, Exception):
            logger.warning(f"Venue {adapter.name} skipped: {result}")
            venue_markets[adapter.name] = []
        else:
            venue_markets[adapter.name] = result
            logger.info(f"Venue {adapter.name}: fetched {len(result)} normalized markets")

    # Step 4: filter normalized markets
    min_liquidity = int(input_config.get("min_liquidity_usd", 1000))
    max_days = int(input_config.get("max_days_to_resolution", 90))

    filtered: dict[str, list[dict]] = {}
    for adapter in adapters:
        all_markets = venue_markets[adapter.name]
        binary_count = sum(1 for m in all_markets if m.get("is_binary"))
        liq_pass = sum(
            1 for m in all_markets
            if m.get("is_binary") and m.get("liquidity_usd", 0) >= min_liquidity
        )
        filtered[adapter.name] = [
            m for m in all_markets
            if _passes_market_filter(m, min_liquidity, max_days)
        ]
        logger.info(
            f"Venue {adapter.name}: {len(all_markets)} total → "
            f"{binary_count} binary → {liq_pass} pass liquidity ≥{min_liquidity} → "
            f"{len(filtered[adapter.name])} pass days ≤{max_days}"
        )

    # Step 5: match across venue pairs (only Polymarket ↔ Kalshi for v1)
    total_pairs = 0
    all_opportunities: list[Opportunity] = []

    for i, adapter_a in enumerate(adapters):
        markets_a = filtered[adapter_a.name]
        if not markets_a:
            continue

        for adapter_b in adapters[i + 1:]:
            markets_b = filtered[adapter_b.name]
            if not markets_b:
                continue

            matches = match_markets(markets_a, markets_b, adapter_a.name, adapter_b.name)
            total_pairs += len(matches)
            logger.info(
                f"Match {adapter_a.name}↔{adapter_b.name}: "
                f"{len(markets_a)}×{len(markets_b)} = {len(markets_a)*len(markets_b)} candidate pairs → "
                f"{len(matches)} passed all gates (binary, date≤30d, ≥2 shared entities, conf≥70)"
            )
            if not matches and markets_a and markets_b:
                # Diagnostic: log top 3 raw title-similarity scores so we can
                # see whether titles, dates, or entity-overlap is the blocker.
                from rapidfuzz import fuzz as _fuzz
                top = []
                for ma in markets_a[:100]:
                    for mb in markets_b[:100]:
                        sc = _fuzz.token_sort_ratio(ma.get("title", ""), mb.get("title", ""))
                        top.append((sc, ma.get("title", "")[:60], mb.get("title", "")[:60],
                                    ma.get("resolution_date", ""), mb.get("resolution_date", "")))
                top.sort(reverse=True)
                logger.info(f"Top 3 cross-venue title scores (no matches passed):")
                for sc, ta, tb, da, db in top[:3]:
                    logger.info(f"  score={sc} | A({da}): {ta!r} | B({db}): {tb!r}")

            # Step 6: build opportunities concurrently
            opp_results = await asyncio.gather(
                *(_build_opportunity(p, adapter_a, adapter_b, input_config) for p in matches),
                return_exceptions=True,
            )

            for r in opp_results:
                if isinstance(r, Exception):
                    logger.warning(f"Opportunity build failed: {r}")
                elif r is not None:
                    all_opportunities.append(r)

    # Step 7+8: sort + cap
    all_opportunities.sort(key=lambda o: o.signal_score, reverse=True)
    output_limit = int(input_config.get("output_limit", 50))
    all_opportunities = all_opportunities[:output_limit]

    summary = ScanSummary.from_opportunities(all_opportunities, total_pairs_scanned=total_pairs)
    return all_opportunities, summary
