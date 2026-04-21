"""Live scan harness — runs against real venue APIs and verifies invariants."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rapidfuzz import fuzz

from src.core.scanner import (
    _build_adapters,
    _passes_market_filter,
    _safe_fetch_markets,
    run_scan,
)


CONFIG = {
    "mode": "scan-all",
    "min_net_spread_pct": -5.0,
    "min_signal_score": 30,
    "min_liquidity_usd": 500,
    "liquidity_test_amount_usd": 100,
    "max_days_to_resolution": 60,
    "output_limit": 10,
}


def _verify_invariants(opps: list) -> list[str]:
    errors: list[str] = []
    required = {
        "id", "event_title", "resolution_date", "venue_a", "venue_b",
        "gross_spread_pct", "fees_pct", "net_spread_pct",
        "liquidity_depth", "match_confidence", "signal_score", "signal_label",
    }

    for i, opp in enumerate(opps):
        d = opp.model_dump()

        # 2. Required fields present
        missing = required - set(d.keys())
        if missing:
            errors.append(f"opp[{i}] missing fields: {missing}")

        # 3. signal_score 0–100
        if not 0 <= d["signal_score"] <= 100:
            errors.append(f"opp[{i}] signal_score out of range: {d['signal_score']}")

        # 4. net = gross - fees (within float tolerance)
        expected = round(d["gross_spread_pct"] - d["fees_pct"], 2)
        actual = round(d["net_spread_pct"], 2)
        if abs(expected - actual) > 0.01:
            errors.append(
                f"opp[{i}] net_spread_pct mismatch: "
                f"gross={d['gross_spread_pct']} fees={d['fees_pct']} "
                f"net={d['net_spread_pct']} expected={expected}"
            )

        # 5. fillable must be True/False/None — key must exist
        depth = d["liquidity_depth"]
        if "fillable" not in depth:
            errors.append(f"opp[{i}] liquidity_depth.fillable key missing")
        elif depth["fillable"] not in (True, False, None):
            errors.append(f"opp[{i}] fillable invalid value: {depth['fillable']!r}")

    return errors


async def _debug_top_candidates():
    """When no matches surface, dump the top 5 cross-venue title similarity scores."""
    adapters = _build_adapters(CONFIG)
    raw_results = await asyncio.gather(*(_safe_fetch_markets(a) for a in adapters))

    poly = [m for m in raw_results[0] if _passes_market_filter(m, 500, 60)]
    kalshi = [m for m in raw_results[1] if _passes_market_filter(m, 500, 60)]

    print(f"\nFiltered market counts: polymarket={len(poly)}, kalshi={len(kalshi)}")

    candidates = []
    for p in poly[:200]:
        for k in kalshi[:200]:
            score = fuzz.token_sort_ratio(p.get("title", ""), k.get("title", ""))
            if score >= 50:
                candidates.append((score, p.get("title", ""), k.get("title", "")))

    candidates.sort(reverse=True)
    print("\nTop 5 cross-venue title similarity candidates:")
    for score, p_title, k_title in candidates[:5]:
        print(f"  score={score}")
        print(f"    poly:   {p_title[:90]}")
        print(f"    kalshi: {k_title[:90]}")


async def main():
    print("=" * 70)
    print("LIVE SCAN — pm-arbitrage")
    print("=" * 70)
    print(f"Config: {json.dumps(CONFIG, indent=2)}")

    opps, summary = await run_scan(CONFIG)

    print(f"\nResults: {len(opps)} opportunities, {summary.total_pairs_scanned} total pairs scanned")
    print(f"Summary: {summary.model_dump_json(indent=2)}")

    if not opps:
        print("\n[!] No opportunities returned — running debug to inspect candidates")
        await _debug_top_candidates()
        return 0

    print(f"\n--- {len(opps)} opportunities ---")
    for i, opp in enumerate(opps[:3]):
        print(f"\n[{i}] {opp.event_title[:80]}")
        print(json.dumps(opp.model_dump(), indent=2, default=str))

    errors = _verify_invariants(opps)
    if errors:
        print(f"\n[X] {len(errors)} INVARIANT VIOLATIONS:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"\n[OK] All {len(opps)} opportunities pass invariant checks.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
