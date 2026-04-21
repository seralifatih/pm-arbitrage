# 🎯 Prediction Market Arbitrage Scanner

> **No noise, just alpha.** Cross-venue prediction market arbitrage signal engine.

[![Run on Apify](https://apify.com/actor-badge?actor=seralifatih/pm-arbitrage)](https://apify.com/seralifatih/pm-arbitrage)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-grade signal engine that scans the same real-world event across **Polymarket** and **Kalshi**, fuzzy-matches markets covering the same outcome, calculates net spread after fees, tests order book liquidity, and returns a confidence-scored JSON signal feed. No raw data dumps — only actionable opportunities.

---

## ✨ Key Features

- **Cross-venue matching** — fuzzy title + entity overlap + date-window matching across Polymarket and Kalshi
- **Fee-aware net spread** — every opportunity reports `gross_spread_pct`, `fees_pct`, and `net_spread_pct` (Polymarket 2%, Kalshi 7%)
- **Real liquidity tests** — walks live order books at a configurable test size; flags `fillable: true/false/null` per opportunity
- **Confidence-scored signals** — every result tagged with a 0–100 `signal_score` and label (`Pure arbitrage`, `Strong EV+ signal`, `EV+ with edge`, `Marginal`)
- **Async-first pipeline** — concurrent venue fetches and order-book probes; full scan in 60–120s
- **Public-read only** — no API keys required; runs out of the box on Apify free tier
- **Modular venue adapters** — adding Manifold, Myriad, or any new venue = one file

---

## 📊 Sample Output

Each item in the dataset is a fully-decorated opportunity:

```json
{
  "id": "fed-rate-cut-june-2025-polymarket-kalshi",
  "event_title": "Will the Fed cut rates at the June 2025 FOMC meeting?",
  "resolution_date": "2025-06-18",
  "venue_a": {
    "name": "polymarket",
    "market_url": "https://polymarket.com/event/fed-rate-cut-june-2025",
    "side": "YES",
    "price_cents": 56,
    "liquidity_usd": 124500
  },
  "venue_b": {
    "name": "kalshi",
    "market_url": "https://kalshi.com/markets/FED-25JUN-T5.25",
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
  "notes": null
}
```

A `ScanSummary` record is also written to the default key-value store under the key `OUTPUT_SUMMARY`:

```json
{
  "scanned_at": "2026-04-21T14:30:00Z",
  "total_pairs_scanned": 847,
  "pure_arb_count": 2,
  "ev_positive_count": 14,
  "avg_net_spread_pct": 1.2,
  "best_opportunity_id": "fed-rate-cut-june-2025-polymarket-kalshi"
}
```

### Signal labels

| Label | Score | Meaning |
|-------|-------|---------|
| `Pure arbitrage` | ≥ 80 + net spread > 0 | Risk-free spread after fees |
| `Strong EV+ signal` | 60–79 | High-conviction edge |
| `EV+ with edge` | 40–59 | Mild edge — position sizing matters |
| `Marginal` | < 40 | Excluded by default |

---

## 🛠 Supported Venues

| Venue | API | Auth | Fee | Status |
|-------|-----|------|-----|--------|
| **Polymarket** | Gamma + CLOB | Public read | 2% taker | ✅ Live |
| **Kalshi** | Elections v2 | Public read | 7% combined | ✅ Live |
| **Manifold** | — | — | 0% (play money) | 🚧 v2 |
| **Myriad** | — | — | ~2% | 🚧 v2 |

---

## 🚀 How to Use

### Method 1: No-Code (Apify Console)

1. Open the actor on [Apify](https://apify.com/seralifatih/pm-arbitrage)
2. Adjust `min_signal_score` and `min_net_spread_pct` for your strategy
3. Click **Start** — results land in the dataset; summary lands in `OUTPUT_SUMMARY`

### Method 2: API Integration (For Developers)

Trigger a run:

```bash
curl -X POST "https://api.apify.com/v2/acts/seralifatih~pm-arbitrage/runs?token=YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "scan-all",
    "min_net_spread_pct": 0,
    "min_signal_score": 70,
    "min_liquidity_usd": 5000,
    "output_limit": 25
  }'
```

Fetch results:

```bash
curl "https://api.apify.com/v2/datasets/DATASET_ID/items?token=YOUR_API_TOKEN&format=json"
```

### Scheduled runs

Schedule the actor every 5–15 minutes during high-volatility windows (FOMC days, election nights, championship games) for fresh signal.

---

## ⚙️ Input Configuration

```json
{
  "mode": "scan-all",
  "categories": [],
  "min_net_spread_pct": -3.0,
  "min_signal_score": 50,
  "min_liquidity_usd": 1000,
  "liquidity_test_amount_usd": 500,
  "max_days_to_resolution": 90,
  "include_manifold": false,
  "output_limit": 50
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"scan-all"` | `scan-all` scans all open markets. `categories` filters by category list. |
| `categories` | string[] | `[]` | Filter by category (`politics`, `economics`, `sports`, `crypto`). Empty = all. |
| `min_net_spread_pct` | number | `-3.0` | Minimum net spread to report. `0` = pure arbitrage only. Negative includes EV+ below breakeven gross. |
| `min_signal_score` | integer | `50` | Minimum signal score (0–100) to include. |
| `min_liquidity_usd` | integer | `1000` | Exclude markets with total liquidity below this threshold. |
| `liquidity_test_amount_usd` | integer | `500` | Simulated position size for the depth test. Sets the `fillable` threshold. |
| `max_days_to_resolution` | integer | `90` | Skip markets resolving beyond this horizon. |
| `include_manifold` | boolean | `false` | Include Manifold (play-money) markets. Calibration research only. |
| `output_limit` | integer | `50` | Max opportunities returned (≤ 200). |

---

## 🧰 Tech Stack

- **Python 3.11** — async-first
- **httpx** — concurrent venue requests
- **rapidfuzz** — fuzzy market matching
- **pydantic v2** — strict output schema
- **Apify SDK for Python**

Estimated run time: 60–120 seconds for `scan-all` mode at 512 MB memory.

---

## ⚠️ Disclaimer

This tool is for informational and analytical purposes only. Prediction market trading involves financial risk. Spreads, liquidity, and resolution outcomes can move against you between signal and execution. Always validate signals independently before trading. Not financial advice.

---

## 🔗 You might also like

- [**Crypto Arbitrage Scanner**](https://apify.com/seralifatih/arbitrage) — CEX spot arbitrage across 8+ exchanges
- [**CEX Funding Rate Arbitrage**](https://apify.com/seralifatih/cex-funding-rate-arbitrage) — Perpetual funding rate basis trades
- Use with the arbitrage scanner to validate prediction market moves against spot crypto signal.
