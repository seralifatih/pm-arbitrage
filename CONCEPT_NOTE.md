# Prediction Market Arbitrage Scanner — Concept Note
**Nokta Studio / Apify Actor**
**Actor slug:** `seralifatih/pm-arbitrage`
**Status:** Pre-build planning

---

## What It Does

A production-grade signal engine that scans the same real-world event across multiple prediction market venues — Polymarket, Kalshi, Manifold, and Myriad — and surfaces cross-venue arbitrage opportunities with liquidity-tested profitability, net-fees spread, and a confidence score.

**Core output:** Developer-ready JSON. No dashboards. No UI. Clean, structured, decision-ready data.

---

## The Problem It Solves

Prediction markets price the same event (e.g., "Will the Fed cut rates in June?") across multiple venues simultaneously. Because each venue has its own liquidity pool, user base, and market-maker incentives, prices diverge. When YES on Venue A + NO on Venue B sums to less than $1.00 — or within a configurable edge threshold above $1.00 — a risk-free or positive-expected-value opportunity exists.

The problem: this data is **fragmented**. Unified APIs like FinFeedAPI, Dome, and PolyRouter provide raw data but no signal logic. Nobody packages the *output* as a cheap, schedulable Apify actor with confidence scoring and liquidity depth validation.

---

## Target Users

- **Quant traders / prediction market participants** — individuals running systematic PM strategies who want signal without building infra
- **AI agent developers** — teams building LLM agents that interact with prediction markets (Apify MCP compatibility is a bonus)
- **Data journalists / researchers** — tracking cross-market belief divergence during elections, macro events, sports

---

## Venues Covered (v1)

| Venue | Type | Data Access | Notes |
|-------|------|-------------|-------|
| Polymarket | Crypto / Polygon | Public REST + CLOB API | Largest volume; no auth for reads |
| Kalshi | CFTC-regulated | REST API (public market data) | US-regulated; no auth for market reads |
| Manifold | Play money | Public REST | Free, no auth; useful for calibration signal |
| Myriad | Crypto | REST | Smaller; adds coverage |

Auth is only required for trading (not in scope for v1). All data ingestion is public-read.

---

## Signal Logic

### Step 1 — Market Matching
Fuzzy-match open markets across venues using:
- Event title similarity (TF-IDF / Levenshtein)
- Resolution date overlap (within ±3 days)
- Binary YES/NO structure check

Output: matched market pairs with confidence score (0–100).

### Step 2 — Spread Calculation
For each matched pair:

```
YES_price_A + NO_price_B = total_cost
spread_pct = (1.00 - total_cost) / total_cost * 100
```

Positive spread = guaranteed arb.
Negative spread (up to configurable threshold, e.g. -2%) = EV+ opportunity if liquidity holds.

### Step 3 — Liquidity Depth Test
Simulate a $100, $500, and $1000 order on each side using the public order book.
Flag if the market can absorb the simulated position without moving price > 0.5%.

### Step 4 — Fee Normalization
Each venue charges differently:
- Polymarket: ~2% taker fee on CLOBs
- Kalshi: ~7% maker/taker on most markets
- Manifold: no fees (play money)

Net spread = gross spread − (fee_A + fee_B)

### Step 5 — Confidence Score
Composite score (0–100) weighting:
- Match quality (title + date similarity)
- Net spread size
- Liquidity depth at $500 level
- Time to resolution (closer = higher risk of info asymmetry)
- Historical resolution dispute rate for that market type

---

## Output Schema (JSON)

```json
{
  "scanned_at": "2025-04-21T14:30:00Z",
  "total_pairs_scanned": 847,
  "opportunities": [
    {
      "id": "fed-rate-cut-june-2025-poly-kalshi",
      "event_title": "Will the Fed cut rates at the June 2025 FOMC meeting?",
      "resolution_date": "2025-06-18",
      "venue_a": {
        "name": "polymarket",
        "market_url": "https://polymarket.com/event/...",
        "side": "YES",
        "price_cents": 56,
        "liquidity_usd": 124500
      },
      "venue_b": {
        "name": "kalshi",
        "market_url": "https://kalshi.com/markets/...",
        "side": "NO",
        "price_cents": 41,
        "liquidity_usd": 38200
      },
      "gross_spread_pct": 2.94,
      "fees_pct": 4.5,
      "net_spread_pct": -1.56,
      "liquidity_depth": {
        "tested_usd": 500,
        "fillable": true,
        "price_impact_pct": 0.3
      },
      "match_confidence": 91,
      "signal_score": 74,
      "signal_label": "EV+ with edge",
      "notes": "Net negative spread but within configurable EV+ threshold. Kalshi fee drag is the main cost."
    }
  ],
  "summary": {
    "pure_arb_count": 2,
    "ev_positive_count": 14,
    "avg_net_spread_pct": 1.2,
    "best_opportunity_id": "..."
  }
}
```

---

## Input Parameters

```json
{
  "mode": "scan-all",
  "min_net_spread_pct": -3.0,
  "min_signal_score": 50,
  "min_liquidity_usd": 1000,
  "liquidity_test_amount_usd": 500,
  "include_manifold": false,
  "max_days_to_resolution": 90,
  "categories": ["politics", "economics", "crypto", "sports"],
  "output_limit": 50
}
```

---

## Monetization

| Plan | Price | Limits |
|------|-------|--------|
| Pay-per-use | Apify compute only | Manual runs only |
| Monthly | $34.99/mo + usage | Scheduled runs, webhooks |
| Pro | $59.99/mo + usage | Priority queue, raw order book output, email alerts |

Pricing mirrors `seralifatih/arbitrage` ($34.99) with a Pro tier added due to higher commercial value.

---

## Competitive Positioning

| Tool | What it does | Gap |
|------|-------------|-----|
| Oddpool | Dashboard + institutional data | Not on Apify, no developer JSON, expensive |
| FinFeedAPI | Unified raw market data | No signal logic, no arb detection |
| Dome / PolyRouter | Normalized data API | No scoring, no liquidity depth |
| Predly | AI mispricing detection | Black-box, not on Apify, no arb pairs |
| **This actor** | Signal engine: matched pairs + net spread + liquidity + confidence | Only one on Apify. Dev-friendly JSON. Modular. |

---

## Technical Stack

- **Language:** Python 3.11 (consistent with `cex-funding-rate-arbitrage`)
- **HTTP:** `httpx` with async for parallel venue requests
- **Matching:** `rapidfuzz` for title similarity
- **Order book:** Polymarket CLOB REST, Kalshi `/markets/{id}/orderbook`
- **Apify SDK:** `apify-client` for input/output, dataset storage
- **Config:** JSON input schema with Apify UI auto-generation

---

## Reuse from Existing Actors

The modular adapter pattern from `cex-funding-rate-arbitrage` maps directly:

```
exchanges/          →     venues/
  binance.py              polymarket.py
  bybit.py                kalshi.py
  okx.py                  manifold.py
core/                     core/
  scanner.py              scanner.py   (swap crypto pairs → event pairs)
  scorer.py               scorer.py    (add match confidence + signal label)
  models.py               models.py
```

Estimate: 60–70% of the scaffold is reusable. The new work is:
1. Fuzzy market matching logic
2. Fee table for each venue
3. Resolution date alignment
4. Output schema for event-style contracts (vs. spot price pairs)

---

## v1 Scope (Launch)

- [x] Polymarket + Kalshi only (biggest volume)
- [x] Scan-all mode
- [x] Gross + net spread calculation
- [x] Liquidity depth test ($100 / $500 / $1000)
- [x] Signal score (0–100)
- [x] JSON + CSV output
- [x] Apify scheduled run support

## v2 Roadmap

- [ ] Manifold + Myriad adapters
- [ ] WebSocket / streaming mode
- [ ] Webhook alert on signal_score > threshold
- [ ] Historical spread tracking (trend: widening or narrowing?)
- [ ] Category filter (politics only, sports only)
- [ ] Sportsbook ↔ PM mispricing mode (separate actor or Pro add-on)
