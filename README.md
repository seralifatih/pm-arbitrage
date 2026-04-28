# 🎯 Polymarket Multi-Outcome Arbitrage Scanner

> **No noise, just alpha.** Concrete arithmetic arbitrage on Polymarket's multi-outcome events.

[![Run on Apify](https://apify.com/actor-badge?actor=seralifatih/pm-arbitrage)](https://apify.com/seralifatih/pm-arbitrage)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A signal engine that scans every multi-outcome Polymarket event (presidential nominations, championship winners, who-becomes-X markets) and detects when the **mutually-exclusive YES prices fail to sum to 1.0** — the mathematical fingerprint of free arbitrage. Output is decision-ready JSON with the exact basket composition, expected return after fees, and per-leg fillability.

---

## ✨ Key Features

- **Pure arithmetic arbitrage** — Σ YES across mutually-exclusive outcomes must equal 1.0. When it doesn't, you can buy or sell the basket for guaranteed profit.
- **Two arb directions** — `buy_yes_basket` (when Σ YES < 1.0) and `buy_no_basket` (when Σ YES > 1.0). The scanner picks the profitable side.
- **Fee-adjusted returns** — every opportunity reports `gross_return_pct`, `fees_pct` (4% round-trip on Polymarket), and the headline `net_return_pct`.
- **Real per-leg liquidity tests** — walks each child market's CLOB order book at a configurable position size; flags `all_legs_fillable: true/false/null` per opportunity.
- **Confidence-scored signals** — every result tagged with a 0–100 `signal_score` and label (`Pure arbitrage`, `Strong EV+ signal`, `EV+ with edge`, `Marginal`).
- **Public-read only** — no API keys required.
- **Async-first** — concurrent event fetch + parallel order-book probes; full scan in 30–90s.

---

## 📊 Sample Output

Each opportunity is a complete basket trade with the math worked out:

```json
{
  "id": "2028-democratic-presidential-nominee-buy_yes_basket",
  "event_title": "2028 Democratic Presidential Nominee",
  "event_url": "https://polymarket.com/event/2028-democratic-presidential-nominee",
  "resolution_date": "2028-11-07",
  "arb_type": "buy_yes_basket",
  "leg_count": 12,
  "sum_yes_price": 0.9320,
  "deviation_from_one": -0.068,
  "fees_pct": 4.0,
  "gross_return_pct": 7.30,
  "net_return_pct": 3.30,
  "legs": [
    {
      "market_id": "0xabc...",
      "question": "Will Pete Buttigieg win the 2028 Democratic nomination?",
      "outcome_label": "Pete Buttigieg",
      "side": "YES",
      "price": 0.0425,
      "market_url": "https://polymarket.com/event/...",
      "liquidity_usd": 84200,
      "fillable": true
    }
  ],
  "liquidity": {
    "tested_usd_per_leg": 100,
    "all_legs_fillable": true,
    "fillable_leg_count": 12,
    "total_leg_count": 12
  },
  "signal_score": 71,
  "signal_label": "Strong EV+ signal",
  "notes": null
}
```

A `ScanSummary` is also written to the default key-value store under `OUTPUT_SUMMARY`:

```json
{
  "scanned_at": "2026-04-29T18:00:00Z",
  "total_events_scanned": 847,
  "eligible_events": 38,
  "pure_arb_count": 2,
  "ev_positive_count": 11,
  "avg_net_return_pct": 1.6,
  "best_opportunity_id": "2028-democratic-presidential-nominee-buy_yes_basket"
}
```

### Signal labels

| Label | Score | Meaning |
|-------|-------|---------|
| `Pure arbitrage` | ≥ 80 + net return > 0 | Risk-free spread after fees |
| `Strong EV+ signal` | 60–79 | High-conviction edge |
| `EV+ with edge` | 40–59 | Mild edge — position sizing matters |
| `Marginal` | < 40 | Excluded by default |

---

## 🧮 The Math

For a Polymarket event with N mutually-exclusive outcomes (e.g. "who wins the 2028 Democratic primary?"), exactly one outcome resolves YES. So under perfect pricing:

```
Σ P(outcome_i = YES) = 1.0
```

When the sum drifts away from 1.0, there's free money:

**Buy-YES-basket arb** (Σ YES < 1.0):
- Cost: Σ YES dollars to buy 1 share of every YES outcome
- Payout: $1 (one of them resolves YES)
- Gross return: `(1 - Σ YES) / Σ YES`

**Buy-NO-basket arb** (Σ YES > 1.0):
- Cost: `N - Σ YES` dollars (NO_i = 1 - YES_i)
- Payout: `N - 1` dollars (one outcome resolves NO worthless, others pay $1)
- Gross return: `(Σ YES - 1) / (N - Σ YES)`

The scanner subtracts a conservative 4% round-trip fee (Polymarket's 2% taker × open + close) to compute `net_return_pct`. Every leg is liquidity-tested at the configured position size before being marked fillable.

---

## 🚀 How to Use

### Method 1: No-Code (Apify Console)

1. Open the actor on [Apify](https://apify.com/seralifatih/pm-arbitrage)
2. Adjust `min_signal_score` and `min_net_return_pct` for your strategy
3. Click **Start** — opportunities land in the dataset, summary in `OUTPUT_SUMMARY`

### Method 2: API Integration (For Developers)

```bash
curl -X POST "https://api.apify.com/v2/acts/seralifatih~pm-arbitrage/runs?token=YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "min_net_return_pct": 0,
    "min_signal_score": 70,
    "min_event_liquidity_usd": 10000,
    "liquidity_test_amount_usd": 250,
    "output_limit": 25
  }'
```

Fetch results:

```bash
curl "https://api.apify.com/v2/datasets/DATASET_ID/items?token=YOUR_API_TOKEN&format=json"
```

### Scheduled runs

Schedule the actor every 5–15 minutes during high-volatility windows (election nights, championship games, FOMC days) to catch fresh basket mispricings before market makers correct them.

---

## ⚙️ Input Configuration

```json
{
  "min_net_return_pct": -1.0,
  "min_signal_score": 30,
  "min_event_liquidity_usd": 5000,
  "min_liquidity_per_leg_usd": 200,
  "min_legs_per_event": 3,
  "liquidity_test_amount_usd": 100,
  "max_days_to_resolution": 365,
  "max_events_to_scan": 1000,
  "output_limit": 50
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_net_return_pct` | number | `-1.0` | Minimum net return after fees. `0` = pure arbitrage only. |
| `min_signal_score` | integer | `30` | Minimum 0–100 signal score to include. |
| `min_event_liquidity_usd` | integer | `5000` | Skip events below this cumulative liquidity. |
| `min_liquidity_per_leg_usd` | integer | `200` | Each leg must have at least this liquidity (filters dead placeholders). |
| `min_legs_per_event` | integer | `3` | Skip events with fewer mutually-exclusive legs than this. |
| `liquidity_test_amount_usd` | integer | `100` | Per-leg position size for the depth test. |
| `max_days_to_resolution` | integer | `365` | Skip events resolving beyond this horizon. |
| `max_events_to_scan` | integer | `1000` | Cap on Polymarket events fetched. Higher = wider coverage, slower. |
| `output_limit` | integer | `50` | Cap on opportunities returned (≤ 200). |

---

## 🧰 Tech Stack

- **Python 3.11** — async-first
- **httpx** — concurrent Gamma + CLOB requests
- **pydantic v2** — strict output schema
- **Apify SDK for Python**

Estimated run time: 30–90 seconds for the default config at 512 MB memory.

---

## ⚠️ Disclaimer

This tool is for informational and analytical purposes only. Prediction market trading involves financial risk. The arithmetic identity (Σ YES = 1.0) holds only for **fully-specified** events — events with hidden "Other" outcomes or unlisted candidates may show false signal. Always verify the event's outcome space is complete and that all legs are fillable at your intended size before committing capital. Not financial advice.

---

## 🔗 You might also like

- [**Crypto Arbitrage Scanner**](https://apify.com/seralifatih/arbitrage) — CEX spot arbitrage across 8+ exchanges
- [**CEX Funding Rate Arbitrage**](https://apify.com/seralifatih/cex-funding-rate-arbitrage) — Perpetual funding rate basis trades
