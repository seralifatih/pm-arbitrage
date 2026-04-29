# I Built a Tool That Finds Mathematical Arbitrage on Polymarket — Here's How It Works

*Published on dev.to | Tags: python, fintech, apify, webdev*

---

Prediction markets are supposed to be efficient. They're not.

Here's a trade I found last week: the **Lebanon Parliamentary Election** had 21 candidate markets on Polymarket. Each one was a binary YES/NO bet on whether that party wins the most seats. Exactly one party will win — so the probabilities must sum to 1.0.

They summed to **0.789**.

That means you could buy one share of YES on every single candidate for $0.789 total, and guaranteed receive $1.00 when the election resolves. No forecasting required. No opinion on Lebanese politics needed. Pure arithmetic.

After fees, that's a **22.7% locked return**.

I built a tool that finds these automatically. Here's how.

---

## The Math

For any event where exactly one outcome can resolve YES — an election winner, a championship, an award — the following must hold under perfect pricing:

```
Σ P(outcome_i = YES) = 1.0
```

When the sum falls below 1.0, you buy all YES positions:

```
Cost    = Σ YES prices       (e.g. 0.789)
Payout  = $1.00              (guaranteed — exactly one resolves YES)
Gross   = (1.0 - Σ YES) / Σ YES
        = (1.0 - 0.789) / 0.789
        = 26.7%
```

Subtract fees (Polymarket charges ~2% per fill, so ~4% round-trip):

```
Net return = 26.7% - 4.0% = 22.7%
```

It also works in reverse. When Σ YES > 1.0, you buy NO on every outcome:

```
Cost    = N - Σ YES          (sum of NO prices)
Payout  = N - 1              (every NO resolves YES except one)
Gross   = (Σ YES - 1.0) / (N - Σ YES)
```

The **Eurovision 2026 Top 5** is a live example of this: 35 countries, Σ YES = 9.58 when it should equal 5.0. Buying NO on every country pays out 30 countries × $1 = $30, costing $25.42 — a 14% net return.

---

## Why These Mispricings Exist

Three reasons:

**1. Market fragmentation.** Each candidate is a separate binary market. Market makers price each one independently. Small errors compound across 20+ markets and the aggregated sum drifts from 1.0 without anyone noticing.

**2. Thin liquidity.** Many of these markets have $5K–$50K of liquidity per leg, not millions. Arbitrageurs with serious capital move on, and the mispricing persists for smaller traders.

**3. Unlisted-candidate risk.** For winner-take-all events, part of the Σ YES shortfall is rational: traders implicitly price in "someone not listed here wins." That's real risk, not pure arb. The tool flags this in the output so you can judge it yourself.

---

## What the Tool Does

**[Polymarket Multi-Outcome Arbitrage Scanner](https://apify.com/seralifatih/pm-arbitrage)** is an Apify Actor (a cloud-hosted script) that:

1. Fetches every open Polymarket event via the Gamma API
2. **Classifies each event's structure** — winner-take-all (Σ = 1.0), top-K (Σ = K), or neither
3. Filters out events that look like arb but aren't: cumulative "by date" events, price ladders, independent prop bets
4. Computes fee-adjusted basket returns for qualifying events
5. Walks the CLOB order book for each leg and verifies fillability at your target position size
6. Scores each opportunity 0–100 and returns structured JSON

The classifier step is the most important. Without it, the tool surfaces thousands of false positives — events like "Will Solana reach $110 / $100 / dip to $70 this month?" look like massive arb (Σ YES ≈ 0.05 → 1900% return) but the outcomes are independent, not mutually exclusive. All three can resolve YES.

---

## The Classifier

Three structures pass the filter:

**WINNER_TAKE_ALL** — exactly one outcome resolves YES. Detected by keywords: `nominee`, `nomination`, `winner`, `wins the [year]`, `championship`, `next president/CEO/Pope`.

**TOP_K** — exactly K outcomes resolve YES. Detected by: `Top N` in the title, or `reach the final` / `advance to final` (K=2 implied by a two-slot final).

Everything else is rejected. The rejection list is explicit:

- `by [month]` in labels → cumulative nested structure
- `↑` / `↓` arrows in labels → price ladder
- `O/U` in questions → independent prop bets
- `What X will Y` / `Which X will` → multi-condition, can co-resolve

Conservative by design. It's better to miss a few valid signals than to ship noise dressed as alpha.

---

## Sample Output

```json
{
  "id": "alaska-governor-election-winner-buy_yes_basket",
  "event_title": "Alaska Governor Election Winner",
  "event_url": "https://polymarket.com/event/alaska-governor-election-winner",
  "resolution_date": "2026-11-03",
  "event_type": "winner_take_all",
  "expected_sum_yes": 1.0,
  "arb_type": "buy_yes_basket",
  "leg_count": 9,
  "sum_yes_price": 0.9015,
  "deviation_from_one": -0.0985,
  "fees_pct": 4.0,
  "gross_return_pct": 10.93,
  "net_return_pct": 6.93,
  "legs": [
    {
      "outcome_label": "Tom Begich",
      "side": "YES",
      "price": 0.375,
      "liquidity_usd": 24661,
      "fillable": true
    },
    {
      "outcome_label": "Bernadette Wilson",
      "side": "YES",
      "price": 0.235,
      "liquidity_usd": 14765,
      "fillable": true
    }
  ],
  "liquidity": {
    "tested_usd_per_leg": 100,
    "all_legs_fillable": true,
    "fillable_leg_count": 9,
    "total_leg_count": 9
  },
  "signal_score": 81,
  "signal_label": "Pure arbitrage"
}
```

9 candidates, all fillable at $100/leg, 6.9% net return locked in until election day November 2026.

---

## Technical Stack

The whole thing is ~600 lines of Python 3.11:

```
pm-arbitrage/
├── src/
│   ├── core/
│   │   ├── scanner.py          # orchestrates the pipeline
│   │   ├── event_classifier.py # rejects non-exclusive structures
│   │   ├── scorer.py           # 0-100 signal scoring
│   │   └── models.py           # Pydantic v2 output schema
│   └── venues/
│       └── polymarket.py       # Gamma + CLOB API adapter
```

Key technical decisions:

**Async-first, bounded concurrency.** The CLOB order book probe fans out to all legs simultaneously but through an `asyncio.Semaphore(20)` to avoid OOMing the 512MB Apify container. Early version hit OOM at 352 eligible events × 10 legs each = 3500 concurrent HTTP connections.

**Conservative classifier, not a blocklist.** Rejecting bad structures is whitelisting-only — events must positively match a good pattern. Default is NOT_ARB. This means some edge cases get rejected, but the output is clean.

**Szymkiewicz–Simpson overlap for entity matching.** (In an earlier cross-venue matching phase, since scrapped.) Jaccard penalizes asymmetric sets; S-S handles the case where one side has more "noise" tokens than the other. Relevant if you extend this to cross-venue matching later.

---

## Results From a Live Run

From a scan on April 29, 2026 with default settings (1000 events, top-K and WTA only, min $5K event liquidity):

| Event | Type | Net Return | Legs |
|---|---|---|---|
| Lebanon Parliamentary Election | winner_take_all | 22.7% | 21 |
| Guinea-Bissau Assembly Election | winner_take_all | 11.7% | 4 |
| Alaska Governor Election | winner_take_all | 6.9% | 9 |
| MLS Cup Winner 2026 | winner_take_all | 7.8% | 25 |
| Serie A Top 4 Finish | top_k (K=4) | 81.1% | 5 |
| EPL Top 4 Finish | top_k (K=4) | 28.2% | 10 |
| Eurovision 2026 Top 5 | top_k (K=5) | 14.0% | 35 |
| 2026 Fields Medal | winner_take_all | 47.3% | 7 |

Note: the Serie A 81% return reflects the scanner computing against the expected Σ=4 baseline — it's real but assumes the 5 listed teams are the only realistic top-4 candidates. Judge accordingly.

---

## Limitations and Honest Caveats

**Implicit "Other" probability.** For winner-take-all events with many candidates, Polymarket may not list every plausible winner. The probability shortfall partially reflects unlisted-candidate risk, not pure arb. Top-K events (EPL Top 4, Eurovision Top 5) are cleaner — the outcome space is rigorously closed.

**Execution risk.** Prices move between scan and fill. Large baskets with 20+ legs require many simultaneous fills; by the time you've filled legs 1–15, legs 16–20 may have moved. The tool tests fillability at $100/leg which is conservative — if you're sizing at $1000/leg, retest.

**Liquidity depth.** The CLOB test is at `liquidity_test_amount_usd` (default $100/leg). Higher position sizes will face more slippage. The `fillable` flag is binary at the test size, not a continuous depth curve.

**This is not financial advice.** It's an arithmetic signal engine. Trade your own book.

---

## Try It

The actor is live on Apify:

👉 **[https://apify.com/seralifatih/pm-arbitrage](https://apify.com/seralifatih/pm-arbitrage)**

Run it with these settings to start:

```json
{
  "min_net_return_pct": 0,
  "min_signal_score": 60,
  "min_event_liquidity_usd": 10000,
  "liquidity_test_amount_usd": 100,
  "max_days_to_resolution": 365,
  "max_events_to_scan": 1000,
  "output_limit": 25
}
```

`min_net_return_pct: 0` filters to pure arbitrage only — positions where you profit even after fees regardless of outcome. `min_signal_score: 60` cuts marginal low-liquidity results.

Source code: [github.com/seralifatih/pm-arbitrage](https://github.com/seralifatih/pm-arbitrage)

---

## What's Next

The obvious extension is adding more venues. Kalshi has the same multi-outcome structure on US elections and sports. Cross-venue arb (same event, different prices on Polymarket vs Kalshi) is the gold standard but requires a much better title-matching system than raw string similarity — I built one using entity extraction + Szymkiewicz-Simpson and it still struggles on the short, diverse titles both venues use.

The more tractable extension is **real-time alerting** — running the scanner on a 5-minute schedule and pushing Telegram/Discord notifications only when new high-score opportunities appear. If you want to build on top of this via the Apify API, all the pieces are there.

---

*Questions? Leave a comment or find me on Twitter. If you spot a false positive or a missed arb structure, open an issue on GitHub — the classifier is the hardest part to get right and more eyes help.*
