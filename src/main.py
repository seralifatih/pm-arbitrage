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

# ---------------------------------------------------------------------------
# Apify SDK with local-dev fallback so `python src/main.py` works without
# the platform context (acceptance gate requirement).
# ---------------------------------------------------------------------------
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
        "mode": "scan-all",
        "min_net_spread_pct": -3.0,
        "min_signal_score": 50,
        "min_liquidity_usd": 1000,
        "liquidity_test_amount_usd": 500,
        "max_days_to_resolution": 90,
        "include_manifold": False,
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


def _get_actor():
    if _APIFY_AVAILABLE and os.environ.get("APIFY_IS_AT_HOME"):
        return _ApifyActor
    return _MockActor()


async def main():
    actor = _get_actor()
    async with actor:
        input_config = await actor.get_input() or {}

        actor.log.info("Starting prediction market arbitrage scan...")
        actor.log.info(f"Config: {input_config}")

        opportunities, summary = await run_scan(input_config)

        actor.log.info(f"Scan complete. Found {len(opportunities)} opportunities.")

        if opportunities:
            await actor.push_data([opp.model_dump() for opp in opportunities])

        await actor.set_value("OUTPUT_SUMMARY", summary.model_dump())

        actor.log.info(f"Summary: {summary.model_dump()}")


if __name__ == "__main__":
    asyncio.run(main())
