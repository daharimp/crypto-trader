# ADR-043: Paper spot trades the 50/200 trend stance and says why it is idle

- Status: accepted (owner, 2026-11-22, project thread "Get the spot bot trading")
- Context: the paper spot session ran `sma_trend` 20/50, which buys only on the one 4h bar
  where SMA20 crosses above SMA50. From 2026-11-15 no coin crossed, so the session made no
  trades and the dashboard gave no reason.

## Evidence (EXP-2026-018, research/run_exp018.py)

Portfolio replay on 3 years of Coinbase 1h candles built into 4h bars for BTC, ETH, SOL, XRP
and SUI, with the approved risk rules (1% risk, 2 x ATR stop on every entry, tier caps, 80%
exposure, 15% breaker, 3% daily stop, cooldown) and 50 bps per side. Last 180 days held out.

| rule | dev return / DD | holdout return / DD / PF |
|---|---|---|
| sma_trend 20/50 cross (current) | +17.8% / 26.9% | +2.5% / 12.3% / 1.11 |
| SMA 50/200 stance | +36.1% / 30.9% | +5.5% / 7.6% / 1.53 |
| mean reversion in downtrends (several variants) | -9% to -55% | -11% to -15% |
| 1h bars (either trend rule) | -44% to -79% | -13% to -35% |

The 50/200 stance also led EXP-2026-010. Mean-reversion "downtrend modes" traded more but
lost in every long window, so they were rejected.

## Decision

- New strategy `sma_stance` 1.0.0 (`configs/strategies/sma_stance.yaml`, 4h only): BUY on
  any bar while SMA50 > SMA200, SELL while below. Spot stays long only (CLAUDE.md), so in a
  downtrend it holds cash. Shorts belong to the paper perps package and are designed in the
  separate long/short work (EXP-2026-019 has the short-side replay).
- New feature `sma_200` in features-m2 (additive; existing values are unchanged, the
  definitions hash changes). The 200-bar feature window already covers it.
- The paper service runs `--strategy ${TRADER_PAPER_STRATEGY:-sma_stance}`. The live service
  keeps the profile default (`sma_trend`) until paper results justify switching it.
- Every cycle the session writes one plain-English line per coin (`watch` in the state file):
  trend and distance between the averages, holding, data late, or which risk rule blocked a
  signal. The dashboard shows it on the Spot account. Strategies may define
  `watch(features, holding)`; others get a generic line. Display only.
- Stops are unchanged: the risk engine attaches the approved 2 x ATR hard stop to every entry
  (UD-16). Trailing stops are separate work and apply on top.

## Consequences

- Expected about 5-7 trades a month across five coins in trending markets (backtest), still
  none while every coin is below its 200-bar average.
- Development drawdown with breaker resets was 31%, above the 15% go-live bar: this is a
  paper change, not a live recommendation.
