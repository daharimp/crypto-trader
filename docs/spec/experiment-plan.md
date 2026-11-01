# Experiment Plan

**Document status:** Draft for owner review
**Version:** 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Depends on:** `product-requirements.md` §3 and §10, `strategy-spec.md`, `data-architecture.md`, `risk-profile.schema.yaml`
**Used by:** `execution-plan.md`, `code-session-handoff.md`

Status labels: **APPROVED** (D-nn), **HYPOTHESIS** (H-nn), **RECOMMENDATION** (R-nn), **UNRESOLVED** (UD-nn).

---

## 1. Purpose and principles

This plan defines how strategies, risk parameters, and later models are evaluated so that results are honest, reproducible, and comparable. Principles:

1. **Measure against simple baselines** (P-08): every result is reported net of costs against cash, buy-and-hold, equal-weight, and simple trend.
2. **Time order is sacred** (v0.1 §8.1): no random splits for primary evaluation.
3. **No look-ahead** (P-07): checks LA-01 to LA-08 are mandatory.
4. **One metric or one window never decides** (v0.1 §6.11).
5. **No profitability claims** (D-07): reports describe simulated history, not forecasts.
6. **Evidence for decisions, not decisions by experiments.** Experiments produce evidence for the owner to resolve UD items and to approve promotions; they never change approved values or promote anything automatically (D-32, D-43).

## 2. Simple baselines

| ID | Baseline | Type | Stage | Purpose |
|---|---|---|---|---|
| `bm_cash` | Hold cash | Benchmark | M1 | Floor: is any risk worth taking? |
| `bm_bh_btc` | Buy-and-hold BTC | Benchmark | M1 | Market exposure baseline (D-46) |
| `bm_bh_eth` | Buy-and-hold ETH | Benchmark | M1 | Market exposure baseline (D-46) |
| `bm_ew_btc_eth` | 50/50 BTC/ETH, no rebalancing | Benchmark | M1 | Diversified passive baseline (v0.1 §8.3) |
| `sma_trend` | SMA 20/50 trend | Strategy baseline | M1 | Simple moving-average trend (v0.1 §8.3; D-46) |
| `tsmom` | Time-series momentum | Strategy baseline | V1 | Momentum family |
| `mean_reversion` | RSI and Bollinger reversion | Strategy baseline | V1 | Mean-reversion family |
| `volatility_breakout` | Donchian breakout | Strategy baseline | V1 | Breakout family |
| `random_entry` | Random timing, matched trade count and holding periods | Control | V1 | Does timing add value? |

Definitions are in `strategy-spec.md` §4.

## 3. Time-ordered train/validation/test design (RECOMMENDATION R-11)

- **Data range:** from the earliest date at which both BTC and ETH have at least one year of continuous 1h history on the chosen venue (UD-20) to the end of the last complete calendar month.
- **Sealed holdout (untouched test):** the most recent 12 months. The holdout is read only when an experiment runs with `--allow-holdout`; each access appends an entry (experiment ID, strategy family, UTC time) to `data/experiments/holdout_access.jsonl`. Each strategy family's final candidate may be evaluated on the holdout once. A second access for the same family invalidates the result (OF-11).
- **Pre-holdout period:** used for training and validation through walk-forward folds (§4).
- **Embargo:** a gap between each training window and its validation window equal to the larger of the feature warm-up and 7 days, so that overlapping windows cannot leak.
- **M1 exception:** the vertical-slice run (EXP-2026-001) is a pipeline check on a single period and is not used to judge strategies.

## 4. Walk-forward evaluation

| Element | Recommendation |
|---|---|
| Training window | Expanding, starting with the first 24 months of the pre-holdout period (minimum 12 months if history is shorter) |
| Validation window | 3 months, consecutive, out-of-sample |
| Step | 3 months |
| Parameter selection | Inside each fold, from a small grid declared before the experiment; the number of configurations tried is recorded (OF-10) |
| Fitted models (P8) | Fitted on the training window only; fitted state versioned per fold |
| Aggregation | Out-of-sample performance = concatenated validation windows; also reported per fold |
| Final check | The selected configuration is evaluated once on the sealed holdout |

Rule-based strategies with fixed parameters still run fold by fold, because fold-to-fold stability (OF-06) is itself evidence.

## 5. Look-ahead-bias checks

All are automated tests or run-time assertions. Any failure rejects the experiment result (OF-01).

| Check | Method | Stage |
|---|---|---|
| LA-01 Future perturbation | Changing any candle after time t leaves every decision at or before t unchanged (property test) | M1 (T-20) |
| LA-02 Feature causality | Every `FeatureSet` satisfies `max_input_close_time_utc <= as_of_utc` (run-time assertion) | M1 |
| LA-03 Next-bar fills | Every fill uses a bar whose open time is at or after the decision time, at a price within that bar's range | M1 (T-35) |
| LA-04 Truncation equivalence | A run on data truncated at T makes identical decisions up to T as a run on the full data | V1 |
| LA-05 Point-in-time eligibility | Eligibility at t uses only data up to t (an asset whose history starts late is ineligible until it qualifies) | M1 (T-22) |
| LA-06 Fit isolation | Fitted objects see only training-fold rows | P8 |
| LA-07 Holdout seal | Holdout rows are unreadable without `--allow-holdout`; access is logged | V1 (T-57) |
| LA-08 Target shuffle | An ML model trained on time-shuffled targets shows no out-of-sample edge | P8 |

## 6. Fees, spread, slippage, and latency assumptions (RECOMMENDATION R-10)

Until the venue and fee tier are chosen (UD-20), every evaluation runs a grid of cost scenarios. Values are per side and apply to every fill. In V1, the half-spread is folded into slippage because candle data contains no spread (R-21).

| Scenario | `fee_rate_pct` | `slippage_bps` (includes half-spread) | Execution delay | `min_notional_usd` |
|---|---|---|---|---|
| `low` | 0.10 | 5 | Fill at next bar open | 10 |
| `base` | 0.40 | 10 | Fill at next bar open | 10 |
| `stress` | 0.60 | 25 | Fill at next bar open | 10 |

- **Buy fill price** = next open × (1 + slippage_bps / 10,000). **Sell fill price** = next open × (1 − slippage_bps / 10,000). Fills are clamped to the bar's high-low range (no fills outside observable prices).
- **Stop fills:** at the stop price, or at the open if the bar gaps through the stop, minus slippage, clamped to the bar's range.
- **Fees** = fill notional × fee_rate_pct / 100, charged in USD.
- **Latency:** decisions happen at bar close; fills happen at the next bar's open. The delay-sensitivity check (RB-03) adds one or two extra bars.
- **Minimum order size:** orders below `min_notional_usd` are rejected (RR-20).
- **Pair availability:** an instrument with no data in a period cannot trade in that period (DQ-06, DQ-10).
- The `base` scenario is replaced by the actual venue fee tier for a $2,500 account once UD-20 is resolved; `stress` stays at least that conservative.
- Cost scenario files: `configs/costs/low.yaml`, `base.yaml`, `stress.yaml`.

## 7. Intraday allocation experiment matrix (EXP-2026-004; D-19, D-20; stage V1.5)

**Question:** does an isolated intraday sleeve improve the portfolio, and if so, at which cap? D-20 requires testing 5%, 10%, 15%, and 20% without assuming the largest is best. A 0% control is added so that "no sleeve" can win.

| Factor | Levels |
|---|---|
| Intraday cap (share of equity) | 0% (control), 5%, 10%, 15%, 20% |
| Intraday strategy | Each separately registered intraday candidate (none approved yet) |
| Cost scenario | `base`, `stress` (stress is the pass/fail scenario, E-I1) |
| Execution delay | Next bar open, +1 bar, +2 bars (E-I4) |
| Folds | Same walk-forward folds as the core evaluation |

Held fixed: the core portfolio configuration (current champion or best baseline), the Balanced risk profile (with experiment values for unresolved fields), and sleeve loss limits under test (UD-14 options A and B).

Metrics:

- **Portfolio:** total return, maximum drawdown, Sortino-like, Calmar, worst UTC-day loss, time under water, share of positive months.
- **Sleeve:** return on sleeve capital, closed trades, turnover, fee and slippage burden, win rate, payoff ratio.
- **Interaction:** correlation of sleeve and core daily returns; marginal change in portfolio Sortino-like; how often aggregate concentration caps bind.

Selection rule (RECOMMENDATION):

1. Exclude any cap under which any fold breaches the profile's or the sleeve's loss limits.
2. A cap "improves" the portfolio if portfolio Sortino-like and Calmar both beat the 0% control in at least two-thirds of folds under `stress` costs, and the overfit checks (§14) and E-I1 to E-I7 pass.
3. Choose the smallest improving cap. A larger cap is preferred only if it beats the smaller one by more than 10% (relative) on both ratios in at least two-thirds of folds.
4. If no cap improves, recommend keeping the sleeve disabled.
5. The owner approves the cap (UD-14); the experiment never enables the sleeve itself (D-32).

## 8. Regime-level evaluation

- Every bar is labelled with the `RegimeAssessment` available at that time (deterministic classifier, `strategy-spec.md` §3.3). M1 reports use `unknown`.
- Each trade is attributed to the regime at entry; daily returns are attributed to the regime at the start of the day.
- Per-regime report: bars in regime, trades, net PnL, win rate, profit factor, contribution to total PnL, and maximum drawdown within regime spells.
- A regime with fewer than 20 closed trades is reported as "insufficient sample" rather than judged.
- OF-05 uses this breakdown to detect regime concentration.

## 9. Benchmark comparisons and metric definitions

Equity is marked to market at every decision-timeframe close and at 00:00 UTC daily. Crypto trades every day, so a year is 365 days. Risk-free rate is 0, which is why ratios are called "-like".

| Metric | Definition |
|---|---|
| Total return | `E_end / E_start − 1` |
| Annualized return (CAGR) | `(E_end / E_start)^(365 / days) − 1` |
| Volatility | Standard deviation of daily log returns × √365 |
| Downside deviation | √(mean(min(r_daily, 0)²)) × √365 |
| Sharpe-like | mean(daily return) × 365 ÷ volatility |
| Sortino-like | mean(daily return) × 365 ÷ downside deviation |
| Maximum drawdown | max over t of `1 − E_t / max_{s≤t} E_s` |
| Calmar | CAGR ÷ maximum drawdown |
| Profit factor | Sum of winning trade PnL ÷ absolute sum of losing trade PnL (after costs) |
| Win rate; payoff ratio | Winners ÷ closed trades; average win ÷ absolute average loss |
| Turnover | Sum of absolute traded notional ÷ average equity, annualized |
| Fee and slippage burden | (Fees + slippage cost) ÷ gross PnL before costs; also as % of starting capital |
| Exposure | Time-weighted average gross exposure ÷ equity, total and by asset |
| Average holding period | Mean time from entry fill to exit fill |
| Time under water | Longest period below a previous equity peak |
| Consistency | Share of positive calendar months; dispersion of rolling 90-day returns |
| Benchmark-relative return | Strategy total return minus each benchmark's total return; ratio comparisons side by side |
| Rejections | Count of risk and execution rejections by reason code |

Every report compares the strategy with all four benchmarks over the same window and cost scenario (SM-05).

## 10. Robustness and sensitivity checks

| Check | Method | Linked rejection criterion |
|---|---|---|
| RB-01 Parameter neighborhood | Re-run at ±1 grid step for each parameter; look for a plateau, not a spike | OF-03 |
| RB-02 Cost sensitivity | `low`, `base`, `stress` scenarios | OF-07 |
| RB-03 Delay sensitivity | +1 and +2 bars of execution delay | OF-08 |
| RB-04 Start-date sensitivity | Shift the start by 1, 2, and 4 weeks | OF-06 |
| RB-05 Timeframe sensitivity | 1h versus 4h | Reported |
| RB-06 Instrument sensitivity | BTC only, ETH only, both | Reported |
| RB-07 Outlier removal | Remove the top 5 trades (or top 5%, whichever is larger) | OF-04 |
| RB-08 Block bootstrap | Resample daily returns in 30-day blocks (1,000 resamples) for confidence intervals | UD-08 input |
| RB-09 Random-entry control | Compare with `random_entry` (matched counts, 100 seeds) | OF-12 |
| RB-10 Regime concentration | Share of net PnL by regime | OF-05 |
| RB-11 Trade-order shuffle | Shuffle trade order (1,000 times) to get a drawdown distribution | Reported |

## 11. Experiment parameter sets (RECOMMENDATION R-02; ADR-016)

Experiments sometimes need values that the owner has not decided yet. They may supply them only through an experiment parameter set, under these rules:

1. Accepted only in the `backtest` environment; the `paper` environment refuses them (RR-02, T-08).
2. May target only fields whose status is `unresolved` or `hypothesis`; approved values, safety constants, kill-switch policy, and loss-response constants cannot be overridden (RP-12, T-09).
3. Every value records its source (for example "UD-03 option A recommendation") and is labelled `experiment` in the `CompiledProfile`, the journal, and the report's provenance banner.
4. Values must satisfy the schema and policy rules RP-01 to RP-07.
5. Results from an experiment parameter set are evidence for resolving the UD item; they never resolve it automatically.

Test fixtures under `tests/fixtures/` use the reserved experiment ID prefix `EXP-0000-` and the provenance label `fixture`.

### 11.1 EXP-2026-001 parameter set (vertical-slice demonstration)

Values are taken from the recommendations in `product-requirements.md` §10. They are **not approved values**.

```yaml
schema_version: "1.0.0"
kind: ExperimentDefinition
experiment_id: EXP-2026-001
title: Vertical-slice demonstration run
purpose: pipeline_verification          # not a strategy evaluation; results must not inform UD decisions
hypothesis: >-
  The validated Balanced paper profile, BTC and ETH candles, buy-and-hold benchmarks, and the
  sma_trend baseline run end to end through deterministic risk checks and simulated execution,
  producing a fully traceable journal and a reproducible report.
environment: backtest
trading_profile: configs/profiles/balanced-paper.yaml
strategy: {strategy_id: sma_trend, version: 1.0.0}
timeframe: 4h
cost_scenario: base
parameters:
  risk:
    limits.portfolio_drawdown_circuit_breaker_pct: {value: 15, source: "UD-01 option B (recommendation)"}
    limits.daily_loss_limit_pct: {value: 3, source: "UD-02 option A (recommendation)"}
    sizing.risk_per_trade_pct: {value: 1.0, source: "UD-03 option A (recommendation)"}
    sizing.hard_stop_policy:
      value: {method: atr_multiple, timeframe: decision_timeframe, atr_period_bars: 14, atr_multiple: 2.0}
      source: "UD-16 recommendation"
    loss_response.size_reduction_schedule:
      value:
        method: stepwise_fraction_of_breaker
        steps:
          - {drawdown_fraction_of_breaker_below: 0.3333, multiplier: 1.0}
          - {drawdown_fraction_of_breaker_below: 0.6667, multiplier: 0.5}
          - {drawdown_fraction_of_breaker_below: 1.0, multiplier: 0.25}
      source: "UD-15 option A (recommendation)"
    allocation.total_exposure_cap_pct: {value: 80, source: "UD-12 option A (recommendation)"}
    allocation.minimum_reserve_pct_range: {value: {low: 20, high: 40}, source: "UD-04 option A (recommendation)"}
    allocation.max_open_positions: {value: 5, source: "UD-12 option A (recommendation)"}
    cooldown.after_consecutive_losing_trades.count: {value: 3, source: "UD-17 recommendation"}
    cooldown.after_consecutive_losing_trades.duration_hours: {value: 24, source: "UD-17 recommendation"}
    data_and_execution_faults.exchange_errors.max_consecutive_errors_before_kill_switch: {value: 3, source: "UD-17 recommendation"}
  eligibility:
    liquidity.min_by_tier.core: {value: 50000000, source: "UD-18 option A (recommendation)"}
    data_history.min_by_tier.core: {value: 365, source: "UD-18 option A (recommendation)"}
    spread.when_no_spread_data: {value: not_applicable, source: "R-21 / UD-18 (recommendation)"}
# Balanced concentration caps are not overridden: they come from H-01..H-04 (hypothesis).
```

## 12. Experiment register

| ID | Title | Stage | Purpose | Informs |
|---|---|---|---|---|
| EXP-2026-001 | Vertical-slice demonstration | M1 | Pipeline verification on synthetic or owner-supplied data | Nothing (verification only) |
| EXP-2026-002 | Baseline comparison | V1 | All baselines and benchmarks, walk-forward, all cost scenarios, real data (UD-20) | Strategy selection; UD-21 |
| EXP-2026-003 | Risk-parameter evidence | V1 | Grid over the option values of UD-01, UD-02, UD-03, UD-04, UD-12, UD-13, UD-15, UD-16: breaker trip frequency, time in lockout, drawdown distribution, effect on returns | Owner resolution of those UD items |
| EXP-2026-004 | Intraday allocation matrix | V1.5 | §7 | UD-14 |
| EXP-2026-005 | Regime classifier validation | V1 | Regime persistence, stability, per-regime strategy behavior, leakage checks | Classifier parameters; eligibility matrix |
| EXP-2026-006 | Ensemble conflict-rule comparison | V1 to V1.5 | UD-07 options A, B, C | UD-07 |
| EXP-2026-007 | ML challenger | P8 | ML model against non-ML baselines | Promotion decision (UD-08) |
| EXP-2026-008 | Major-tier eligibility screening | V1.5 | Candidate Major assets under UD-18 thresholds | UD-06, UD-18 |

## 13. Experiment record template

Machine-readable records (`ExperimentRecord`, `architecture.md` §17.2) are written to `data/experiments/<experiment_id>/record.json`. A human-readable copy is committed to `docs/experiments/<experiment_id>.md` using this template, which extends the v0.1 template:

```markdown
# Experiment: EXP-YYYY-NNN

## Hypothesis
## Purpose
(pipeline_verification | strategy_evaluation | risk_parameter_evidence | allocation | regime | ensemble | ml | universe)

## Data
- Source / venue:
- Instruments:
- Time range (evaluation; warm-up):
- Candle interval:
- Dataset IDs and hashes:
- Holdout accessed? (yes/no; access-log entry)

## Strategy/model
- Strategy ID and version:
- Feature set version and definitions hash:
- Regime classifier version:
- Ensemble version and weighting method:
- Model ID and version:
- Trading profile ID, version, hash:
- Risk profile ID, version, hash:
- Config hash (CompiledProfile):

## Experiment parameters (non-approved values)
| Field | Value | Source (UD/H ID) | Provenance label |

## Assumptions
- Cost scenario(s), fees, slippage:
- Execution delay:
- Minimum notional:

## Method
- Split design and folds:
- Parameter grid and number of configurations tried:
- Seeds:

## Results (net of costs)
- Strategy vs bm_cash, bm_bh_btc, bm_bh_eth, bm_ew_btc_eth:
- Return, CAGR, maximum drawdown, Sortino-like, Calmar, profit factor, win rate, trades, turnover, fee burden:
- Per-fold table:
- Per-regime table:
- Rejections by reason code:

## Robustness checks (RB-01 to RB-11)
## Overfit checks (OF-01 to OF-12): pass / fail / not applicable, with evidence
## Failure analysis

## Decision
- reject / iterate / candidate (shadow) / recommend promotion
- Decided by, date, rationale
- Note: promotion requires a separate owner-signed PromotionRecord.

## Reproduction
- Command:
- Code revision:
- Environment lock hash:
- Run IDs and journal root hashes:
```

## 14. Explicit rejection criteria for overfit strategies (RECOMMENDATION R-12)

A strategy, parameter set, ensemble rule, or model is rejected, or its result marked invalid or inconclusive as stated, if any criterion is met. Thresholds are recommendations for the owner to confirm with UD-08.

| ID | Criterion | Outcome |
|---|---|---|
| OF-01 | Any look-ahead check (LA-01 to LA-08) fails | Reject |
| OF-02 | Holdout Sortino-like is below 50% of the walk-forward out-of-sample value, or negative while out-of-sample was positive | Reject |
| OF-03 | Fewer than 60% of parameter neighbors (RB-01) beat the best simple baseline (performance is a spike, not a plateau) | Reject |
| OF-04 | Removing the top 5 trades (or top 5%, whichever is larger) makes excess return over the best simple baseline zero or negative | Reject |
| OF-05 | More than 80% of net PnL comes from one regime label and the strategy is not declared regime-specific | Reject, or restrict eligibility to that regime and re-test |
| OF-06 | Positive excess return in fewer than half of the walk-forward folds | Reject |
| OF-07 | Excess return is zero or negative under `base` costs (reject); or under `stress` costs (not promotable) | Reject / not promotable |
| OF-08 | Excess return changes sign with +1 bar of execution delay | Reject |
| OF-09 | Fewer than 30 closed trades in out-of-sample folds (100 for intraday) | Inconclusive; cannot be promoted |
| OF-10 | Number of configurations tried was not recorded; or more than 20 were tried without confirmation on an untouched period | Invalid result |
| OF-11 | The holdout was used more than once for the same strategy family | Invalid result |
| OF-12 | Does not beat cash and buy-and-hold on Sortino-like and Calmar, or does not beat the random-entry control | Reject (adds no value) |

## 15. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue: baselines, split and walk-forward design, look-ahead checks, cost scenarios, intraday matrix, regime evaluation, metric definitions, robustness checks, experiment parameter sets, experiment register, record template, overfit rejection criteria. |
