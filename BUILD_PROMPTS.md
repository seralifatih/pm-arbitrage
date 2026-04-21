# BUILD_PROMPTS.md — pm-arbitrage
**Actor:** `seralifatih/pm-arbitrage`
**Tool:** Cursor (with CLAUDE.md + CONCEPT_NOTE.md in context for every prompt)
**Language:** Python 3.11

---

## How to Use These Prompts

1. Open Cursor in the `pm-arbitrage/` project root.
2. Add `CLAUDE.md` and `CONCEPT_NOTE.md` to Cursor context before every session.
3. Run prompts in order. Each prompt builds on the output of the previous one.
4. After each prompt: run `pytest tests/ -v` before proceeding.
5. Do not skip prompts. Each one has a defined acceptance gate.

---

## Prompt 01 — Project Scaffold

```
Read CLAUDE.md and CONCEPT_NOTE.md fully.

Create the full project scaffold for the pm-arbitrage Apify actor:

1. Create the directory structure exactly as defined in CLAUDE.md under "Repository Structure".
2. Create `requirements.txt` with these dependencies:
   - apify-client
   - httpx
   - rapidfuzz
   - pydantic>=2.0
   - python-dateutil
3. Create `.actor/actor.json` with:
   - name: pm-arbitrage
   - version: 0.1.0
   - buildTag: latest
   - memoryMbytes: 512
   - title: Prediction Market Arbitrage Scanner
   - description: Cross-venue arbitrage signal engine for Polymarket and Kalshi
4. Create `.actor/input_schema.json` exactly as defined in CLAUDE.md under "Input Schema".
5. Create stub `__init__.py` files for all packages.
6. Create `src/main.py` with a minimal Apify Actor entry point that:
   - Reads input using `Actor.get_input()`
   - Prints "Actor started" to log
   - Pushes an empty array to dataset
   - Has a TODO comment for the scanner call
7. Do NOT implement any business logic yet.

Acceptance gate: `python src/main.py` runs without errors (you may need to mock the Apify context).
```

---

## Prompt 02 — Pydantic Models

```
Read CLAUDE.md fully, especially the "Output Schema" section.

Create `src/core/models.py` with all Pydantic v2 models exactly as defined:
- LiquidityDepth
- VenuePosition
- Opportunity
- ScanSummary

Requirements:
- Use Pydantic v2 syntax (model_config, not class Config)
- All Optional fields must have default=None
- Add a classmethod `Opportunity.make_id(event_title, venue_a_name, venue_b_name)` that
  generates a slug: lowercase, spaces→hyphens, max 80 chars, format:
  "{event_slug}-{venue_a}-{venue_b}"
- Add `ScanSummary.from_opportunities(opportunities: list[Opportunity]) -> ScanSummary`
  that computes all summary fields from the list

Create `tests/test_models.py` with tests for:
- make_id produces correct slug format
- ScanSummary.from_opportunities correctly counts pure_arb (net_spread > 0) vs ev_positive
- All required fields raise ValidationError if missing

Acceptance gate: `pytest tests/test_models.py -v` all pass.
```

---

## Prompt 03 — Fee Calculator

```
Read CLAUDE.md, especially "Venue API Reference" fee sections.

Create `src/utils/fees.py` with:

1. Fee constants:
   FEE_POLYMARKET = 0.02   # 2% taker
   FEE_KALSHI = 0.07       # 7% combined
   FEE_MANIFOLD = 0.0      # play money, no fees
   FEE_MYRIAD = 0.02       # approximate

   VENUE_FEES = {
     "polymarket": FEE_POLYMARKET,
     "kalshi": FEE_KALSHI,
     "manifold": FEE_MANIFOLD,
     "myriad": FEE_MYRIAD,
   }

2. Function `calculate_spread(yes_price: float, no_price: float, venue_a: str, venue_b: str) -> dict`:
   - yes_price and no_price are 0.0–1.0 (not cents)
   - Returns dict with keys: gross_spread_pct, fees_pct, net_spread_pct
   - gross_spread_pct = (1.0 - yes_price - no_price) / (yes_price + no_price) * 100
   - fees_pct = (VENUE_FEES[venue_a] + VENUE_FEES[venue_b]) * 100
   - net_spread_pct = gross_spread_pct - fees_pct

Create `tests/test_fees.py` with tests for:
- A pure arb case (gross > fees, net > 0)
- A marginal case (gross < fees, net < 0)
- Edge case: yes_price + no_price exactly = 1.0 (zero gross spread)
- Unknown venue raises KeyError

Acceptance gate: `pytest tests/test_fees.py -v` all pass.
```

---

## Prompt 04 — Base Venue Adapter

```
Read CLAUDE.md fully.

Create `src/venues/base.py` with an abstract base class `VenueAdapter`:

```python
from abc import ABC, abstractmethod
from src.core.models import VenuePosition

class VenueAdapter(ABC):
    name: str  # class-level constant, e.g. "polymarket"
    
    @abstractmethod
    async def fetch_open_markets(self) -> list[dict]:
        """Return list of raw market dicts from this venue."""
        ...
    
    @abstractmethod
    def normalize_market(self, raw: dict) -> dict:
        """
        Normalize raw market dict to standard shape:
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
          "raw": dict               # original for debugging
        }
        """
        ...
    
    @abstractmethod
    async def fetch_orderbook(self, market_id: str) -> dict | None:
        """Return raw orderbook dict, or None if unavailable."""
        ...
    
    def test_liquidity_depth(self, orderbook: dict, test_usd: int, yes_price: float) -> dict:
        """
        Walk the ask side of the order book to simulate a test_usd purchase.
        Returns: {fillable: bool, price_impact_pct: float}
        If orderbook is None, returns {fillable: None, price_impact_pct: None}
        """
        ...  # implement this one here (not abstract) — shared logic for all venues
```

The `test_liquidity_depth` method should be fully implemented in base.py.
It walks asks from lowest to highest. If cumulative size * price >= test_usd before
price moves > 0.5% from yes_price, return fillable=True. Otherwise False.

Do NOT create httpx clients in base.py. Subclasses handle transport.

Acceptance gate: base.py imports without error, no abstract methods leak.
```

---

## Prompt 05 — Polymarket Adapter

```
Read CLAUDE.md "Venue API Reference → Polymarket" section fully.

Create `src/venues/polymarket.py` implementing PolymarketAdapter(VenueAdapter):

1. fetch_open_markets():
   - GET https://gamma-api.polymarket.com/markets?closed=false&limit=500
   - Use httpx.AsyncClient with timeout=10
   - Return raw list of market dicts
   - Handle pagination if total > 500 (check response for next cursor or total count)

2. normalize_market(raw):
   - Map fields per CLAUDE.md market object shape
   - Parse outcomePrices[0] as yes_price, [1] as no_price (strings → float)
   - Parse endDate as resolution_date (strip time component)
   - is_binary = True only if len(outcomes) == 2 and "Yes"/"No" in outcomes
   - market_url = f"https://polymarket.com/event/{raw['slug']}" if slug exists, else construct from conditionId

3. fetch_orderbook(market_id):
   - market_id here is the YES token_id (from clobTokenIds[0] in raw)
   - GET https://clob.polymarket.com/book?token_id={token_id}
   - Return raw orderbook dict with bids/asks arrays
   - Return None on any error (do not raise)

Add `tests/fixtures/polymarket_markets.json` with 5 sample markets (mix of binary and non-binary).
Add `tests/fixtures/polymarket_orderbook.json` with a sample orderbook.

Create `tests/test_polymarket.py` using fixtures (no live API calls — mock httpx):
- normalize_market correctly parses prices from strings
- normalize_market sets is_binary=False for non-binary market
- fetch_orderbook returns None on 404

Acceptance gate: `pytest tests/test_polymarket.py -v` all pass.
```

---

## Prompt 06 — Kalshi Adapter

```
Read CLAUDE.md "Venue API Reference → Kalshi" section fully.

Create `src/venues/kalshi.py` implementing KalshiAdapter(VenueAdapter):

1. fetch_open_markets():
   - GET https://trading-api.kalshi.com/trade-api/v2/markets?status=open&limit=200
   - Paginate using cursor if response includes next_cursor
   - Return combined raw list

2. normalize_market(raw):
   - yes_price = raw["yes_ask"] / 100  (convert cents to 0–1)
   - no_price = raw["no_ask"] / 100
   - resolution_date from raw["close_time"] (strip time)
   - is_binary = True (all Kalshi markets are binary)
   - market_url = f"https://kalshi.com/markets/{raw['ticker']}"

3. fetch_orderbook(market_id):
   - market_id = ticker string (e.g. "FED-25JUN-T5.25")
   - GET https://trading-api.kalshi.com/trade-api/v2/markets/{ticker}/orderbook?depth=10
   - Normalize asks to same shape as Polymarket (price as float 0–1, size as float USD)
   - Return None on any error

Add `tests/fixtures/kalshi_markets.json` with 5 sample markets.
Add `tests/fixtures/kalshi_orderbook.json` with a sample orderbook.

Create `tests/test_kalshi.py` (mock httpx, no live calls):
- normalize_market correctly converts cents to 0–1 prices
- fetch_orderbook normalizes asks to float prices
- fetch_open_markets handles pagination (mock two pages)

Acceptance gate: `pytest tests/test_kalshi.py -v` all pass.
```

---

## Prompt 07 — Market Matcher

```
Read CLAUDE.md "Matching Logic (matcher.py)" section fully.

Create `src/core/matcher.py` with function:

def match_markets(
    markets_a: list[dict],   # normalized dicts from venue A
    markets_b: list[dict],   # normalized dicts from venue B
    venue_a_name: str,
    venue_b_name: str
) -> list[dict]:
    """
    Returns list of matched pairs:
    {
      "market_a": dict,         # normalized market from venue A
      "market_b": dict,         # normalized market from venue B
      "venue_a_name": str,
      "venue_b_name": str,
      "match_confidence": int,  # 0–100
      "date_diff_days": int
    }
    Only pairs with match_confidence >= 70 are returned.
    """

Implement the 5-step matching logic exactly as described in CLAUDE.md:
1. Category pre-filter (if category field exists on both)
2. Date window filter (≤ 3 days apart)
3. Title similarity via rapidfuzz.fuzz.token_sort_ratio (threshold ≥ 75)
4. Entity overlap check (strip stopwords + numbers, check core noun overlap)
5. Binary structure check (both must have is_binary=True)

match_confidence formula (weighted average as specified in CLAUDE.md).

Create `tests/test_matcher.py`:
- Clear match: "Will Fed cut rates June 2025" ↔ "Fed rate cut June 2025 FOMC?" → confidence ≥ 85
- Date too far: same title, 10 days apart → excluded
- Non-binary market A → excluded
- Low title similarity (unrelated markets) → excluded
- Returns empty list when no matches found

Acceptance gate: `pytest tests/test_matcher.py -v` all pass.
```

---

## Prompt 08 — Signal Scorer

```
Read CLAUDE.md "Scorer Logic (scorer.py)" section fully.

Create `src/core/scorer.py` with function:

def score_opportunity(
    gross_spread_pct: float,
    net_spread_pct: float,
    fillable: bool | None,
    match_confidence: int,
    days_to_resolution: int
) -> tuple[int, str]:
    """
    Returns (signal_score: int 0–100, signal_label: str)
    """

Implement the weighted scoring formula exactly as in CLAUDE.md:
- net_spread_pct component: 0% = 0 pts, 5%+ = 40 pts (linear interpolation)
- liquidity fillable: 25 pts if True, 0 if False, 12 if None (uncertain)
- match_confidence: pass through, scale to 20 pts max
- days_to_resolution: 0–30 = 15 pts, 31–90 = 7 pts, 90+ = 0 pts

signal_label mapping:
- score ≥ 80 AND net_spread_pct > 0: "Pure arbitrage"
- score ≥ 80 AND net_spread_pct ≤ 0: "Strong EV+ signal"
- score 60–79: "Strong EV+ signal"
- score 40–59: "EV+ with edge"
- score < 40: "Marginal"

Create `tests/test_scorer.py`:
- Perfect case (5% net spread, fillable, 95 confidence, 5 days) → score ≥ 85, label "Pure arbitrage"
- Zero net spread → check correct label
- Null fillable → partial liquidity score (12 pts)
- 100 days to resolution → 0 days component

Acceptance gate: `pytest tests/test_scorer.py -v` all pass.
```

---

## Prompt 09 — Scanner Orchestrator

```
Read CLAUDE.md fully, especially "Error Handling Rules" and "Invariants".

Create `src/core/scanner.py` with the main orchestration function:

async def run_scan(input_config: dict) -> tuple[list[Opportunity], ScanSummary]:
    """
    Full scan pipeline:
    1. Instantiate enabled venue adapters
    2. Fetch open markets from all venues concurrently (asyncio.gather)
    3. Normalize all markets
    4. Filter: is_binary=True, liquidity >= min_liquidity_usd, days_to_resolution <= max_days_to_resolution
    5. Run matcher for each venue pair (Polymarket ↔ Kalshi for v1)
    6. For each matched pair:
       a. Calculate spread (fees.calculate_spread)
       b. Filter by min_net_spread_pct
       c. Fetch orderbooks concurrently for the pair
       d. Test liquidity depth
       e. Score the opportunity (scorer.score_opportunity)
       f. Filter by min_signal_score
       g. Build Opportunity object
    7. Sort by signal_score descending
    8. Apply output_limit
    9. Build ScanSummary
    10. Return (opportunities, summary)
    """

Error handling: follow all rules from CLAUDE.md "Error Handling Rules".
Never let a single venue failure crash the scan.
Use asyncio.gather with return_exceptions=True for concurrent venue fetches.

Create `tests/test_scanner.py` using fully mocked adapters (no live API calls):
- Happy path: 2 venues, 3 matched pairs, returns sorted opportunities
- Venue A timeout: scan continues with Venue B only, logs warning
- Zero matches: returns empty list + correct summary
- min_signal_score filter: only high-scoring opportunities pass

Acceptance gate: `pytest tests/test_scanner.py -v` all pass.
```

---

## Prompt 10 — Main Entry Point + Apify Integration

```
Read CLAUDE.md fully.

Update `src/main.py` to be the full Apify Actor entry point:

```python
from apify import Actor
from src.core.scanner import run_scan
from src.core.models import ScanSummary

async def main():
    async with Actor:
        input_config = await Actor.get_input() or {}
        
        Actor.log.info("Starting prediction market arbitrage scan...")
        Actor.log.info(f"Config: {input_config}")
        
        opportunities, summary = await run_scan(input_config)
        
        Actor.log.info(f"Scan complete. Found {len(opportunities)} opportunities.")
        
        # Push opportunities to dataset
        if opportunities:
            await Actor.push_data([opp.model_dump() for opp in opportunities])
        
        # Push summary to key-value store
        await Actor.set_value("OUTPUT_SUMMARY", summary.model_dump())
        
        Actor.log.info(f"Summary: {summary.model_dump()}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

Then write the full README.md for the Apify Store listing following the template in CLAUDE.md.

README must include:
- Header: "No noise, just alpha."
- What It Does section (3 sentences max)
- Who It's For section
- Input Parameters table (all fields with types, defaults, descriptions)
- Output Schema section with the full JSON example from CONCEPT_NOTE.md
- How to Run section (UI steps + API curl example)
- Disclaimer (exact text from CLAUDE.md)

Acceptance gate: `python src/main.py` runs with empty input and outputs valid JSON summary. README is complete and matches Apify Store format.
```

---

## Prompt 11 — Integration Test with Live APIs (Manual)

```
⚠️ This prompt requires live API access. Run manually, not in CI.

Run a live scan against real Polymarket and Kalshi APIs with these settings:
{
  "mode": "scan-all",
  "min_net_spread_pct": -5.0,
  "min_signal_score": 30,
  "min_liquidity_usd": 500,
  "liquidity_test_amount_usd": 100,
  "max_days_to_resolution": 60,
  "output_limit": 10
}

Verify:
1. At least one matched pair is returned (if not, log the top 5 candidate pairs by title similarity for debugging)
2. All opportunity objects have all required fields
3. signal_scores are within 0–100 range
4. net_spread_pct is always gross_spread_pct - fees_pct
5. liquidity_depth.fillable is never missing (should be True, False, or null)

Fix any issues found. Document any Polymarket or Kalshi API quirks discovered in CLAUDE.md under a new "Known API Quirks" section.

Acceptance gate: Live scan returns valid JSON, all invariants hold.
```

---

## Prompt 12 — Polish + Apify Push

```
Final pre-launch polish pass:

1. Review README.md against the live actor page format at https://apify.com/seralifatih/arbitrage.
   Match the structure, tone ("No noise, just alpha." opener), and section flow.

2. Update .actor/actor.json with:
   - categories: ["finance", "developer-tools"]
   - Add a proper icon reference if Apify supports it

3. Add a `Makefile` with targets:
   - test: pytest tests/ -v
   - run-local: python src/main.py
   - push: apify push

4. Final check: run `pytest tests/ -v` — all must pass.

5. Run `apify push` to deploy.

6. After push, run the actor once from Apify Console with default settings.
   Screenshot the output JSON for the README "Output Example" section.

Acceptance gate: Actor is live at https://apify.com/seralifatih/pm-arbitrage with correct metadata, passing run, and complete README.
```

---

## Prompt 13 — v2 Matcher Rewrite

```
Background: v1 matcher uses raw `rapidfuzz.fuzz.token_sort_ratio >= 60` on
event titles. Live data shows the same real-world event scores 55–70 across
venues because Polymarket and Kalshi phrase titles very differently:

  Polymarket: "Will the Lakers win the 2026 NBA Finals?"
  Kalshi:     "NBA Finals winner — Los Angeles Lakers"
  Polymarket: "Will the Fed cut rates at the June 2025 FOMC meeting?"
  Kalshi:     "FED-25JUN-T5.25 — Fed funds rate above 5.25% after June 2025?"

The v1 threshold drop to 60 was a temporary unblock that lets a few real
matches surface but is fragile and noisy. Rebuild the matcher properly.

Goal: replace the title-only fuzzy match with a normalize-then-score
pipeline that handles the structural divergence between venues.

Tasks:

1. Add `src/core/title_normalizer.py` with `normalize_title(title: str) -> str`:
   - Strip leading "Will ", "Does ", "Is ", "Has " (Polymarket question form)
   - Strip Kalshi-style ticker prefixes (UPPERCASE-with-dashes followed by " — ")
   - Strip date phrases ("by end of 2025", "after June 2025 meeting", etc.)
   - Strip trailing "?"
   - Strip parenthesized aside ("(FOMC)", "(by Q4)", etc.)
   - Lowercase, collapse whitespace
   - Return the normalized core phrase

2. Update `src/core/matcher.py` to compute title similarity on
   normalized titles, not raw. Keep title threshold at 75 against
   normalized inputs (much tighter signal).

3. Add a "key entities" extraction step that pulls proper nouns + numbers
   (e.g. "Lakers", "Fed", "5.25", "2025") and weights entity overlap up
   to 35% of the confidence score (was 20% in v1). Title drops to 35%,
   date stays at 30%.

4. Build a fixture set in `tests/fixtures/cross_venue_pairs.json` with
   at least 15 hand-labeled pairs (true_match: bool) sourced from a
   live `scripts/live_scan.py` run. Include:
   - 5 known true matches (same event, different phrasing)
   - 5 known false matches (similar wording, different events)
   - 5 edge cases (numerical thresholds, multi-leg events)

5. Add `tests/test_matcher_v2.py` that runs the matcher against the
   fixture set and asserts precision >= 0.85 and recall >= 0.70.

6. Re-run live scan and confirm `total_pairs_scanned > 0` and at least
   one opportunity surfaces with `match_confidence >= 75`.

Acceptance gate: tests/test_matcher_v2.py passes; live scan returns ≥1
opportunity with match_confidence ≥ 75; v1 unit tests still pass.
```
