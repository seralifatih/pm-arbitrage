# 🎯 Polymarket Multi-Outcome Arbitrage Scanner

> **No noise, just alpha.** Concrete arithmetic arbitrage on Polymarket's multi-outcome events.

[![Run on Apify](https://apify.com/actor-badge?actor=seralifatih/pm-arbitrage)](https://apify.com/seralifatih/pm-arbitrage)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A signal engine that scans every Polymarket event with mutually-exclusive outcomes — election winners, championship finishers, "who will be the X" markets — and detects when the **YES prices fail to sum to their mathematical expected value**. That's free arbitrage. Every output is a complete basket trade with the math worked out, fees subtracted, and per-leg liquidity verified against live order books.

---

## ✨ Key Features

- **Real arbitrage, not vibes** — every signal is rigorous arithmetic. Σ YES across N mutually-exclusive outcomes must equal a known constant (1.0 for winner-take-all, K for top-K). Deviations are quantifiable edge.
- **Two arb directions** — `buy_yes_basket` (when Σ YES < expected) and `buy_no_basket` (when Σ YES > expected). The scanner picks the profitable side automatically.
- **Conservative event classifier** — three structures qualify (winner-take-all, top-K) and the scanner explicitly rejects cumulative "by date" events, price ladders, and prop bets. No false signal from non-exclusive outcomes.
- **Fee-adjusted returns** — every opportunity reports `gross_return_pct`, `fees_pct` (Polymarket's 4% round-trip), and the headline `net_return_pct` you actually capture.
- **Real per-leg liquidity tests** — walks each child market's CLOB order book at a configurable position size; flags `all_legs_fillable: true/false/null` per opportunity.
- **Confidence-scored signals** — every result tagged with a 0–100 `signal_score` weighing return, fillability, leg count, and time-to-resolution.
- **Public-read only** — no API keys required. Runs on Apify free tier.
- **Async-first pipeline** — concurrent event fetch + bounded-concurrency CLOB probes; full scan in 30–90 seconds.

---

## 📊 Sample Output

Each opportunity is a complete basket trade with the math worked out:

```json
{
  "id": "lebanon-parliamentary-election-winner-buy_yes_basket",
  "event_title": "Lebanon Parliamentary Election Winner",
  "event_url": "https://polymarket.com/event/lebanon-parliamentary-election-winner",
  "resolution_date": "2026-05-31",
  "event_type": "winner_take_all",
  "expected_sum_yes": 1.0,
  "arb_type": "buy_yes_basket",
  "leg_count": 21,
  "sum_yes_price": 0.789,
  "deviation_from_one": -0.211,
  "fees_pct": 4.0,
  "gross_return_pct": 26.74,
  "net_return_pct": 22.74,
  "legs": [
    {
      "market_id": "0x7fc8...",
      "question": "Will Lebanese Forces win the most seats in the 2026 Lebanese parliamentary election?",
      "outcome_label": "Lebanese Forces (LF)",
      "side": "YES",
      "price": 0.06,
      "market_url": "https://polymarket.com/event/will-lebanese-forces-win-the-most-seats...",
      "liquidity_usd": 19892,
      "fillable": true
    }
  ],
  "liquidity": {
    "tested_usd_per_leg": 100,
    "all_legs_fillable": true,
    "fillable_leg_count": 21,
    "total_leg_count": 21
  },
  "signal_score": 85,
  "signal_label": "Pure arbitrage",
  "notes": null
}
```

A `ScanSummary` record is also written to the default key-value store under `OUTPUT_SUMMARY`:

```json
{
  "scanned_at": "2026-04-29T18:00:00Z",
  "total_events_scanned": 1000,
  "eligible_events": 38,
  "pure_arb_count": 7,
  "ev_positive_count": 11,
  "avg_net_return_pct": 18.4,
  "best_opportunity_id": "lebanon-parliamentary-election-winner-buy_yes_basket"
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

For a Polymarket event with N mutually-exclusive outcomes (e.g. "who wins the 2026 MLS Cup?", "which team finishes top 4 in Serie A?"), exactly K outcomes resolve YES. So under perfect pricing:

```
Σ P(outcome_i = YES) = K
```

- **K = 1** for winner-take-all events ("X election winner", "Y nominee", "Z championship")
- **K = N_top** for top-K events ("Top 4 EPL finish", "Reach the final" with K=2, "Eurovision Top 5")

When Σ YES drifts from K, there's a basket trade with locked-in profit:

**Buy-YES-basket arb** (Σ YES < K):
- Cost: Σ YES dollars to buy 1 share of every YES outcome
- Payout: K dollars (exactly K of them resolve YES)
- Gross return: `(K - Σ YES) / Σ YES`

**Buy-NO-basket arb** (Σ YES > K):
- Cost: `N - Σ YES` dollars (since NO_i = 1 - YES_i)
- Payout: `N - K` dollars (the legs that DON'T resolve YES)
- Gross return: `(N - K - (N - Σ YES)) / (N - Σ YES) = (Σ YES - K) / (N - Σ YES)`

The scanner subtracts a conservative 4% round-trip fee (Polymarket's 2% taker × open + close) to compute `net_return_pct`. Every leg is liquidity-tested against the live order book at the configured position size before being marked fillable.

---

## 🛡 What This Scanner Will NOT Flag

The scanner uses a conservative event classifier that rejects structures where Σ YES has no constraint. These look superficially like arb but are not — buying their baskets has no guaranteed payout.

**Rejected: cumulative "by date" events**
> "Will Drake release Iceman by April / May / June?" — releasing in April implies released by May too. Outcomes are nested, not exclusive.

**Rejected: price/threshold ladders**
> "Will Solana reach $110 / dip to $70 / reach $100 in April?" — price can hit multiple thresholds. Outcomes are independent ranges.

**Rejected: prop bets and multi-condition events**
> "Player X: Points O/U 17.5 + Rebounds O/U 4.5 + Assists O/U 3.5" — independent stat lines.
> "Will Trump publicly insult someone on April 26 / 28 / 29 / 30?" — independent daily events.
> "What demands will Trump agree to in April?" — multiple demands can co-resolve YES.

If you're seeing a Polymarket event you'd expect to be arb-eligible but it's not in the output, it likely fell into one of these categories. Check `OUTPUT_SUMMARY.eligible_events` to see how many of the day's events qualified.

---

## 🚀 How to Use

### Method 1: No-Code (Apify Console)

1. Open the actor on [Apify](https://apify.com/seralifatih/pm-arbitrage)
2. Adjust `min_signal_score` and `min_net_return_pct` for your strategy
3. Click **Start** — opportunities land in the dataset, summary in `OUTPUT_SUMMARY`

### Method 2: API Integration

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

Schedule the actor every 5–15 minutes during high-volatility windows (election nights, championship games, FOMC days, Eurovision, primary debates) to catch fresh basket mispricings before market makers correct them.

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
- **httpx** — concurrent Gamma + CLOB requests with bounded concurrency
- **pydantic v2** — strict output schema
- **Apify SDK for Python**

Estimated run time: 30–90 seconds for the default config at 512 MB memory.

---

## ⚠️ Disclaimer

This tool is for informational and analytical purposes only. Prediction market trading involves financial risk. Always validate signals independently before committing capital. Not financial advice.

**Important caveat — implicit "Other" probability:** The arithmetic identity `Σ YES = K` assumes the listed outcomes cover **all** real-world possibilities. For winner-take-all events (e.g. "Alaska Governor 2026") with many candidates, Polymarket may not list every potential winner — the missing probability mass on unlisted outcomes is what often keeps Σ YES below 1.0 even on well-priced markets. **Top-K events** (Eurovision Top 5, EPL Top 4, Serie A Top 4) are typically more reliable because the outcome space is rigorously defined: exactly K teams finish top-K, no "other" possible. **Single-winner events with >10% deviation** deserve manual verification of outcome-space completeness before trading. The scanner reports the raw mathematical signal — **you must judge whether the listed candidates exhaust the field.**

---

## 🔗 You might also like

- [**Crypto Arbitrage Scanner**](https://apify.com/seralifatih/arbitrage) — CEX spot arbitrage across 8+ exchanges
- [**CEX Funding Rate Arbitrage**](https://apify.com/seralifatih/cex-funding-rate-arbitrage) — Perpetual funding rate basis trades
