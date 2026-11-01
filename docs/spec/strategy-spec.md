# Strategy Specification

**Document status:** Draft for owner review
**Version:** 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Depends on:** `product-requirements.md` §3 (decision registers), `architecture.md` §4.3 (authority matrix), §6.7 (risk rules), §17 (contracts), `risk-profile.schema.yaml`
**Used by:** `experiment-plan.md`, `execution-plan.md`, `code-session-handoff.md`

Status labels: **APPROVED** (D-nn), **HYPOTHESIS** (H-nn), **RECOMMENDATION** (R-nn), **UNRESOLVED** (UD-nn).

---

## 1. Purpose and scope

This document defines how the system turns market data into proposed trades: the regime taxonomy, the baseline strategies, the signal and ensemble contracts, conflict and no-trade behavior, minute-level strategy rules, the deterministic position-sizing boundary, versioning, the champion/challenger lifecycle, and promotion gates.

It implements the approved hybrid regime-aware ensemble (D-29), in which no single opaque model receives total control (D-30). Strategies and models propose; the deterministic risk engine decides (D-13, D-14).

## 2. Pipeline recap

| D-29 step | Stage | Contract produced | M1 implementation | V1 implementation |
|---|---|---|---|---|
| 1 | Ingest and validate market data | `MarketSnapshot`, `FeatureSet` | Datasets with DQ checks; SMA and ATR features | Same plus feature set v1 (`data-architecture.md` §8) |
| 2 | Classify the market regime | `RegimeAssessment` | Null classifier (`method: not_evaluated`, states `unknown`; data state from freshness checks) | Deterministic classifier (§3.3) |
| 3 | Determine eligible strategies | (inside `EnsembleDecision`) | All registered strategies eligible (one strategy) | Regime eligibility matrix (§4.9) |
| 4 | Generate candidates | `SignalCandidate` | `sma_trend` | Plus `tsmom`, `mean_reversion`, `volatility_breakout`; ML later (P8) |
| 5 | Combine through the ensemble | `EnsembleDecision` | Single-strategy pass-through | R-01 conflict rules (§7) until UD-07 is resolved |
| 6 | Risk approve, modify, or reject | `RiskDecision` | RR-01 to RR-12 | Same |
| 7 | Size deterministically | `OrderIntent` | RR-13 to RR-20 (§9) | Same |
| 8 | Paper execution only | `ExecutionReport` | Internal simulator | Simulator; forward paper session |
| 9 | Journal the decision chain | `TradeEvent` | All of the above | Same plus explanations |

---

## 3. Regime taxonomy

### 3.1 Axes and labels (RECOMMENDATION R-08)

v0.1 listed six regimes: trending up, trending down, range-bound, high volatility, low volatility, uncertain/stale. Trend and volatility can occur together (a strong uptrend can be volatile), so v0.2 classifies them on separate axes and treats data quality as an override.

| Axis | Values | Meaning |
|---|---|---|
| `trend_state` | `trending_up`, `trending_down`, `range_bound`, `unknown` | Direction of the prevailing move on the regime timeframe |
| `volatility_state` | `low`, `normal`, `high`, `unknown` | Realized volatility relative to its own trailing history |
| `data_state` | `ok`, `uncertain`, `stale` | Whether the inputs are trustworthy enough to act on |

The composite label is `"<trend_state>/<volatility_state>"` (for example `trending_up/high`). `unknown` is used only when the classifier is not evaluated (M1) or warm-up is incomplete.

### 3.2 Mapping from v0.1 labels

| v0.1 regime | v0.2 representation |
|---|---|
| trending up | `trend_state = trending_up` |
| trending down | `trend_state = trending_down` |
| range-bound | `trend_state = range_bound` |
| high volatility | `volatility_state = high` |
| low volatility | `volatility_state = low` |
| uncertain/stale | `data_state = uncertain` or `stale` |

### 3.3 V1 deterministic classifier (RECOMMENDATION; parameters are research parameters tuned in EXP-2026-005)

Computed per instrument on closed 4h candles (the regime timeframe), causally:

- `trend_state`: `trending_up` if SMA(50) > SMA(200) and close > SMA(50); `trending_down` if SMA(50) < SMA(200) and close < SMA(50); otherwise `range_bound`.
- `volatility_state`: realized volatility = standard deviation of 4h log returns over the last 30 bars. Compare with its own values over the trailing 365 days: below the 25th percentile is `low`, above the 75th percentile is `high`, otherwise `normal`.
- `data_state`: `stale` if the snapshot is stale (RR-06 definition); `uncertain` if warm-up is incomplete (fewer than 200 closed 4h bars, or less than 365 days for the volatility percentile) or if `trend_state` changed more than twice in the last 12 bars; otherwise `ok`.
- `confidence`: null for the deterministic classifier.

The classifier for a 1h decision uses the most recent closed 4h bar at or before the 1h decision time (no look-ahead).

### 3.4 Uncertain and stale behavior

- `stale`: no orders of any kind for that instrument (the risk engine also rejects with `STALE_DATA`).
- `uncertain`: no new entries; exits allowed (v0.1 §6.6: "Uncertain or stale states should block or reduce activity").
- M1 null classifier: `data_state` still follows freshness (`stale` or `ok`), so stale-data blocking is active in M1.

### 3.5 AI-assisted classification (later)

AI and models may directly influence regime classification (D-31). An ML or AI-assisted classifier must: produce the same `RegimeAssessment` contract with `method: ml_model` or `ai_assisted` and a model version; never set `data_state` to `ok` when the deterministic freshness checks say otherwise; and enter the active paper trader only as a promoted challenger (§11).

---

## 4. Initial baseline strategies

### 4.1 Benchmarks (computed analytically; RECOMMENDATION R-20)

Benchmarks are reference series. They are not routed through the risk engine or execution, because they measure the market rather than trade it.

| Benchmark ID | Definition | Costs |
|---|---|---|
| `bm_cash` | Hold $2,500 in cash for the whole period | None |
| `bm_bh_btc` | Buy BTC with all capital at the first evaluated bar's next open; hold to the end | Entry fee and slippage of the run's cost scenario |
| `bm_bh_eth` | As above for ETH | As above |
| `bm_ew_btc_eth` | 50% BTC and 50% ETH at the start; no rebalancing | As above |

All benchmarks use the same evaluation window as the strategy (after the strategy's warm-up) and are marked to market at every decision-timeframe close. Open strategy positions are also marked to market at the end; there is no forced liquidation for either.

### 4.2 Strategy catalogue

| Strategy ID | Family | Stage | Decision timeframes | Default parameters (RECOMMENDATION) |
|---|---|---|---|---|
| `sma_trend` | Trend/momentum | M1 | 1h, 4h | fast 20, slow 50 (R-09) |
| `tsmom` | Time-series momentum | V1 | 1h, 4h | lookback = 7 days (168 bars on 1h, 42 bars on 4h) |
| `mean_reversion` | Mean reversion | V1 | 1h, 4h | RSI(14) < 30 and close below the lower Bollinger band (20, 2σ); exit at the middle band or RSI > 50 |
| `volatility_breakout` | Breakout | V1 | 4h | Entry: close above the highest high of the previous 20 bars; exit: close below the lowest low of the previous 10 bars |
| `random_entry` | Control | V1 | as tested strategy | Same entry count and holding-period distribution as the strategy under test, random timing, fixed seed |
| ML challenger | ML | P8 | 1h, 4h | Defined in its `ExperimentRecord`; challenger only |

All parameters are research parameters, not risk values. Changing them creates a new strategy version (§10) and must be justified by an experiment with the overfit checks in `experiment-plan.md` §14.

### 4.3 `sma_trend` version 1.0.0 (M1 trend/momentum baseline; RECOMMENDATION R-09)

- **Inputs:** closed candles of the decision timeframe (1h or 4h); features `sma_fast = SMA(close, 20)` and `sma_slow = SMA(close, 50)`, computed causally.
- **Warm-up:** 51 closed bars. No signals before warm-up completes.
- **Entry signal (`side: buy`):** at the close of bar t, `sma_fast[t] > sma_slow[t]` and `sma_fast[t-1] <= sma_slow[t-1]` (a cross up). Rationale code `SMA_CROSS_UP`.
- **Exit signal (`side: sell`):** at the close of bar t, `sma_fast[t] < sma_slow[t]`. Emitted on every such bar, so a missed or rejected exit is retried. Rationale code `SMA_FAST_BELOW_SLOW`.
- **No signal** otherwise. A rejected entry is not retried until the next cross up.
- **Fields:** `strength = 1.0` (binary strategy), `confidence = null`, `expected_horizon = null` (holding period is adaptive, D-15), `invalidation = {kind: indicator_cross, level: null, reason: SMA_FAST_BELOW_SLOW}`, `model_id = null`, `model_version = null`, `sleeve = core`.
- **Hard stop:** not part of the strategy. The deterministic stop policy (UD-16) applies to every entry (§9).

### 4.4 to 4.8 Other baselines

- **4.4 `tsmom`:** buy when the trailing return over the lookback turns positive; sell while it is zero or negative. Strength 1.0.
- **4.5 `mean_reversion`:** buy on the entry condition in §4.2; sell on the exit condition. Strength = `(30 − RSI) / 30`, clipped to [0, 1].
- **4.6 `volatility_breakout`:** buy on the channel breakout; sell on the exit channel. Strength 1.0.
- **4.7 `random_entry`:** used only in experiments to test whether timing adds value; never eligible for promotion.
- **4.8 ML challenger:** must output a `SignalCandidate` (probability or expected return mapped to side, strength, and calibrated confidence). It may never output quantities, stops, or limits (D-32), and it is evaluated only after the non-ML baselines exist (ADR-004, RT-03).

### 4.9 Regime eligibility matrix for entries (RECOMMENDATION; V1)

Exits are always eligible: a strategy can always close a position it opened.

| Strategy | `trending_up` | `range_bound` | `trending_down` | `volatility_state = high` | `data_state` not `ok` |
|---|---|---|---|---|---|
| `sma_trend` | Yes | No | No | Yes | No |
| `tsmom` | Yes | No | No | Yes | No |
| `mean_reversion` | No | Yes (low or normal volatility only) | No | No | No |
| `volatility_breakout` | Yes | Yes (low or normal volatility only) | No | No | No |

Spot long-only (SAFE-02) means `trending_down` offers no entries for any strategy.

---

## 5. Signal contract (`SignalCandidate`)

Field list and ownership: `architecture.md` §17.2, contract 6. Semantics:

| Field | Semantics |
|---|---|
| `side` | `buy` = open a long position if flat. `sell` = close the long position if held. Spot long-only: `sell` never opens a short. |
| `strength` | Strategy-specific signal strength in [0, 1]. Used by the ensemble score; never used for sizing in V1. |
| `confidence` | Calibrated probability in [0, 1] when the producer can calibrate (ML), else null. Advisory only. |
| `expected_horizon` | ISO-8601 duration or null. Informational; holding is adaptive (D-15). |
| `entry_reference_price` | Close of the decision bar. Not an order price. |
| `invalidation` | Condition under which the thesis is wrong (`kind`, optional `level`, `reason`). Not a stop order; the hard stop is set by the risk profile (UD-16). |
| `sleeve` | `core` (1h/4h strategies) or `intraday` (separately approved intraday strategies only). |
| `rationale_codes` | Machine-readable reasons used by explanation templates. |

Rules:

- **S-01** A signal never contains quantity, notional, leverage, stop policy, or limit fields (schema `extra="forbid"`; D-32).
- **S-02** `decision_time_utc` equals the `FeatureSet.as_of_utc` it was computed from, which equals a bar close time.
- **S-03** Every input used has `close_time_utc <= decision_time_utc` (P-07).
- **S-04** `strategy_id` and `strategy_version` match a registry entry whose lifecycle state allows the current environment (§11).
- **S-05** Core-sleeve signals use a timeframe in the profile's `primary_decision_timeframes` (D-16).
- **S-06** Intraday-sleeve signals are accepted only from strategies registered as intraday and approved (D-18, D-19).
- **S-07** One signal per strategy, instrument, and decision time; duplicates are dropped and journaled.
- **S-08** Signals are journaled whether or not they lead to a trade (D-29 step 9).

---

## 6. Ensemble contract (`EnsembleDecision`)

Field list: `architecture.md` §17.2, contract 7.

| `action` | Meaning |
|---|---|
| `enter_long` | Proposes opening a long position (position must be flat) |
| `exit_long` | Proposes closing the long position (position must be long) |
| `hold` | No change needed: already in the desired state (for example a `sell` signal while flat) or no signals |
| `no_trade` | A trade was suggested but blocked by ensemble rules; `no_trade_reason` is required |

`no_trade_reason` values: `SIGNAL_CONFLICT`, `REGIME_BLOCKED`, `DATA_STALE`, `DATA_UNCERTAIN`, `NO_ELIGIBLE_SIGNALS`, `BELOW_THRESHOLD`.

Rules:

- **E-01** Exactly one `EnsembleDecision` per instrument per decision time.
- **E-02** The decision lists contributing signal IDs and ignored signals with reasons (`INELIGIBLE_IN_REGIME`, `DUPLICATE`, `STALE`).
- **E-03** The ensemble never sizes and never creates orders (FR-STRAT-09).
- **E-04** `weighting_method` names the method in use: `single_strategy_passthrough` (M1) or `equal_weight_opposition_veto` (V1, R-01); other UD-07 options are challengers.
- **E-05** Position state (`flat` or `long`) comes from the latest `PositionSnapshot`, including pending orders.
- **E-06** The decision is deterministic: the same inputs give the same output (ties ordered by `strategy_id`).

---

## 7. Conflict and no-trade behavior

> **RECOMMENDATION R-01. This is not a user-approved decision.** The signal-conflict weighting formula is UNRESOLVED (UD-07). The rules below are recommended for V1 because they are transparent, deterministic, hard to overfit, and conservative: when strategies disagree about opening risk, the system does nothing; when the strategy that opened a position wants out, it gets out.

### 7.1 Recommended conflict rules

| Rule | Recommendation |
|---|---|
| C-01 Regime gate | Only strategies eligible for the current `RegimeAssessment` (§4.9) may contribute to an entry. Ineligible signals are journaled as `INELIGIBLE_IN_REGIME` and ignored. |
| C-02 Data-state veto | `stale` → `no_trade` with `DATA_STALE` (no orders). `uncertain` → no entries (`DATA_UNCERTAIN`); exits allowed. |
| C-03 Opposition veto for entries | Propose `enter_long` only if at least one eligible strategy says `buy` and no eligible strategy says `sell` for the same instrument and decision time. Any opposing vote → `no_trade` with `SIGNAL_CONFLICT`. |
| C-04 Exit precedence | If long and any strategy that contributed to the entry (the position's owners) says `sell`, propose `exit_long` even if other strategies say `buy`. A `sell` from a non-owner sets `conflict.detected = true` but does not exit in V1. |
| C-05 Equal-weight score | `combined_score` = mean `strength` of the contributing `buy` signals. Entry requires `combined_score >= τ_entry`. τ_entry is part of UD-07; for V1 baselines with binary strength the recommended τ_entry is 0, so C-03 alone decides. |
| C-06 Confidence is advisory | Confidence and score never change position size in V1 (§9.1). |
| C-07 Determinism | Signals are processed in `strategy_id` order; identical inputs give identical decisions. |
| C-08 Abstain by default | Missing, malformed, or duplicate signals never produce a trade. |

### 7.2 Worked examples

| # | Position | Regime | Signals | Decision |
|---|---|---|---|---|
| 1 | Flat | `trending_up/normal`, ok | `sma_trend` buy, `tsmom` buy | `enter_long`, score 1.0 |
| 2 | Flat | `range_bound/low`, ok | `sma_trend` buy, `mean_reversion` sell | `sma_trend` is ineligible in `range_bound` (C-01); only a sell remains while flat → `hold` |
| 3 | Flat | `trending_up/normal`, ok | `sma_trend` buy, `volatility_breakout` buy, `tsmom` sell | Opposition veto (C-03) → `no_trade`, `SIGNAL_CONFLICT` |
| 4 | Long (opened by `sma_trend`) | any, ok | `sma_trend` sell, `tsmom` buy | Exit precedence (C-04) → `exit_long` |
| 5 | Long (opened by `sma_trend`) | any, ok | `mean_reversion` sell only | Non-owner sell → `hold`, `conflict.detected = true` |
| 6 | Any | any, `stale` | any | `no_trade`, `DATA_STALE` (risk engine also rejects with `STALE_DATA`) |
| 7 | Flat | any, `uncertain` | `sma_trend` buy | `no_trade`, `DATA_UNCERTAIN` |

### 7.3 Options for UD-07 and recommended path

| Option | Description | Recommended role |
|---|---|---|
| A | Equal-weight vote with opposition veto (this section) | V1 champion candidate |
| B | Regime-conditional static weights fitted on walk-forward training folds | Challenger in EXP-2026-006 |
| C | Weighting by calibrated confidence | Challenger in EXP-2026-006 once calibrated producers exist |
| D | Learned meta-model (stacking) | ML challenger only (P8); never automatically promoted |

---

## 8. Requirements for minute-level strategies

Minute-level data has exactly two permitted roles (D-18). Both start in V1.5 (RECOMMENDATION R-23). High-frequency and latency-arbitrage trading are out of scope (D-21).

### 8.1 Role A: refining entries and exits of 1h/4h decisions

- **M-01** Refinement acts only on an order that already has an approved `RiskDecision` from a 1h/4h cycle. It may choose *when* to submit within a bounded window that ends no later than the parent intent's `valid_until_utc`.
- **M-02** Refinement cannot change side, cannot increase quantity, cannot create an order without a parent decision, and cannot extend validity.
- **M-03** The fallback when the window expires (submit at window end, or cancel) is declared per refinement version and fixed before approval.
- **M-04** 1m candles pass the same data-quality checks; stale 1m data falls back to the parent's unrefined behavior.
- **M-05** A refinement is kept only if experiments show better net fill quality than the unrefined parent after costs.

### 8.2 Role B: independent intraday strategies (separately approved)

- **I-01** Each intraday strategy needs its own approval through the lifecycle in §11 (D-18: "separately approved").
- **I-02** It trades only inside the isolated intraday sleeve: a separate ledger with a capped allocation (UD-14, selected by testing 5%, 10%, 15%, and 20% per D-20) and its own loss limits (UD-14). The sleeve can never borrow capital from the core portfolio (D-19).
- **I-03** Concentration caps apply to aggregate exposure per asset across sleeves (RR-15).
- **I-04** The intraday sleeve is disabled while the cap is `TBD` (RR-12, PV-05).
- **I-05** Minimum bar size is 1 minute; at most one decision per instrument per bar; no sub-minute data, order-book latency strategies, or co-location (SAFE-11).

### 8.3 Stricter evaluation rules for intraday strategies (D-19; RECOMMENDATION thresholds)

| Rule | Core strategies | Intraday strategies |
|---|---|---|
| E-I1 Cost scenario that must stay positive | `base` | `stress` |
| E-I2 Minimum closed trades in test folds | 50 (UD-08 recommendation) | 100 |
| E-I3 Fee and slippage burden | Reported | At most 50% of gross profit |
| E-I4 Delay sensitivity (+1 bar) | Must not flip the sign of excess return (OF-08) | Same, and also +2 bars reported |
| E-I5 Portfolio-level value | Beats baselines | Must improve portfolio Sortino-like and Calmar versus the 0% control at the selected cap (EXP-2026-004) |
| E-I6 Cap robustness | n/a | Evaluated at all of 5%, 10%, 15%, 20%; the smallest effective cap is preferred (D-20) |
| E-I7 Shadow period before promotion | 30 days (UD-08 recommendation) | 60 days |

---

## 9. Deterministic position-sizing boundary

### 9.1 What may and may not influence size

| Producer | May output | May not output |
|---|---|---|
| Strategies (rule-based or ML) | Side, strength, confidence, expected horizon, invalidation | Quantity, notional, leverage, stop policy, caps |
| Ensemble | Action, combined score, confidence, conflict status | Quantity or notional |
| AI/LLM components | Recommendations (for example a proposed adaptation multiplier, later) | Final size, hard stop policy, exposure ceilings, drawdown or daily limits, caps, leverage, kill-switch behavior (D-32) |
| Risk engine (deterministic) | Approved quantity and notional, stop price, binding constraint | — |

### 9.2 V1 sizing algorithm for entries (RR-13 to RR-20)

All arithmetic uses `Decimal`. `E` = equity, `C` = cash, `K` = cash committed to pending orders, `P` = reference price (close of the decision bar), `B` = breaker threshold (UD-01), `DD` = current drawdown from the breaker high-water mark.

1. `m_loss = schedule(DD / B)` from `loss_response.size_reduction_schedule` (UD-15). `m_loss = 0` only at the breaker, which RR-09 already rejects.
2. `m_adapt = 1` in V1 (upward adaptation disabled, R-22).
3. `stop_distance = atr_multiple × ATR(atr_period_bars) / P` for `atr_multiple`, or `fixed_pct / 100` for `fixed_pct` (UD-16).
4. `risk_budget = E × risk_per_trade_pct / 100 × m_loss × m_adapt` (UD-03).
5. `N_risk = risk_budget / stop_distance` (risk-based notional).
6. `H_tier = E × tier_cap_pct / 100 − exposure(asset) − pending(asset)`, aggregated across sleeves (H-01 to H-03 for Balanced).
7. `H_spec = E × speculative_total_cap_pct / 100 − speculative_exposure − speculative_pending` (Speculative assets only; H-04 for Balanced).
8. `H_total = E × total_exposure_cap_pct / 100 − total_exposure − total_pending` (UD-12).
9. `reserve = E × reserve_low / 100` (UD-04; may rise toward `reserve_high` only under defensive adaptation); `H_cash = (C − K − reserve) / (1 + fee_rate)`.
10. `N = min(N_risk, H_tier, H_spec, H_total, H_cash)`. If `N <= 0`, reject with the code of the binding limit (`CONCENTRATION_LIMIT`, `EXPOSURE_LIMIT`, `RESERVE_LIMIT`).
11. RR-19: if open positions plus pending entries already equal `max_open_positions` (UD-12), reject with `MAX_POSITIONS`.
12. `P_cons = P × (1 + slippage_bps / 10,000)` (conservative reference price).
13. `qty = round_down(N / P_cons, quantity_step)`.
14. RR-20: if `qty × P_cons < min_notional_usd`, reject with `SIZE_BELOW_MINIMUM`.
15. `status = approved` if `N == N_risk`, otherwise `modified` with `binding_constraint` set to one of `TIER_CAP`, `SPECULATIVE_CAP`, `TOTAL_EXPOSURE_CAP`, `RESERVE_FLOOR`, `AVAILABLE_CASH`.

Caps constrain risk-increasing orders at decision time. Price drift after entry does not force trimming in V1 (RECOMMENDATION R-19).

### 9.3 Exits and protective stops

- Exits close the full position at the next bar's open (V1 has no partial exits).
- Every entry gets an attached protective stop at `fill_price × (1 − stop_distance)`, registered with the adapter as part of the fill. It is not a new order decision.
- Exits are not blocked by loss limits, cooldowns, or eligibility (RR-05, RR-09 to RR-20 apply to entries only), but they still require fresh data and enabled execution (RR-03, RR-06).

### 9.4 Adaptation inside the profile (D-10; RECOMMENDATION R-22)

- Defensive adaptation in V1: the loss-scaling multiplier (D-12 step 2). Later, regime-driven multipliers no greater than 1 (for example in `high` volatility) may be added as research items.
- Upward adaptation (more aggressive inside the profile) stays disabled until `upward_multiplier_max` is approved (UD-15). Even then, it can never lift a hard cap (tier, speculative, total exposure, reserve floor, daily loss, breaker).
- AI may propose an adaptation multiplier (later). The sizer clamps it to `[0, upward_multiplier_max]` and records both the proposal and the applied value.
- The system never switches risk profiles (SAFE-10).

### 9.5 Rounding and minimums

Quantities round down to the instrument's `quantity_step` from the asset registry (`data-architecture.md` §4.4). USD amounts are kept at full `Decimal` precision internally and quantized to cents only in reports. `min_notional_usd` comes from the cost scenario (`experiment-plan.md` §6) until the venue's rules are known (UD-20).

### 9.6 Illustration (uses EXP-2026-001 experiment inputs, which are NOT approved values)

Assumptions for illustration only: E = $2,500 (D-04); risk per trade 1% and stop = 2 × ATR(14) (EXP-2026-001 inputs taken from the UD-03 and UD-16 recommendations); Balanced Core cap 35% (H-01); flat portfolio; ATR/price of 0.75% on 1h and 1.75% on 4h.

| Timeframe | Stop distance | `N_risk` | Core cap headroom | Result |
|---|---|---|---|---|
| 1h | 1.50% | $1,666.67 | $875.00 | `modified`, binding constraint `TIER_CAP`, notional $875.00 |
| 4h | 3.50% | $714.29 | $875.00 | `approved`, notional $714.29 |

This shows why caps are clamps rather than errors, and why the 1h configuration often hits the H-01 cap first.

---

## 10. Model and strategy versioning

| Artifact | Identifier | Version rule | Recorded in |
|---|---|---|---|
| Strategy | `strategy_id` + semantic `strategy_version` | Logic change: major; default-parameter change: minor; documentation: patch | `SignalCandidate`, registry, bundle |
| Feature set | `feature_set_version` + `definitions_hash` | Any definition or parameter change: new version | `FeatureSet`, `SignalCandidate` |
| Regime classifier | `classifier_id` + `classifier_version` | As strategy | `RegimeAssessment` |
| Ensemble | `ensemble_id` + `ensemble_version` + `weighting_method` + member list with versions | Membership or rule change: new version | `EnsembleDecision` |
| ML model | `model_id` + `model_version`; training dataset IDs, feature set version, training code revision, hyperparameters, artifact hash | Any retrain: new version | `SignalCandidate`, `ExperimentRecord` |
| Risk engine | `risk_engine_version` + per-rule versions | Rule logic change: new version | `RiskDecision` |

Strategy registry entry (`configs/strategies/<strategy_id>.yaml`): `strategy_id`, `version`, `family`, `kind` (`rule_based` or `ml_model`), `sleeve`, `timeframes`, `parameters`, `feature_set_version`, `regime_eligibility`, `lifecycle_state`, `code_ref`, `promotion_record_id` (when approved).

A champion bundle (`architecture.md` §8.6) pins every version above. The active paper trader refuses unpinned or unregistered versions.

---

## 11. Champion/challenger lifecycle

```text
 proposed ──> research ──> candidate ──> approved ──> champion ──> retired
                 │              │                         │
                 └──> rejected <┘                         └──> suspended ──> champion | retired
```

| State | Meaning | Where it can run | Who moves it in | Automatic? |
|---|---|---|---|---|
| `proposed` | Idea registered; AI may propose experiments (D-31) | Nowhere | Owner or AI proposal | Recording only |
| `research` | Implemented and versioned | Research backtests | Owner | No |
| `candidate` | Passed the overfit checks; challenger | Research and shadow (`observe_only`) | Owner (system may flag eligibility) | No |
| `approved` | Owner signed a `PromotionRecord` after gates G-01 to G-11 | Eligible for a champion bundle | Owner only (D-32, D-43) | Never |
| `champion` | Loaded in the active paper trader | Active paper trader | Owner deploys the bundle | Never |
| `suspended` | Champion halted pending review | Nowhere (shadow optional) | Owner, or automatic on integrity failure | Only into `suspended` |
| `retired` | Withdrawn or replaced | Nowhere | Owner | No |
| `rejected` | Failed checks | Nowhere | Owner or automatic on failed checks | Only into `rejected` |

Automation may only move a version *down* (to `rejected` or `suspended`), never up. Promotion must never be automatic (D-43).

## 12. Strategy promotion gates (RECOMMENDATION R-24; thresholds UNRESOLVED UD-08)

| Gate | Requirement | Threshold source |
|---|---|---|
| G-01 Reproducibility | A clean-checkout rerun reproduces the `ExperimentRecord` metrics exactly | Deterministic (NFR-01) |
| G-02 No leakage | Look-ahead checks LA-01 to LA-08 pass (`experiment-plan.md` §5) | Pass/fail |
| G-03 Beats simple baselines after costs | Risk-adjusted metrics beat the best simple baseline across walk-forward test folds | UD-08 |
| G-04 Beats the current champion | Same comparison against the champion, when one exists | UD-08 |
| G-05 Drawdown inside the profile | Maximum drawdown in every fold at or below the selected profile's breaker | UD-01, UD-08 |
| G-06 Regime stability | Not dependent on one regime (OF-05) | UD-08 |
| G-07 Outlier independence | Excess return survives removing the top trades (OF-04) | UD-08 |
| G-08 Cost and delay robustness | Survives `stress` costs and +1 bar delay (OF-07, OF-08) | UD-08 |
| G-09 Sufficient sample | Minimum closed trades (OF-09) | UD-08 |
| G-10 Shadow paper run | Shadow run in `observe_only` for the required period, signals identical to a deterministic replay, no integrity failures | UD-08 |
| G-11 Explicit owner approval | `PromotionRecord` signed by the owner with evidence experiment IDs and gate results | Required; never automatic (D-43) |

Intraday strategies must also meet E-I1 to E-I7 (§8.3).

---

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue: regime taxonomy, baseline strategies, signal and ensemble contracts, signal-conflict recommendation R-01, minute-level rules, sizing boundary, versioning, lifecycle, promotion gates. |
