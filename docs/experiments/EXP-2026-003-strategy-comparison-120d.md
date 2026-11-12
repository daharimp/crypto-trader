# EXP-2026-003: Strategy comparison on real Kraken data (120 days), with a random control

- **Date run:** 2026-11-03. **Approved by:** owner (all four next steps).
- **Status:** completed (short-history version; the full-history rerun is pending Kraken's
  downloadable data). **Verdict:** no strategy shows an edge. Mean reversion lost least in
  the falling window. Limit orders cut fees by about a third.

## Setup

- Same real Kraken data as [EXP-2026-002](EXP-2026-002-kraken-120d.md): 4h candles
  2026-07-05 to 2026-11-02 for BTC, ETH, SOL, XRP, SUI; daily candles for eligibility.
- Evaluation 2026-07-15 to 2026-11-02, split into **3 consecutive windows of about 36 days**.
- Strategies (strategy-spec §4, fixed parameters): `sma_trend`, `tsmom` (7-day momentum),
  `mean_reversion` (RSI 14 < 30 and close below the lower Bollinger band), and
  `volatility_breakout` (20-bar high and 10-bar low channels).
- Costs:
  - `base`: market orders, 0.40% fee, 10 bps slippage.
  - `base_maker`: post-only limit orders 5 bps from the last close at a 0.25% maker fee,
    with a pessimistic fill model. Stops stay market orders.
- **Random control:** 10 seeds per window and cost. Each seed is matched to `sma_trend`'s
  trade frequency and holding time in that window, so "beats random" measures timing skill.
- Owner-approved risk settings throughout; capital $2,500 (percentages are identical at $250,
  as EXP-2026-002 showed).
- Reproduce: `trader research compare` (command in the appendix). Raw results:
  [`EXP-2026-003-compare.json`](EXP-2026-003-compare.json).

## Results per window

| Window | Hold all 5 | sma_trend | tsmom | mean_reversion | volatility_breakout | Random (median, range) |
|---|---|---|---|---|---|---|
| 1: Jul 15–Aug 20 (rising), market | +10.0% | +5.2% | −1.2% | +1.1% | +5.3% | −0.7% (−2.7 to +6.3) |
| 1, limit | | +3.7% | +4.7% | +1.0% | +6.1% | −0.0% (−2.5 to +6.7) |
| 2: Aug 20–Sep 26 (rising fast), market | +31.5% | −0.8% | +1.3% | +0.2% | +0.7% | −1.2% (−4.8 to +2.2) |
| 2, limit | | +0.6% | +4.1% | +0.0% | +2.4% | −0.4% (−2.7 to +1.6) |
| 3: Sep 26–Nov 2 (falling), market | −19.5% | −7.1% | −11.2% | −1.6% | −9.7% | −2.2% (−3.9 to −0.3) |
| 3, limit | | −6.3% | −9.2% | −0.5% | −8.2% | −1.7% (−2.8 to +0.4) |

## Summary across windows

| Strategy | Costs | Median return | Beat hold-all | Beat random | Worst drawdown | Trades | Fees |
|---|---|---|---|---|---|---|---|
| mean_reversion | market | +0.2% | 1 of 3 | 77% | 3.4% | 22 | $81.97 |
| mean_reversion | limit | +0.0% | 1 of 3 | 80% | 3.3% | 18 | $47.19 |
| sma_trend | market | −0.8% | 1 of 3 | 50% | 7.5% | 29 | $108.39 |
| sma_trend | limit | +0.6% | 1 of 3 | 60% | 6.8% | 25 | $73.39 |
| tsmom | market | −1.2% | 1 of 3 | 37% | 11.4% | 98 | $335.60 |
| tsmom | limit | +4.1% | 1 of 3 | 63% | 9.4% | 87 | $220.99 |
| volatility_breakout | market | +0.7% | 1 of 3 | 57% | 9.7% | 43 | $159.74 |
| volatility_breakout | limit | +2.4% | 1 of 3 | 63% | 8.2% | 37 | $103.42 |

"Beat hold-all 1 of 3" is the falling window in every case: no strategy beat simply holding
in either rising window.

## Findings

1. **No edge.** In rising markets, holding beat every strategy by a wide margin. In the
   falling window, every strategy lost money.
2. **Trend strategies did worse than random in the decline.** `sma_trend`, `tsmom`, and
   `volatility_breakout` lost 6–11% in window 3, while matched random entries lost about
   2%: they kept buying breakouts that failed. Overall, `sma_trend` beat only 50–60% of
   random runs, which is what luck would produce.
3. **Mean reversion was the most defensive.** It had the smallest losses in the decline
   (−0.5% to −1.6%), the lowest drawdown (3.4%), and beat about 78% of random runs. But it
   earned almost nothing in rising markets, because it trades rarely and is mostly in cash.
4. **Limit orders cut fees by 32–44%** and improved the result in 9 of 12 strategy and
   window cells, even with a pessimistic fill model (44 limit orders did not fill). The
   saving is real enough to be worth building for live trading.
5. **Sample size.** Three 36-day windows and a few dozen trades per strategy cannot separate
   skill from luck. Random seeds alone spread from −4.8% to +6.7% within one window.

## Recommendations (for the owner to approve or deny)

1. **Do not go live with any of these strategies yet.** Keep paper running for operations.
2. **Rerun this on Kraken's full downloadable history** (years, many windows) as soon as the
   files are uploaded. That is the decisive test. `trader data import-kraken` is ready.
3. **If full history confirms it, consider making `mean_reversion` the paper default**, or
   combining it with a trend filter (BL-023/BL-024: regime classifier and ensemble), since
   its weakness is idle capital in uptrends.
4. **Build limit orders for live trading** (a post-only Kraken order with fill polling and
   prompt stop placement). The simulator shows the saving; live currently refuses limits by
   design.

## Appendix: reproduction

```bash
trader research compare --profile configs/profiles/balanced-paper.yaml \
  --datasets <five 4h IDs from EXP-2026-002> --eligibility-datasets <five 1d IDs> \
  --start 2026-07-15T00:00:00Z --end 2026-11-02T20:00:00Z \
  --strategies sma_trend,tsmom,mean_reversion,volatility_breakout \
  --cost-scenarios base,base_maker --windows 3 --random-seeds 10
```
