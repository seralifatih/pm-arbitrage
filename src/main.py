import asyncio
import json
import os
import sys
from pathlib import Path

# Allow `python src/main.py` from project root by ensuring the repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.core.scanner import run_scan  # noqa: E402

try:
    from apify import Actor as _ApifyActor
    _APIFY_AVAILABLE = True
except ImportError:
    _APIFY_AVAILABLE = False
    _ApifyActor = None


class _MockLog:
    def info(self, msg): print(f"[INFO] {msg}")
    def warning(self, msg): print(f"[WARN] {msg}")
    def error(self, msg): print(f"[ERROR] {msg}")


class _MockActor:
    """Minimal stand-in used when running outside the Apify platform."""

    log = _MockLog()

    _default_input = {
        "min_net_return_pct": -1.0,
        "min_signal_score": 30,
        "min_event_liquidity_usd": 5000,
        "min_liquidity_per_leg_usd": 200,
        "min_legs_per_event": 3,
        "liquidity_test_amount_usd": 100,
        "max_days_to_resolution": 365,
        "max_events_to_scan": 1000,
        "output_limit": 50,
    }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get_input(self):
        return dict(self._default_input)

    async def push_data(self, data):
        print(f"[MockActor] push_data: {len(data)} records")

    async def set_value(self, key, value):
        print(f"[MockActor] set_value '{key}':")
        print(json.dumps(value, indent=2, default=str))

    async def charge(self, event_name: str, count: int = 1):
        print(f"[MockActor] charge '{event_name}' x{count}")


def _get_actor():
    if _APIFY_AVAILABLE and os.environ.get("APIFY_IS_AT_HOME"):
        return _ApifyActor
    return _MockActor()


async def _safe_charge(actor, event_name: str, count: int = 1) -> None:
    """Call Actor.charge if available; never let billing break a scan."""
    if count <= 0:
        return
    try:
        await actor.charge(event_name, count)
    except Exception as exc:
        actor.log.warning(f"Charge for '{event_name}' x{count} failed: {exc}")


async def main():
    actor = _get_actor()
    async with actor:
        input_config = await actor.get_input() or {}

        actor.log.info("Starting Polymarket multi-outcome arbitrage scan...")
        actor.log.info(f"Config: {input_config}")

        opportunities, summary = await run_scan(input_config)

        actor.log.info(f"Scan complete. Found {len(opportunities)} opportunities.")

        if opportunities:
            await actor.push_data([opp.model_dump() for opp in opportunities])
            # Bill one event per opportunity returned to the dataset.
            await _safe_charge(actor, "opportunity_returned", len(opportunities))

        await actor.set_value("OUTPUT_SUMMARY", summary.model_dump())

        # Bill one event per successful scan, regardless of result count.
        # Charged last so partial-failure runs don't get billed for the run fee.
        await _safe_charge(actor, "scan_completed", 1)

        actor.log.info(f"Summary: {summary.model_dump()}")


if __name__ == "__main__":
    asyncio.run(main())
