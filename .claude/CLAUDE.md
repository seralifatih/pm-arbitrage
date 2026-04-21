# CLAUDE.md — pm-arbitrage (Apify Actor)
**Actor:** `seralifatih/pm-arbitrage`
**Stack:** Python 3.11 · Apify SDK · httpx · rapidfuzz
**Related actors:** `seralifatih/arbitrage`, `seralifatih/cex-funding-rate-arbitrage`

---

## Project Purpose

This Apify Actor is a prediction market cross-venue arbitrage scanner. It ingests public market data from Polymarket and Kalshi (v1), fuzzy-matches markets covering the same real-world event, calculates net spread after fees, tests liquidity depth, and returns a confidence-scored JSON signal feed — no raw data dumps, only actionable opportunities.

This is a **signal engine**, not a scraper. The output must be decision-ready JSON with clear labels (signal_score, signal_label, net_spread_pct, fillable).

---

## Repository Structure

```
pm-arbitrage/
├── CLAUDE.md                 ← this file
├── CONCEPT_NOTE.md           ← product spec
├── BUILD_PROMPTS.md          ← sequenced Cursor prompts
├── .actor/
│   ├── actor.json            ← Apify actor metadata
│   └── input_schema.json     ← UI input form definition
├── src/
│   ├── main.py               ← Apify entry point
│   ├── venues/
│   │   ├── __init__.py
│   │   ├── base.py           ← abstract VenueAdapter class
│   │   ├── polymarket.py     ← Polymarket REST + CLOB adapter
│   │   └── kalshi.py         ← Kalshi REST adapter
│   ├── core/
│   │   ├── __init__.py
│   │   ├── matcher.py        ← fuzzy market matching logic
│   │   ├── scanner.py        ← orchestrates venue adapters + matching
│   │   ├── scorer.py         ← signal_score + signal_label computation
│   │   └── models.py         ← Pydantic models for all data shapes
│   └── utils/
│       ├── __init__.py
│       ├── fees.py           ← per-venue fee constants and calculator
│       └── logger.py         ← structured logging
├── tests/
│   ├── test_matcher.py
│   ├── test_scorer.py
│   └── fixtures/             ← JSON mock responses for each venue
└── requirements.txt
```

---

## Core Invariants — Never Violate These

1. **Signal-first output.** Every opportunity object must have `signal_score`, `signal_label`, `net_spread_pct`, and `liquidity_depth.fillable`. Strip nothing from the output schema.

2. **Modular adapters.** Each venue is its own adapter class inheriting from `base.VenueAdapter`. The scanner never calls venue APIs directly — always via adapters. Adding a new venue = adding one file in `venues/`.

3. **Fees are always applied.** Never return `gross_spread_pct` alone as the headline metric. Always compute `net_spread_pct = gross_spread_pct - fees_pct`. Misleading a trader about fees is a critical bug.

4. **Liquidity tests are real, not estimated.** Walk the order book; do not interpolate or assume. If the order book endpoint is unavailable, set `fillable: null` and flag it — never assume fillable.

5. **Match confidence gates opportunities.** Markets with `match_confidence < 70` are excluded from opportunities output by default. They may appear in a `low_confidence_pairs` array for debugging, but must not pollute the main signal feed.

6. **No credentials required for v1.** All Polymarket and Kalshi data used is public-read. Do not require API keys from users for the scan-all mode.

7. **Apify output contract.** Results go to `Actor.pushData()` as a flat array of opportunity objects. The summary object goes to the default key-value store as `OUTPUT_SUMMARY`. Do not change these output targets.

---

## Venue API Reference

### Polymarket

Base URL: `https://gamma-api.polymarket.com`

Key endpoints:
- `GET /markets?closed=false&limit=500` — fetch open markets
- `GET /markets/{condition_id}` — single market detail
- `GET /clob/orderbook/{token_id}` — order book (YES token)

Market object shape (relevant fields):
```json
{
  "conditionId": "0xabc...",
  "question": "Will the Fed cut rates at the June 2025 FOMC meeting?",
  "endDate": "2025-06-18T00:00:00Z",
  "active": true,
  "outcomePrices": ["0.56", "0.44"],
  "outcomes": ["Yes", "No"],
  "volume": 1240500,
  "liquidity": 87300
}
```

Order book shape:
```json
{
  "bids": [{"price": "0.55", "size": "4500"}, ...],
  "asks": [{"price": "0.57", "size": "2100"}, ...]
}
```

Fees: ~2% taker on CLOB trades. Use `FEE_POLYMARKET = 0.02` in `fees.py`.

Rate limits: generous for reads. No auth needed for public data.

### Kalshi

Base URL: `https://api.elections.kalshi.com/trade-api/v2`

(The legacy `trading-api.kalshi.com` host now requires authentication. The elections-domain mirror serves the same `/trade-api/v2` schema for public-read endpoints.)

Key endpoints:
- `GET /markets?status=open&limit=200` — open markets (paginated)
- `GET /markets/{ticker}` — single market
- `GET /markets/{ticker}/orderbook?depth=10` — order book

Market object shape (relevant fields):
```json
{
  "ticker": "FED-25JUN-T5.25",
  "title": "Fed funds rate above 5.25% after June 2025 meeting?",
  "close_time": "2025-06-18T18:00:00Z",
  "yes_bid": 44,
  "yes_ask": 46,
  "no_bid": 54,
  "no_ask": 56,
  "volume": 85000,
  "liquidity": 32000
}
```

Prices are in cents (0–100). Normalize to 0.0–1.0 for internal calculations.

Fees: ~7% combined maker/taker on most markets. Use `FEE_KALSHI = 0.07` in `fees.py`.

---

## Matching Logic (matcher.py)

Market matching is the hardest part. Use this approach in order:

1. **Category pre-filter** — Polymarket and Kalshi both expose categories. Pre-group by category to reduce the N×M matching space.

2. **Date window filter** — Only compare markets where `abs(end_date_A - end_date_B) <= 3 days`.

3. **Title similarity** — Use `rapidfuzz.fuzz.token_sort_ratio(title_A, title_B)`. Threshold: ≥ 75 to proceed to step 4.

4. **Semantic confirmation** — Strip stopwords, numbers, and dates from both titles. Check that the core entity set overlaps (e.g., both mention "Fed", "rate", "June"). Boost match confidence if overlap ≥ 80%.

5. **Binary structure check** — Both markets must be binary (YES/NO). Multi-outcome markets are excluded in v1.

Final `match_confidence` = weighted average:
- title similarity score: 50%
- date proximity (max score if same day, 0 if > 3 days): 30%
- entity overlap: 20%

---

## Scorer Logic (scorer.py)

`signal_score` (0–100) = weighted composite:

| Factor | Weight | Description |
|--------|--------|-------------|
| net_spread_pct | 40% | Normalized: 0% spread = 0 pts, 5%+ = 40 pts |
| liquidity_depth fillable at test amount | 25% | 25 pts if fillable, 0 if not |
| match_confidence | 20% | Pass through directly (0–100 → scaled) |
| days_to_resolution | 15% | 0–30 days = full points; 31–90 = half; 90+ = 0 |

`signal_label` mapping:
- score ≥ 80: `"Pure arbitrage"` (net_spread > 0 required too)
- score 60–79: `"Strong EV+ signal"`
- score 40–59: `"EV+ with edge"`
- score < 40: `"Marginal"` (excluded by default unless `min_signal_score` override)

---

## Input Schema (input_schema.json)

```json
{
  "title": "Prediction Market Arbitrage Scanner",
  "type": "object",
  "schemaVersion": 1,
  "properties": {
    "mode": {
      "title": "Scan Mode",
      "type": "string",
      "enum": ["scan-all", "categories"],
      "default": "scan-all",
      "description": "scan-all scans all open markets. categories uses the categories filter."
    },
    "categories": {
      "title": "Categories",
      "type": "array",
      "items": { "type": "string" },
      "default": [],
      "description": "Filter by category (e.g. politics, economics, sports, crypto). Leave empty for all."
    },
    "min_net_spread_pct": {
      "title": "Minimum Net Spread %",
      "type": "number",
      "default": -3.0,
      "description": "Set to 0 for pure arbitrage only. Negative values include EV+ opportunities below breakeven gross."
    },
    "min_signal_score": {
      "title": "Minimum Signal Score",
      "type": "integer",
      "default": 50,
      "minimum": 0,
      "maximum": 100
    },
    "min_liquidity_usd": {
      "title": "Minimum Liquidity (USD)",
      "type": "integer",
      "default": 1000,
      "description": "Exclude markets with total liquidity below this threshold."
    },
    "liquidity_test_amount_usd": {
      "title": "Liquidity Test Size (USD)",
      "type": "integer",
      "default": 500,
      "description": "Simulated position size for depth test. Sets the fillable threshold."
    },
    "max_days_to_resolution": {
      "title": "Max Days to Resolution",
      "type": "integer",
      "default": 90
    },
    "include_manifold": {
      "title": "Include Manifold Markets",
      "type": "boolean",
      "default": false,
      "description": "Manifold uses play money. Useful for calibration signal research, not live trading."
    },
    "output_limit": {
      "title": "Max Opportunities in Output",
      "type": "integer",
      "default": 50,
      "maximum": 200
    }
  }
}
```

---

## Output Schema (models.py)

All Pydantic models. Do not change field names without updating the README output sample.

```python
class LiquidityDepth(BaseModel):
    tested_usd: int
    fillable: Optional[bool]  # None if order book unavailable
    price_impact_pct: Optional[float]

class VenuePosition(BaseModel):
    name: str  # "polymarket" | "kalshi" | "manifold" | "myriad"
    market_url: str
    side: str  # "YES" | "NO"
    price_cents: int  # 0–100
    liquidity_usd: int

class Opportunity(BaseModel):
    id: str  # slug derived from event + venue pair
    event_title: str
    resolution_date: str  # ISO date
    venue_a: VenuePosition
    venue_b: VenuePosition
    gross_spread_pct: float
    fees_pct: float
    net_spread_pct: float
    liquidity_depth: LiquidityDepth
    match_confidence: int  # 0–100
    signal_score: int  # 0–100
    signal_label: str
    notes: Optional[str]

class ScanSummary(BaseModel):
    scanned_at: str
    total_pairs_scanned: int
    pure_arb_count: int
    ev_positive_count: int
    avg_net_spread_pct: float
    best_opportunity_id: Optional[str]
```

---

## Error Handling Rules

- **Venue timeout (>10s):** Skip that venue for current run, log warning, continue with available venues. Do not crash.
- **Order book unavailable:** Set `fillable: null`, add note to opportunity. Do not exclude from output.
- **Zero matches found:** Push empty array to dataset. Push summary with all zeroes. Do not error.
- **Rate limit hit:** Exponential backoff × 3 attempts, then skip venue with warning.
- **Malformed market data:** Log and skip that market. Never let one bad market crash the scan.

---

## Known API Quirks

Discovered via live scan probing (2026-04). These are non-obvious and not in either venue's public docs.

### Polymarket Gamma API

- **`outcomes` and `outcomePrices` are JSON-encoded strings, not arrays.**
  Live API returns `'["Yes", "No"]'` and `'["0.56", "0.44"]'` as strings. Calling code must `json.loads()` before iterating, or `is_binary` check silently fails for every market.
  Handled by `_maybe_json_list()` helper in `src/venues/polymarket.py`.

### Kalshi v2 (April 2026 schema)

- **Legacy host `trading-api.kalshi.com` requires auth.**
  Use `https://api.elections.kalshi.com/trade-api/v2` for public reads. Same v2 schema, no API key needed.

- **Field renames + unit changes:**
  | Legacy | Current | Notes |
  |---|---|---|
  | `yes_ask` (cents 0–100, int) | `yes_ask_dollars` (0–1, string) | Both still served — prefer `_dollars` |
  | `no_ask` | `no_ask_dollars` | Same |
  | `liquidity` | `liquidity_dollars` | Often `'0.0000'` even on active markets — see below |
  | `volume` | `volume_fp` | |
  | — | `open_interest_fp` | New — positions outstanding |
  | — | `market_type` | `"binary"` for YES/NO markets |

- **Default markets endpoint returns dead long-tail markets.**
  Without a server-side filter, the first 200 results from `/markets?status=open` have zero liquidity (multi-year-out markets nobody trades). Pass `max_close_ts = int(time.time()) + max_days * 86400` as a query param to get tradeable markets. Without this filter: ~0 usable markets. With it: ~50+.

- **`liquidity_dollars` is unreliable as a liquidity signal.**
  Frequently `'0.0000'` on actively traded markets. Use a fallback chain: `liquidity_dollars` → `open_interest_fp` → `volume_fp` → legacy `liquidity`. Otherwise the `min_liquidity_usd` filter excludes every Kalshi market.

### Cross-venue matching

- **Polymarket and Kalshi title structures diverge sharply.**
  Polymarket favors short questions ("Will the Lakers win the 2026 NBA Finals?"), Kalshi favors structured tickers + clauses ("NBA Finals winner — Los Angeles Lakers"). `token_sort_ratio` on raw titles often scores 50–60 on the same event. The v1 matcher's threshold of 75 will rarely fire for live data — entity-overlap step doing more lifting than title similarity. Tune in v2.

---

## Testing

Run tests before every push:
```bash
pytest tests/ -v
```

Use `tests/fixtures/` for mock venue responses — never hit live APIs in tests.

Fixture files:
- `polymarket_markets.json` — 20 sample open markets
- `kalshi_markets.json` — 20 sample open markets  
- `polymarket_orderbook.json` — sample order book
- `kalshi_orderbook.json` — sample order book

---

## README Template (for Apify Store listing)

Opening line: "No noise, just alpha. Cross-venue prediction market arbitrage signal engine."

Sections: What It Does / Who It's For / Input Parameters (table) / Output Schema (JSON sample) / How to Run / API Usage / Disclaimer

Disclaimer (required): "This tool is for informational and analytical purposes only. Prediction market trading involves financial risk. Always validate signals independently before trading."

---

## Deployment

```bash
apify push
```

Actor runs on Apify default Python runtime. Memory: 512 MB sufficient for v1 (no browser automation). Estimated run time: 60–120 seconds for scan-all mode.
