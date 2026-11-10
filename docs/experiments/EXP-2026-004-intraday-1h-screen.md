# EXP-2026-004 (part 1): 1h strategy screen for the intraday slice

- **Date:** 2026-11-03 · **Owner request:** the 2026-11-03 revisit of UD-14 (1h quick trades,
  10% slice). The owner chose "test all, then pick" for the slice's strategy.
- **Data:** Kraken public API, 1h candles 2026-10-04..2026-11-03 for BTC, ETH, SOL, XRP, SUI
  (720 candles, the API maximum), plus daily candles for eligibility. After the 200-bar
  warm-up, decisions run 2026-10-13..2026-11-03: three 7-day windows.
- **Setup:** `trader research compare --timeframe 1h --reference mean_reversion`, profile
  `balanced-paper` ($2,500 paper capital), costs `base` (0.40% taker), `base_maker` (post-only
  limits, 0.25% maker), `stress`. Ten random-entry seeds per window and cost, matched to
  `mean_reversion`'s trade count and holding time. `volatility_breakout` is 4h-only and was
  not run.
- **Raw results:** [`EXP-2026-004-compare-1h.json`](EXP-2026-004-compare-1h.json).

## Results (base_maker, per window)

| Window | Hold all five | sma_trend | tsmom | mean_reversion | mean_reversion fees |
|---|---|---|---|---|---|
| 10-13 → 10-20 | −2.0% | −3.5% | −0.4% | **+0.7%** | $33 |
| 10-20 → 10-27 | −4.0% | −1.8% | −3.8% | −1.9% | $37 |
| 10-27 → 11-03 | −5.6% | −1.6% | −1.1% | −1.4% | $29 |

Summary across the three windows:

| Strategy | Costs | Median return | Beat holding | Beat random | Worst drawdown |
|---|---|---|---|---|---|
| mean_reversion | base_maker | −1.4% | 3 of 3 | 60% | 3.7% |
| mean_reversion | base | −2.2% | 3 of 3 | 77% | 3.9% |
| tsmom | base_maker | −1.1% | 3 of 3 | 60% | 4.1% |
| sma_trend | base_maker | −1.8% | 2 of 3 | 23% | 3.8% |
| random control | base_maker | −1.5% | 93% | n/a | 4.2% |

## What it means

- **Nothing made money.** The market fell every week (holding lost 2–6% per week). Every
  strategy lost less than holding, mostly because it sat in cash much of the time. That is
  not an edge, and the random control shows the same pattern.
- **Fees are the main cost.** `mean_reversion` paid about 1.3% of capital in fees every week
  even with limit orders. A 1h strategy has to beat that just to break even.
- **No strategy clearly beats random timing.** The best was `mean_reversion` at taker cost,
  beating 77% of random runs. With three short windows in one falling market, that falls
  within noise.
- **The evidence is too thin to choose on.** Three weeks of one market regime cannot select
  a strategy. The decisive test needs Kraken's downloadable 1h files (`*_60.csv`), loaded
  with `trader data import-kraken`, covering rising, falling, and sideways periods.

No profitability is implied or guaranteed by any result here.
