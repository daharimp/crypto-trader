# AI-Assisted Crypto Trading System Architecture

**Document status:** Living design document
**Version:** 0.2
**Created:** 2026-10-08
**Revised:** 2026-10-08 (v0.2)
**Target:** Initial paper-trading prototype and implementation handoff to a Code session
**Primary owner:** Dahari Morgan-Parker
**Controlling inputs for v0.2:** `cowork-kickoff.md` (controlling specification), `decisions-summary.md`, `architecture.md` v0.1
**Package:** Part of the specification package indexed in `README.md`. The canonical decision registers (D, H, R, RT, UD IDs) are in `product-requirements.md` §3.

> **Safety boundary:** The first implementation uses paper, dry-run, or simulated funds only (D-02). Real-money execution, leverage, withdrawals, and unrestricted autonomous trading are explicitly out of scope until the system has passed documented validation and a separate production-readiness review (D-03). Deterministic risk controls have final authority (D-13).

**Reading v0.2.** Sections 1 to 16 keep the v0.1 structure. Sections whose content moved to another package document keep their heading and point to the new location, so nothing from v0.1 is lost. Section 17 (domain contracts) is new, and the change log moves to section 18. Status labels: **APPROVED** (D-nn), **HYPOTHESIS** (H-nn), **RECOMMENDATION** (R-nn, RT-nn), **UNRESOLVED** (UD-nn, value `TBD`).

---

## 1. Purpose

This document tracks the architecture, assumptions, design decisions, implementation plan, experiments, and improvements for an AI-assisted crypto trading system. It is a research and engineering project (D-01).

The desired user experience is:

1. The owner states objectives, capital, risk, time horizon, assets, and operating constraints. In V1 the owner authors these as a YAML `TradingProfile` and the CLI validates it; a guided questionnaire (V1 should-have) and a conversational interface (V2) come later (D-39, D-40).
2. The system converts the answers into a structured and versioned `TradingProfile`, compiled with the selected `RiskProfile` into a hashed `CompiledProfile`.
3. Quantitative strategies, and later optional machine-learning models, generate candidate signals inside a regime-aware ensemble (D-29).
4. A deterministic risk engine approves, modifies, or rejects each candidate (D-13).
5. An execution adapter submits approved orders to a paper-trading, dry-run, or simulated environment, automatically and without a per-trade approval click (D-33, D-34).
6. The system records decisions, explanations, fills, performance, errors, and model/configuration versions, so every order is traceable (D-36).
7. Results feed an evaluation loop used to improve strategies without silently changing production behavior; promotion into the active paper trader is always explicit (D-43).

The language model is a planning and interpretation component, not the final authority for trade execution. AI and models may directly influence the areas listed in D-31 and may only recommend for the areas listed in D-32 (authority matrix, §4.3).

---

## 2. Initial scope

Staged release scope (M1 vertical slice, V1, V1.5, V2, Experimental) is defined in `product-requirements.md` §4.

### 2.1 MVP goals

- Run locally with a repeatable developer setup.
- Define the objective and risk profile as a validated, versioned `TradingProfile` (authored YAML in M1; guided questionnaire as a V1 should-have).
- Support BTC and ETH initially (H-05), inside a rules-based universe of liquid assets with Core, Major, Speculative, and Blocked tiers (D-22, D-26).
- Support spot trading only.
- Use 1-hour and 4-hour decision timeframes with adaptive holding periods (D-15, D-16).
- Generate signals using simple, testable baseline strategies.
- Run historical backtests with fees and configurable slippage assumptions.
- Execute approved trades automatically using dry-run, paper, or simulated funds (D-02, D-33).
- Provide a manual kill switch (D-35).
- Explain and journal every decision.
- Produce risk and performance reports.
- Keep exchange, model, and strategy implementations replaceable (D-44).

### 2.2 Non-goals for the first version

- Guaranteed returns or claims of future profitability (D-07).
- Real-money autonomous execution (D-03).
- Leverage, margin, futures, options, or perpetual contracts. Derivatives *data* (V1.5, D-37) is a read-only input and does not change this.
- High-frequency, latency-sensitive, or latency-arbitrage trading (D-21).
- Autonomous withdrawal or transfer permissions.
- Letting an LLM directly invent order quantities or bypass risk checks.
- Training on unverified news or social-media content.
- Optimizing solely for historical profit.
- Automatic promotion of strategies or models (D-43).
- Dashboard and conversational UI before the CLI and core engine pipeline works end to end (D-40, D-41).

---

## 3. Architecture principles

P-01 to P-10 are carried forward from v0.1 as accepted baseline. P-11 and P-12 are new in v0.2.

1. **P-01 Risk engine has final authority.** No model, strategy, or LLM can bypass it (D-13, D-14).
2. **P-02 Configuration over improvisation.** Natural-language objectives must compile into a validated schema.
3. **P-03 Paper first.** The same decision pipeline runs in simulation before any live adapter is considered; backtests and paper sessions share one decision-cycle implementation.
4. **P-04 Deterministic core.** Position sizing, limits, and order validation are reproducible.
5. **P-05 Explainability by default.** Every proposed, rejected, submitted, and closed trade receives a journal entry.
6. **P-06 Version everything.** Profile, strategy, model, features, data range, configuration, and code revision must be traceable.
7. **P-07 Prevent look-ahead bias.** Features and decisions may use only data available at decision time.
8. **P-08 Measure against simple baselines.** AI/ML must outperform useful baselines after fees and risk, not merely show positive backtest returns.
9. **P-09 Fail closed.** Missing data, stale data, exchange errors, or invalid state stop new orders.
10. **P-10 Least privilege.** Test keys first; future keys must disable withdrawals and use strict permissions.
11. **P-11 Unresolved means blocked** (RECOMMENDATION R-02). A required value marked `TBD` is never defaulted; the run stops with a blocker report naming the UD ID.
12. **P-12 Research and active trading are separated** (APPROVED D-43). Experiments run in the research environment; only explicitly promoted versions run in the active paper trader.

---

## 4. System context

### 4.1 Context diagram

```text
                         +-----------------------------------------+
                         | Owner (researcher, risk owner, operator) |
                         +-----+---------------------------+-------+
                               |                           |
              TradingProfile YAML (M1);         CLI: validate, data, backtest,
              questionnaire (V1); chat (V2)     report, journal verify, kill switch
                               |                           |
                               v                           v
+---------------------+   +----+---------------------------+----+   +----------------------+
| Market data         |   | Core engine (Python package trader) |   | Local storage        |
| providers           +-->+  profiles + compiler   universe     +<->+  Parquet datasets    |
| V1: OHLCV candles   |   |  data + quality       features     |   |  SQLite journal      |
| V1.5/V2/Exp: later, |   |  regime  strategies   ensemble     |   |  SQLite ops state    |
| never required in V1|   |  risk engine + sizing  ops control |   |  reports, records    |
+---------------------+   |  execution gate  portfolio journal |   +----------------------+
                          |  evaluation  research/promotion    |
                          +----------------+-------------------+
                                           |
                                 approved OrderIntent only
                                           v
                          +----------------+-------------------+
                          | Execution adapters (allowlist)     |
                          |  M1: internal deterministic        |
                          |      simulator                     |
                          |  Later: paper/dry-run/sandbox      |
                          |      adapter chosen under UD-05    |
                          |  Never: live or real-money adapter |
                          +------------------------------------+

All components emit events to the append-only trade journal (TradeEvent),
structured JSON logs, the metrics/evaluation pipeline, and the audit trail.
```

### 4.2 Component boundaries

| Component | Package | Responsibility | Owns contracts | Must never | Phase |
|---|---|---|---|---|---|
| Profile service and compiler | `trader.profiles` | Load and validate `TradingProfile` and `RiskProfile`; detect contradictions; merge experiment parameter sets (backtest only); produce `CompiledProfile` and blocker reports | `TradingProfile`, `RiskProfile`, `CompiledProfile` | Invent missing values; mutate validated profiles | P1 |
| Universe and eligibility | `trader.universe` | Asset registry, tiers, eligibility checks, point-in-time `UniverseSnapshot` | `UniverseSnapshot` | Admit an asset that failed eligibility | P2 |
| Market data service | `trader.data` | Providers, quality checks, immutable datasets, decision-time snapshots | `MarketSnapshot`, `DatasetManifest` | Fill gaps silently; accept naive timestamps | P2 |
| Feature pipeline | `trader.features` | Causal, versioned features with lineage | `FeatureSet` | Read data after decision time | P3 |
| Regime classifier | `trader.regimes` | Classify regime and data state | `RegimeAssessment` | Mark stale data as tradable | P7 (null classifier in M1) |
| Strategy engine | `trader.strategies` | Generate signals | `SignalCandidate` | Emit quantities or orders | P3 |
| Ensemble layer | `trader.ensemble` | Gate by regime, combine, resolve conflicts, decide no-trade | `EnsembleDecision` | Emit quantities or orders | P7 (pass-through in M1) |
| Risk engine and sizing | `trader.risk` | Rule catalogue RR-01 to RR-20, deterministic sizing, order-intent creation | `RiskDecision`, `OrderIntent` | Be bypassed; accept AI-set limits | P4 |
| Operational control | `trader.risk.controls` | Kill switch, circuit breaker, daily lockout, cooldown state | `KillSwitchState` | Be disengaged by any automated component | P4 |
| Execution service | `trader.execution` | Execution gate EG-01 to EG-05, adapter registry, order state machine, reconciliation | `ExecutionReport` | Accept an intent without an approved `RiskDecision`; register a live adapter | P5 |
| Portfolio service | `trader.portfolio` | Ledger, mark-to-market, exposure, loss state | `PositionSnapshot` | Allow negative cash or negative quantity | P5 |
| Journal | `trader.journal` | Append-only hash-chained event store, verification, explanation templates | `TradeEvent` | Update or delete events | P6 |
| Evaluation and reporting | `trader.evaluation` | Metrics, benchmarks, reports | (report schema) | Claim or imply guaranteed profitability | P6 |
| Research and promotion | `trader.research` | Experiment definitions and records, walk-forward harness, promotion records | `ExperimentRecord`, `PromotionRecord` | Promote automatically | P6, P10 |
| Decision-cycle orchestrator | `trader.pipeline`, `trader.backtest` | Run the stages in order for each decision time; same code for backtest and paper | — | Skip a stage | P3 to P6 |
| CLI | `trader.cli` | Owner commands | — | Offer arbitrary order placement | P0 onward |

### 4.3 Authority matrix

AI and models may directly influence the D-31 areas. For the D-32 areas they may only recommend; the deterministic component in the last column decides.

| Decision area | AI/ML role | Final authority | Enforcement point |
|---|---|---|---|
| Market-regime classification | Directly influence (D-31) | Regime classifier output; stale or uncertain data states are set deterministically from data checks | `RegimeAssessment.data_state` |
| Eligible-strategy selection | Directly influence (D-31) | Ensemble, limited to strategies in the approved registry | `EnsembleDecision` |
| Ranking of eligible assets | Directly influence (D-31) | Universe service; ranking never adds an ineligible asset (D-25) | `UniverseSnapshot` |
| Combination and interpretation of signals | Directly influence (D-31) | Ensemble formula (UD-07; R-01 in V1) | `EnsembleDecision` |
| Explanations | Directly influence (D-31) | Generated from journal facts; never the source of truth | Explanation templates |
| Proposed research experiments | Directly influence (D-31) | Research environment only | `ExperimentRecord` |
| News and unstructured sources (later) | Directly influence (D-31) | Feature inputs in V2 | Provider interfaces |
| Final position size | Recommend only (D-32) | Deterministic sizer | RR-13 to RR-20 |
| Hard stop-loss policy | Recommend only | Owner-approved `RiskProfile` (UD-16) | `sizing.hard_stop_policy` |
| Portfolio exposure ceilings | Recommend only | `RiskProfile` (UD-12) | RR-17 |
| Drawdown limits | Recommend only | `RiskProfile` (UD-01) | RR-09 |
| Daily loss limits | Recommend only | `RiskProfile` (UD-02) | RR-10 |
| Speculative and intraday allocation caps | Recommend only | `RiskProfile` (H-04, UD-13, UD-14) | RR-12, RR-16 |
| Leverage permissions | Recommend only; constant `false` in the MVP | Schema constants | RR-04 |
| Kill-switch behavior | Recommend only | Owner configuration and manual control | Operational control service |
| Promotion of experimental strategies | Recommend only | Owner-signed `PromotionRecord` | Promotion service |

### 4.4 Module dependency rules

- `trader.domain` holds the framework-neutral contracts (§17) and may import only the Python standard library and Pydantic (D-44, NFR-02).
- Framework and vendor libraries (pandas, pyarrow, CCXT, Freqtrade if adopted) are imported only inside adapter or implementation modules, never by `trader.domain`.
- Dependencies point inward: CLI → orchestrator → services → domain. Services communicate through domain contracts, not through framework objects.
- Only `trader.risk` constructs `OrderIntent` objects; only `trader.execution` calls adapters.

---

## 5. Proposed technology stack

### 5.1 Recommended initial stack

The v0.1 list is kept. The v0.2 status of each item is shown in brackets (RECOMMENDATION unless stated).

- **Language:** Python 3.11+ [adopt; RT-01]
- **Trading/backtesting framework:** Freqtrade [evaluate in a time-boxed spike, not a dependency of M1; RT-02, R-03, ADR-003]
- **Optional ML extension:** FreqAI [only after non-ML baselines exist; RT-03, ADR-004]
- **Exchange abstraction:** CCXT where it adds portability [adopt for public market data; trading adapters behind the framework-neutral interface after UD-05; RT-04]
- **Data/config schemas:** Pydantic [adopt v2; RT-05]
- **Local API:** FastAPI [later, P9/P10; RT-07]
- **CLI:** Typer or the framework's native CLI [Typer; RT-06]
- **Storage, MVP:** SQLite plus Parquet for market/features data [adopt; RT-08]
- **Storage, later:** PostgreSQL and object storage [adopt for hosted; RT-08]
- **Testing:** pytest [adopt, plus hypothesis for property tests; RT-09, R-17]
- **Packaging/environment:** `uv` or Poetry, with Docker as a reproducibility option [`uv`; Docker after M1; RT-11, R-17]
- **Observability:** structured JSON logging; Prometheus/Grafana can be added later [JSON logs with correlation IDs in M1; RT-10]
- **Secrets:** local `.env` excluded from Git for the prototype; managed secrets before any hosted deployment [unchanged; M1 needs no secrets]

### 5.2 Why this direction

- Freqtrade provides an existing strategy, backtesting, dry-run, and protection framework. Its value is highest for data download, cross-checking backtest results, and later dry-run against live exchange data.
- FreqAI offers an experimentation path for model training and periodic retraining without requiring a custom ML platform immediately.
- CCXT reduces exchange-specific integration code, but exchange-specific behavior must still be tested.
- Pydantic makes the natural-language-to-configuration boundary explicit and validates all generated configuration before use.
- **v0.2 addition (R-03).** The M1 slice needs the deterministic risk engine to be the only sizing and approval authority and needs the journal to capture the full chain in framework-neutral contracts (D-44, D-46). A small in-house bar-replay simulator behind the `ExecutionAdapter` interface does this with fewer moving parts and faster deterministic tests. Freqtrade stays the leading candidate for a later adapter and as an independent cross-check of benchmark and baseline results (BL-032). Note for the owner: Freqtrade is distributed under the GPL-3.0 licence, which matters if the code is ever redistributed.

### 5.3 Build versus adopt

| Capability | MVP choice (v0.1) | v0.2 recommendation | Reason |
|---|---|---|---|
| Backtesting | Adopt Freqtrade | Build a minimal deterministic bar-replay simulator for M1; evaluate Freqtrade in BL-032 | Keeps the risk engine authoritative and contracts framework-neutral; Freqtrade cross-checks results |
| ML experimentation | Adopt FreqAI initially | Unchanged, after baselines (P8) | Faster model baseline and retraining experiments |
| Exchange connectivity | CCXT or framework adapter | CCXT for public data now; trading adapter after UD-05 | Preserve exchange portability |
| Risk policy | Build custom deterministic module | Unchanged | Core product behavior and safety boundary |
| User interview | Build | Build later (V1 should-have questionnaire; V2 conversation) | CLI and core engine first (D-40) |
| LLM profile interpretation | Build behind schema validation | Unchanged, V2 | Central differentiator but must be constrained |
| Dashboard | Defer or use existing UI first | Defer to V2 | D-41 |
| Trade journal | Build lightweight structured event log | Build, append-only and hash-chained (R-05) | Needed for explanations, audits, and improvement |

### 5.4 Evaluation of the kickoff's recommended technical direction

The verdicts for RT-01 to RT-11 are recorded in `product-requirements.md` §3.4. In summary: all eleven are adopted or kept, with two sequencing changes: Freqtrade (RT-02) is evaluated in a spike instead of being an M1 dependency, and Docker (RT-11) follows M1 as the kickoff itself states.

---

## 6. Core components

### 6.1 Questionnaire and profile service

Responsibilities:

- Ask a versioned set of objective and risk questions (V1 should-have, BL-031). The question set is generated from the `TradingProfile` and `RiskProfile` schema fields rather than fixed at 16 or 20 questions.
- Support both fixed choices and short natural-language answers.
- Normalize answers into a validated `TradingProfile`.
- Identify contradictions, such as a 5% drawdown limit with an aggressive/high-volatility objective (policy rules PV-01 to PV-10 and RP-01 to RP-12).
- Require explicit resolution of contradictions before activation.
- Preserve the original answers and the normalized output.
- **Profile compiler (new in v0.2):** merge the `TradingProfile`, the selected `RiskProfile`, the eligibility rules, and, in backtests only, an experiment parameter set into a `CompiledProfile`; record the provenance of every effective value (`approved`, `hypothesis`, `experiment`); compute `config_hash`; emit a blocker report for every required `TBD` value (R-02).

The v0.1 example profile (`paper_balance_usd: 10000`, `frequency: several_per_day`, `symbols: BTC/USD`) is superseded by `trading-profile.schema.yaml`. Excerpt of the v0.2 Balanced profile:

```yaml
profile_id: balanced-paper
version: 1
status: validated
capital: {paper_capital_usd: 2500, accounting_currency: USD, funds: simulated}   # D-04, D-02
risk_selection: {risk_profile_id: balanced, risk_profile_version: 1}              # D-09
universe: {construction: rules_based, core_assets: [BTC, ETH], instruments_in_scope: [BTC-USD, ETH-USD]}
horizon: {holding_period: adaptive, primary_decision_timeframes: ["1h", "4h"]}    # D-15, D-16
execution: {autonomy_mode: paper_autonomous, per_trade_approval_required: false, leverage_allowed: false}
```

Financial-risk values are not in the `TradingProfile`. They live in the `RiskProfile`, where unresolved values are `TBD`. A profile cannot run in an environment while any value required there is `TBD` (§9.2).

### 6.2 Profile interpreter

The profile interpreter (V2, with the conversational interface) may use an LLM to:

- Translate human goals into proposed structured settings.
- Explain trade-offs in plain English.
- Flag ambiguous or incompatible answers.
- Produce a proposed profile for user review.

It must not:

- Place orders.
- Alter an active profile silently.
- Set missing risk limits using invented defaults.
- Override hard system limits.

All LLM output must pass schema validation and policy validation, and becomes a proposal that follows the resolution procedure in `product-requirements.md` §10.1.

### 6.3 Market data service

Responsibilities:

- Download and cache candle data.
- Retrieve current ticker/order-book information where supported (V1.5).
- Detect missing, duplicated, stale, and out-of-order market data (checks DQ-01 to DQ-12).
- Normalize timestamps to UTC.
- Record data source, retrieval time, and symbol mapping.
- Expose immutable historical snapshots to backtests.

Initial data (V1, D-37): OHLCV candles, volume, volatility and technical features derived from them, spread when available, and exchange fees as cost-model inputs.

Deferred data: order book, cross-asset relationships, and derivatives data (V1.5); news, on-chain metrics, and macroeconomic series (V2); social sentiment and other alternative signals (Experimental). Provider interfaces, identifiers, quality checks, datasets, lineage, and degraded behavior are specified in `data-architecture.md`.

### 6.4 Feature pipeline

Initial features should be transparent and inexpensive:

- rolling returns
- moving-average distance and crossover state
- RSI or a similar bounded momentum feature
- realized volatility
- average true range
- volume change and volume z-score
- drawdown from rolling peak
- market-regime labels

Requirements:

- Fit transformations only on training periods.
- Use walk-forward processing.
- Store feature definitions and versions (`FeatureSet.feature_set_version`, `definitions_hash`).
- Prevent future values from entering current rows (`FeatureSet.max_input_close_time_utc <= as_of_utc`).

### 6.5 Strategy engine

The first system compares simple strategies before relying on ML (ADR-004).

Initial strategy candidates:

1. **Buy-and-hold benchmark** (computed analytically, R-20)
2. **Trend/momentum** (`sma_trend` in M1; time-series momentum in V1)
3. **Mean reversion** (V1)
4. **Volatility breakout** (V1)
5. **Optional ML model** for probability or expected-return ranking (P8, challenger only)

A strategy returns a `SignalCandidate`, not an order. v0.2 example:

```yaml
schema_version: "1.0.0"
signal_id: sig-000123
correlation_id: cor-000123
instrument_id: BTC-USD
timeframe: 4h
decision_time_utc: "2026-10-08T16:00:00Z"
strategy_id: sma_trend
strategy_version: 1.0.0
sleeve: core
side: buy
strength: 1.0
confidence: null
expected_horizon: null          # holding period is adaptive (D-15)
entry_reference_price: "62150.00"
invalidation: {kind: indicator_cross, level: null, reason: SMA_FAST_BELOW_SLOW}
feature_set_id: fs-000123
regime_assessment_id: reg-000123
model_id: null
model_version: null
rationale_codes: [SMA_CROSS_UP]
```

Full semantics are in `strategy-spec.md` §5.

### 6.6 Regime classifier

Possible regimes (v0.1): trending up, trending down, range-bound, high volatility, low volatility, uncertain/stale. v0.2 organizes them on two axes plus a data state (R-08): `trend_state` (trending_up, trending_down, range_bound), `volatility_state` (low, normal, high), and `data_state` (ok, uncertain, stale). See `strategy-spec.md` §3.

For the MVP, use deterministic features and thresholds. An ML-based or AI-assisted regime model can be evaluated later (D-31). Uncertain or stale states block new entries; exits remain allowed.

### 6.7 Risk engine

The risk engine is independent from the strategy and LLM layers. It is the only component that creates `OrderIntent` objects.

Checks include (v0.1 list, all retained): allowed symbol and asset type; spot-only rule; leverage disabled; maximum position size; maximum aggregate exposure; maximum open positions; per-trade risk limit; daily loss limit; portfolio drawdown circuit breaker; stale-data rejection; duplicate-order prevention; minimum liquidity/spread requirement; cooldown after repeated losses or exchange errors; kill-switch state.

**Rule catalogue (v0.2).** Rules are evaluated in order. A failed gate rule (RR-01 to RR-12) stops evaluation; later rules are recorded as `not_evaluated`. Sizing rules (RR-13 to RR-20) clamp (`modified`) or reject. Exits are evaluated against RR-01 to RR-04 and RR-06 to RR-08 only, so a position can always be closed when data is fresh and execution is enabled.

| Rule | Check | Parameters | Reason code on failure | Applies to |
|---|---|---|---|---|
| RR-01 | Profile runnable: valid, declared status permits the environment, not suspended | — | `PROFILE_NOT_RUNNABLE` | Entry, exit |
| RR-02 | Risk configuration resolved for the environment; no experiment values in `paper` | Required-field sets | `RISK_CONFIG_UNRESOLVED` | Entry, exit |
| RR-03 | Execution enabled: kill switch disengaged, autonomy mode `paper_autonomous`, execution flag on | — | `KILL_SWITCH_ENGAGED`, `EXECUTION_DISABLED` | Entry, exit |
| RR-04 | Safety constants: simulated funds, spot only, no leverage, margin, shorting, or withdrawals | Schema constants | `SAFETY_VIOLATION` | Entry, exit |
| RR-05 | Instrument supported: in registry, not Blocked, not disallowed, in profile universe, eligible now, spot | UD-18 thresholds | `ASSET_NOT_SUPPORTED`, `ASSET_BLOCKED`, `ASSET_INELIGIBLE` | Entry |
| RR-06 | Data fresh: latest expected closed candle present and snapshot quality ok | UD-17 grace (paper) | `STALE_DATA`, `DATA_QUALITY_FAILED` | Entry, exit |
| RR-07 | No duplicate: idempotency key unused; no pending (unfilled) market order for the instrument (resting protective stops excluded); entries only when flat | — | `DUPLICATE_ORDER` | Entry, exit |
| RR-08 | Spot long-only: buys within available cash, sells within held quantity | — | `SPOT_CONSTRAINT_VIOLATION` | Entry, exit |
| RR-09 | Drawdown circuit breaker not open; opens (latched) when drawdown reaches the threshold | UD-01 | `CIRCUIT_BREAKER_OPEN` | Entry |
| RR-10 | Daily loss limit not reached for the current UTC day | UD-02 | `DAILY_LOSS_LIMIT` | Entry |
| RR-11 | No active cooldown for the strategy-instrument pair | UD-17 | `COOLDOWN_ACTIVE` | Entry |
| RR-12 | Intraday sleeve enabled and within sleeve limits (intraday signals only) | UD-14 | `INTRADAY_SLEEVE_DISABLED` | Entry |
| RR-13 | Loss-scaling multiplier from the size-reduction schedule | UD-15 | (multiplier 0 is handled by RR-09) | Entry |
| RR-14 | Risk-per-trade budget divided by hard-stop distance | UD-03, UD-16 | `RISK_CONFIG_UNRESOLVED` if inputs missing | Entry |
| RR-15 | Tier per-asset concentration cap (aggregate across sleeves) | H-01 to H-03, UD-13 | `CONCENTRATION_LIMIT` (no headroom) | Entry |
| RR-16 | Speculative total cap | H-04, UD-13 | `CONCENTRATION_LIMIT` | Entry |
| RR-17 | Total exposure cap | UD-12 | `EXPOSURE_LIMIT` | Entry |
| RR-18 | Reserve floor after order, fees, and committed cash | UD-04 | `RESERVE_LIMIT` | Entry |
| RR-19 | Maximum open positions, including pending entries | UD-12 | `MAX_POSITIONS` | Entry |
| RR-20 | Minimum order notional after clamping | Venue/simulator setting | `SIZE_BELOW_MINIMUM` | Entry |

Output (v0.2):

```yaml
risk_decision_id: rsk-000456
correlation_id: cor-000123
ensemble_decision_id: ens-000123
status: approved | modified | rejected
approved_quantity: "0.01234"
approved_notional_usd: "767.41"
binding_constraint: TIER_CAP          # set when status is modified
rule_results: [{rule_id: RR-01, outcome: pass}, ...]
reason_codes: []
config_hash: "sha256:..."
risk_engine_version: 1.0.0
```

### 6.8 Portfolio and position-sizing service

Initial sizing uses deterministic rules rather than LLM output.

Candidate approaches to test (v0.1): fixed fractional allocation; volatility-targeted sizing; capped inverse-volatility sizing; equal weight across approved positions.

V1 algorithm (fixed fractional on risk, RR-13 to RR-20): notional = equity × risk per trade × loss-scaling multiplier ÷ stop distance, then clamped by tier cap, speculative cap, total exposure, reserve floor, and available cash, and rounded down to the instrument's quantity step. Details and the AI boundary are in `strategy-spec.md` §9. No sizing method may exceed profile or global hard limits.

The portfolio service maintains cash, committed cash for pending orders, positions, mark-to-market equity, the high-water mark, drawdown, UTC-day start equity, and exposure by instrument, tier, and sleeve (`PositionSnapshot`).

### 6.9 Execution service

Responsibilities:

- Accept only approved `OrderIntent` objects.
- Route orders to paper/dry-run/simulated adapters registered in an allowlist (FR-EXEC-01).
- Generate idempotency keys (deterministic; §17.2 `OrderIntent`).
- Track accepted, open, partially filled, filled, canceled, rejected, expired, and error states.
- Reconcile internal positions against exchange/simulator state after every fill.
- Retry only safe and idempotent operations.
- Record latency and expected-versus-realized fill price.

**Execution gate (v0.2).** Immediately before submission, the gate re-checks every intent:

| Gate | Check | Reason code |
|---|---|---|
| EG-01 | A `RiskDecision` with status `approved` or `modified` exists for the intent; instrument and side match; quantity does not exceed `approved_quantity`; notional estimate does not exceed `approved_notional_usd` | `RISK_DECISION_MISSING`, `RISK_DECISION_MISMATCH`, `EXCESSIVE_SIZE` |
| EG-02 | Kill switch disengaged and execution enabled at submission time. Single exemption: the protective stop attached to an entry that has already filled, so a filled position is never left without its stop | `KILL_SWITCH_ENGAGED`, `EXECUTION_DISABLED` |
| EG-03 | Idempotency key not used before | `DUPLICATE_ORDER` |
| EG-04 | `funds` is `simulated` and the adapter is in the simulated/paper allowlist | `ADAPTER_NOT_ALLOWED` |
| EG-05 | Intent not expired (`valid_until_utc`) | `INTENT_EXPIRED` |

Adapter interface (framework-neutral; types from §17):

```python
class ExecutionAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    def validate_order(self, intent: OrderIntent) -> list[str]: ...
    def submit_order(self, intent: OrderIntent) -> ExecutionReport: ...
    def cancel_order(self, order_intent_id: str) -> ExecutionReport: ...
    def get_order(self, order_intent_id: str) -> ExecutionReport: ...
    def list_open_orders(self) -> list[ExecutionReport]: ...
    def get_balances(self) -> dict[str, Decimal]: ...
```

M1 implements `SimulatedExecutionAdapter`: market orders fill at the next bar's open adjusted by slippage; fees are charged on notional; attached protective stops trigger intrabar when the bar's low reaches the stop and fill at the stop price, or at the open if the bar opens below it; fills never fall outside the bar's range; a minimum notional is enforced.

### 6.10 Trade journal and explanation service

Every cycle records: market timestamp; data freshness; active profile version; strategy and model version; market regime; candidate signal; ensemble decision; risk decision; proposed and executed order; expected and realized price; fees and assumed slippage; entry/exit rationale; profit and loss; maximum adverse/favorable excursion; rejection or failure reason.

v0.2 additions (R-05): the journal is append-only (database triggers reject updates and deletes) and hash-chained (`event_hash` covers the previous hash and the canonical event content). Order intents are journaled before submission; if the write fails, nothing is submitted. `trader journal verify` recomputes the chain and checks D-36 traceability for every order.

The human-readable explanation must be generated from recorded facts, not used as a source of truth. V1 uses deterministic templates keyed by reason and rationale codes (R-13); AI-written explanations (V2) must cite journal event IDs.

### 6.11 Evaluation service

Required evaluation views: total and annualized return; benchmark-relative return; maximum drawdown; volatility; downside deviation; Sharpe-like and Sortino-like measures; profit factor; win rate and payoff ratio; turnover; fee and slippage burden; exposure by asset; number of trades; average holding period; rejected-signal counts by risk rule; performance by market regime. Metric definitions are in `experiment-plan.md` §9.

A strategy is not promoted based on one metric or one backtest window.

### 6.12 Ensemble layer (new in v0.2)

Turns the signals of eligible strategies into one `EnsembleDecision` per instrument and decision time (D-29 step 5). It applies the regime gate, the conflict rules (R-01 until UD-07 is resolved), and the position-state logic (enter only when flat, exit only when long). It never sizes. M1 uses a single-strategy pass-through that still produces the contract, so later phases change the implementation, not the pipeline shape.

### 6.13 Universe and eligibility service (new in v0.2)

Maintains the asset registry (tiers, aliases, approvals), evaluates eligibility criteria for every asset including manual allowlist entries (D-24, D-25), and publishes a point-in-time `UniverseSnapshot` per cycle. AI may rank eligible assets (D-31) but cannot change eligibility. Specified in `data-architecture.md` §4.

### 6.14 Operational control service (new in v0.2)

Holds the latched and timed controls that the risk engine reads: the kill switch (persisted in `data/state/operational.sqlite`), the circuit-breaker state, the UTC-day loss lockout, and cooldowns. Only owner commands can disengage the kill switch or reset the breaker (R-15, R-18). Automated components can only engage.

### 6.15 Research and promotion service (new in v0.2)

Runs experiments in the research environment, writes `ExperimentRecord` files, enforces holdout sealing, and records promotions as owner-approved `PromotionRecord` objects. It builds champion bundles for the active paper trader (§8.6) and never promotes automatically (D-43).

---

## 7. Data flow

v0.2 extends this section to cover data, control, and execution flows.

### 7.1 Profile creation

```text
Owner-authored TradingProfile YAML (M1)  |  questionnaire answers (V1)  |  chat directive (V2)
  -> schema validation (JSON Schema / Pydantic)
  -> policy validation and contradiction checks (PV-01..PV-10, RP-01..RP-12)
  -> user-readable summary and blocker report (UD IDs for every required TBD)
  -> versioned TradingProfile (declared status re-verified at every load)
  -> profile compiler + selected RiskProfile + eligibility rules (+ experiment parameter set, backtest only)
  -> CompiledProfile with per-value provenance and config_hash
```

### 7.2 Trading cycle (control flow)

One decision cycle runs at each bar close of the decision timeframe, in a deterministic instrument order. Stage numbers match D-29.

```text
Schedule (bar close; simulated clock in backtests, wall clock in paper)
  1. retrieve market data -> quality and freshness checks -> MarketSnapshot      [D-29 step 1]
     -> UniverseSnapshot (eligibility at this time)
     -> build features -> FeatureSet
  2. classify regime -> RegimeAssessment                                          [step 2]
  3. determine eligible strategies for the regime                                 [step 3]
  4. generate candidate signals -> SignalCandidate[]                              [step 4]
  5. combine through the ensemble layer -> EnsembleDecision                       [step 5]
  6. apply portfolio context and run risk rules RR-01..RR-12 -> RiskDecision      [step 6]
  7. size deterministically RR-13..RR-20 -> OrderIntent (journaled first)         [step 7]
  8. execution gate EG-01..EG-05 -> paper/simulated adapter -> ExecutionReport    [step 8]
     -> portfolio update -> reconciliation -> PositionSnapshot
  9. journal every object above as TradeEvent; metrics; explanation               [step 9]
```

### 7.3 Improvement cycle

```text
Historical snapshot (immutable datasets)
  -> train/calibrate if applicable (training folds only)
  -> walk-forward backtest
  -> compare with baselines (cash, buy-and-hold, equal-weight, simple trend)
  -> inspect drawdowns and regime behavior; robustness and overfit checks (OF-01..OF-12)
  -> record experiment (ExperimentRecord)
  -> owner approves or rejects strategy version (PromotionRecord; never automatic)
  -> shadow run in observe_only mode
  -> paper-trading deployment as champion
```

### 7.4 Market-data flow (new in v0.2)

```text
Provider (CSV | synthetic | CCXT public OHLCV with explicit venue)
  -> raw files (data/raw/...)
  -> normalization (UTC, canonical instrument_id, open-time convention)
  -> quality checks DQ-01..DQ-12 -> quality report
  -> immutable dataset (Parquet) + DatasetManifest (content hash = dataset_id)
  -> snapshot builder at decision time t: only candles with close_time_utc <= t
```

### 7.5 Execution flow (new in v0.2)

```text
RiskDecision (approved | modified)
  -> OrderIntent (idempotency key = hash of config_hash, instrument, side, purpose, decision time)
  -> journal ORDER_INTENT_CREATED (must succeed)
  -> execution gate EG-01..EG-05 (reject -> ORDER_REJECTED event)
  -> adapter.submit_order -> ExecutionReport (accepted/filled/rejected/error)
  -> ledger update -> reconciliation (mismatch -> kill switch auto-engages)
  -> attached protective stop registered with the adapter (entries)
  -> journal ORDER_FILLED / POSITION_UPDATED
```

### 7.6 Loss-response flow (new in v0.2; D-12)

```text
every cycle:   reassess signals and regime (stages 1-5)                          [D-12 step 1]
every entry:   multiplier = schedule(drawdown / breaker threshold)  (UD-15)     [step 2]
always:        hard limits RR-09..RR-20 override strategies and models          [step 3]
at threshold:  circuit breaker opens -> no new entries until owner reset        [step 4]
daily:         daily loss limit -> no new entries until next UTC day
exits:         remain allowed whenever data is fresh and execution is enabled
```

### 7.7 Traceability chain (D-36)

```text
OrderIntent
  ├── signal_ids ───────────────> SignalCandidate (strategy_id, strategy_version, model_version, feature_set_id)
  ├── ensemble_decision_id ─────> EnsembleDecision (ensemble_version, weighting_method)
  ├── risk_decision_id ─────────> RiskDecision (rule_results, risk_engine_version)
  ├── config_hash ──────────────> CompiledProfile (profile versions, provenance of every value)
  └── market_data_timestamp_utc + snapshot dataset_ids -> MarketSnapshot / DatasetManifest
```

---

## 8. Training and backtesting policy

v0.2 extends this section to cover the separation between the research environment and the active paper trader. The full method is in `experiment-plan.md`.

### 8.1 Dataset separation

Use time-ordered splits: training period; validation period; untouched test period; rolling walk-forward windows. Random train/test splitting is inappropriate for the primary time-series evaluation. The recommended design (R-11) is in `experiment-plan.md` §3 and §4.

### 8.2 Simulation assumptions

Each backtest must include: exchange fees; conservative slippage assumption; execution delay assumption (decide at bar close, fill at next bar open or later); minimum order size; unavailable or missing candle handling (treated as stale); no fills outside observable prices; trading-pair availability for the tested period. Cost scenarios are in `experiment-plan.md` §6.

### 8.3 Baselines

Every model should be compared with: holding cash; buy and hold for each selected asset; a simple moving-average trend strategy; a simple equal-weight portfolio where relevant; and a random-entry control with matched trade count (v0.2 addition).

### 8.4 Promotion criteria

Promotion should require: acceptable maximum drawdown; positive risk-adjusted performance after fees; stability across multiple market regimes; performance that is not dependent on a few outlier trades; no evidence of leakage; successful paper-trading behavior; reproducible results from a clean environment. These are gates G-01 to G-11 in `strategy-spec.md` §12. Exact thresholds are UD-08.

### 8.5 Research environment versus active paper trader (new in v0.2; D-42, D-43)

| Aspect | Research environment | Active paper trader |
|---|---|---|
| Location | Local machine (V1) | Local forward session (V1), hosted (P10) |
| Purpose | Development, backtesting, experiments, strategy research | Continuous signal generation, risk checks, simulated execution, journaling, monitoring, alerts |
| Strategies and models | Any registered version, including challengers | Only the champion bundle backed by a `PromotionRecord` |
| Risk values | Approved and hypothesis values; experiment parameter sets allowed (backtest only) | Approved and hypothesis values only; experiment values refused (RR-02) |
| Profile status required | `validated` or `active` | `active` |
| Clock | Simulated (deterministic) | Wall clock (UTC) |
| Data | Immutable datasets | Live public candles, validated per cycle |
| Kill switch | Run-scoped (tests can engage it) | Persisted operational state |

### 8.6 Champion bundles and promotion (new in v0.2)

A champion bundle is an immutable artifact containing: strategy and ensemble identifiers and versions; model artifacts and hashes (if any); the `TradingProfile` and `RiskProfile` versions and hashes; the code revision; and the `PromotionRecord` (owner, date, evidence experiment IDs, gate results). The active paper trader refuses to load a bundle without a matching `PromotionRecord`. Challengers may run beside the champion in `observe_only` mode (shadow) to collect evidence. Lifecycle states are defined in `strategy-spec.md` §11.

---

## 9. Security and operational controls

v0.2 extends this section to cover failure handling.

### 9.1 Key controls

- No credentials are needed for M1; public market data and the internal simulator need none.
- Use sandbox/paper credentials for the MVP if an external paper adapter is chosen (UD-05).
- Never commit secrets.
- Separate data-only and trading credentials when possible.
- Never grant withdrawal permission.
- Restrict API keys by IP when supported.
- Rotate compromised keys immediately.

### 9.2 Kill switches

The system must stop new orders when:

- daily loss limit is reached
- maximum drawdown is reached
- market data is stale
- balances do not reconcile
- repeated API failures occur
- clock skew exceeds tolerance
- risk configuration is invalid or unavailable
- an operator activates the manual kill switch

Closing existing positions after a halt should be governed by a separate, explicit liquidation policy, not improvised by the model (UD-19).

**v0.2 halt mechanisms.** The v0.1 conditions map to five deterministic mechanisms with different scopes and reset rules:

| Mechanism | Triggered by | Blocks | Reset | Source |
|---|---|---|---|---|
| Per-cycle gate | Stale data, data-quality failure, invalid or unresolved configuration | New orders for the affected instrument or run | Automatic when the input is valid again | P-09, RR-02, RR-06 |
| Daily loss lockout | Daily loss limit reached (UD-02) | New entries | Automatic at 00:00 UTC | RR-10 |
| Circuit breaker | Portfolio drawdown reaches the breaker (UD-01) | New entries | Owner command with reason; rebases the high-water mark (R-18) | D-12 step 4, RR-09 |
| Cooldown | Consecutive losses for a strategy-instrument pair (UD-17) | New entries for that pair | Automatic after the duration | RR-11 |
| Kill switch | Manual command; or auto-engage on reconciliation mismatch, repeated execution errors (UD-17), clock skew beyond tolerance, journal write failure, configuration becoming invalid mid-session, persistent stale data | All new orders | Owner command with reason only (R-15) | D-35, RR-03, EG-02 |

Kill-switch rules: engaging always succeeds, even when configuration is invalid; the state persists across restarts; no automated component can disengage it; until UD-19 is resolved, open positions and their attached protective stops are left unchanged and nothing is liquidated automatically.

### 9.3 Auditability

- Append-only decision events (hash-chained, R-05).
- Correlation IDs across signal, risk, order, fill, and position events (`cycle_id`, `correlation_id`).
- UTC timestamps.
- Code/config/model version attached to decisions (`code_revision`, `config_hash`, strategy and model versions).
- No silent configuration mutation (version increments; content hashes in every run).

### 9.4 Failure-mode handling (new in v0.2)

| ID | Failure | Detection | Immediate response | Recovery | Alert level |
|---|---|---|---|---|---|
| FM-01 | Market-data provider unavailable | Fetch error or timeout | No new orders for affected instruments; `DATA_STALE` event | Automatic when data returns; kill switch after N stale cycles (UD-17) | Warning, then critical |
| FM-02 | Stale data | Freshness check (RR-06) | Reject with `STALE_DATA` | Automatic | Warning |
| FM-03 | Data-quality failure | DQ checks | Dataset unusable or cycle skipped | Fix source; new dataset ID | Warning |
| FM-04 | Clock skew beyond tolerance | Comparison with reference time (paper) | Kill switch auto-engages | Owner disengages after fixing | Critical |
| FM-05 | Risk configuration invalid or unresolved | Compiler, RR-02 | Refuse to start or reject | Owner fixes configuration (new version) | Critical in paper |
| FM-06 | Execution adapter error | Exception or error report | Journal; count consecutive errors | Kill switch at threshold (UD-17) | Warning, then critical |
| FM-07 | Reconciliation mismatch | Post-fill reconciliation | Kill switch auto-engages | Owner investigation | Critical |
| FM-08 | Journal write failure | Exception on write | Nothing submitted (journal before act); kill switch (paper) or run fails (backtest) | Owner | Critical |
| FM-09 | Duplicate scheduling or replay | Idempotency key | `DUPLICATE_ORDER` | None needed | Info |
| FM-10 | Process crash or restart | Supervisor | Reload state from journal and operational store; kill switch state preserved; reconcile before trading | Automatic | Warning |
| FM-11 | Daily loss limit reached | RR-10 | Lockout until 00:00 UTC | Automatic | Warning |
| FM-12 | Circuit breaker reached | RR-09 | No new entries (latched) | Owner reset | Critical |
| FM-13 | Repeated losses | RR-11 | Cooldown | Automatic | Info |
| FM-14 | Storage full or unavailable | Write errors | As FM-08 | Owner | Critical |
| FM-15 | Profile or status changed mid-session | Hash check per cycle | Session suspends; no new orders | Owner re-activates | Critical |

Alert taxonomy: **critical** (kill switch engaged, breaker open, reconciliation or journal failure, clock skew), **warning** (stale data, adapter errors below threshold, daily lockout), **info** (cooldowns, daily summary). In V1 alerts go to the console and a log file; hosted channels are UD-10.

### 9.5 Operational procedures

The runbook (`docs/operations/runbook.md`, created in P5) covers: engaging and disengaging the kill switch; resetting the circuit breaker; activating and suspending a profile; recovering from a crash; verifying the journal; and resolving a UD item (`product-requirements.md` §10.1).

---

## 10. Suggested repository structure

v0.2 extends this section with deployment views.

### 10.1 Local deployment view (V1)

```text
Owner laptop (macOS / Linux / Windows, Python 3.11+, uv)
  trader CLI (Typer)
    ├── research environment: backtests, experiments, reports (simulated clock)
    └── local forward paper session (V1, BL-027): scheduler + same pipeline (wall clock)
  data/
    ├── raw/            downloaded or imported files
    ├── datasets/       immutable Parquet datasets + manifests
    ├── journal/        journal.sqlite (append-only, hash-chained)
    ├── state/          operational.sqlite (kill switch, breaker, activations)
    ├── reports/        per-run report.json and report.md
    └── experiments/    ExperimentRecord JSON
  network: public market-data endpoints only (optional); no trading keys
```

### 10.2 Hosted deployment view (later; P10, UD-09, UD-10, UD-11)

```text
Research environment (local)
  -> builds champion bundle + PromotionRecord (owner-approved)
  -> artifact store (object storage)

Hosted paper trader (single always-on instance; topology UD-09)
  scheduler -> market-data fetcher (public data) -> decision pipeline
    -> deterministic risk engine -> execution gate -> simulated/paper adapter
  journal database (PostgreSQL) + object storage (datasets, reports)
  operational state (kill switch, breaker) persisted in the database
  alerting (channels UD-10) ; monitoring (JSON logs; metrics later)
  owner control plane: authenticated CLI/API for status and kill switch only
  secrets manager (only if an external paper adapter needs keys; no withdrawal permission)
```

Rules: the hosted trader loads only promoted bundles; it exposes no endpoint that places arbitrary orders; the kill switch is reachable even if the trading process is unhealthy; retention follows UD-11.

### 10.3 Repository structure

```text
ai-crypto-trader/
├── README.md
├── BLOCKERS.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── configs/
│   ├── profiles/          # TradingProfile YAML
│   ├── risk/              # RiskProfile YAML (conservative, balanced, aggressive)
│   ├── universe/          # asset registry and eligibility rules
│   ├── strategies/        # strategy registry entries
│   ├── costs/             # cost scenarios (low, base, stress)
│   └── environments/      # backtest and paper settings
├── experiments/           # experiment definitions (inputs)
├── schemas/               # trading-profile and risk-profile schema files
├── docs/
│   ├── spec/              # this specification package
│   ├── decisions/         # ADRs
│   ├── experiments/       # human-readable experiment records
│   └── operations/        # runbook, threat model
├── src/
│   └── trader/
│       ├── domain/        # framework-neutral contracts (stdlib + Pydantic only)
│       ├── common/        # clock, ids, canonical JSON, hashing, logging
│       ├── profiles/      # loader, validator, compiler
│       ├── universe/      # registry, eligibility
│       ├── data/          # providers, quality, datasets, snapshots
│       ├── features/
│       ├── regimes/
│       ├── strategies/
│       ├── ensemble/
│       ├── risk/          # engine, rules, sizing, controls
│       ├── portfolio/
│       ├── execution/     # gate, service
│       │   └── adapters/  # simulated (M1); others only after UD-05
│       ├── journal/
│       ├── evaluation/
│       ├── research/
│       ├── pipeline/      # decision cycle
│       ├── backtest/      # bar-replay runner
│       └── cli/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── safety/
│   └── fixtures/
├── scripts/
└── data/                  # git-ignored
```

`data/`, model artifacts, local databases, logs, and secrets should be excluded from source control unless explicitly sanitized.

---

## 11. MVP implementation sequence

Moved to `execution-plan.md` in v0.2, which defines phases P0 to P10 with dependencies, outputs, test requirements, and exit criteria. Mapping from v0.1:

| v0.1 phase | v0.2 phase(s) |
|---|---|
| Phase 0: Foundation | P0 Foundation |
| Phase 1: Profile and risk contract | P1 Schemas/profile compiler (risk rules implemented in P4) |
| Phase 2: Data and baseline backtest | P2 Data pipeline, P3 Baseline backtesting |
| Phase 3: Risk and paper execution | P4 Deterministic risk engine, P5 Paper execution |
| Phase 4: Journal and explanations | P6 Journal and evaluation |
| Phase 5: Strategy comparison | P7 Ensemble/regime layer (with walk-forward from P6) |
| Phase 6: Optional ML experiment | P8 Optional ML challenger |
| (new) | P9 Dashboard/conversation, P10 Hosted paper deployment |

The v0.1 Phase 0 item "Choose the first paper/sandbox adapter" is now UD-05 and does not block P0 to P4.

## 12. Initial backlog for the Code session

Moved to `execution-plan.md` §5 (prioritized V1 backlog BL-001 to BL-047). Every v0.1 item is carried forward:

| v0.1 item | v0.2 backlog |
|---|---|
| Initialize repository and environment | BL-001 |
| Install and verify the chosen trading framework | BL-032 (Freqtrade spike; not an M1 dependency) |
| Pydantic models for `TradingProfile`, `SignalCandidate`, `RiskDecision`, `OrderIntent`, `TradeEvent` | BL-003 (all 13 contracts) |
| Add the 16-question interview as a versioned questionnaire | BL-031 (V1 should-have; questions generated from the schema) |
| Prevent profile activation while required values are missing | BL-005 |
| Add BTC/USD and ETH/USD configuration | BL-006 (canonical `BTC-USD`, `ETH-USD`) |
| Download sample historical data | BL-007 |
| Implement buy-and-hold benchmark | BL-011 |
| Implement a basic trend strategy | BL-012 |
| Add fee and slippage settings | BL-006, BL-014 |
| Add basic maximum-position and maximum-drawdown rules | BL-013 |
| Run the system in dry-run or paper mode only | BL-014, BL-017 |
| Save a machine-readable trade journal | BL-016 |
| Generate an initial backtest report | BL-018 |
| Add mean-reversion baseline; add volatility-breakout baseline | BL-022 |
| Add regime classification | BL-023 |
| Add structured JSON logs and correlation IDs | BL-002 (moved into M1) |
| Add a manual kill-switch command | BL-019 (moved into M1) |
| Add data-staleness and balance-reconciliation checks | BL-013, BL-014 (M1); BL-027 (forward paper) |
| Add walk-forward evaluation script | BL-025 |
| Add FreqAI experiment | BL-040 |
| Add dashboard/API | BL-041, BL-042 |
| Add news, sentiment, or on-chain feature experiments | BL-045, BL-046 |
| Add hosted deployment design | BL-044 |
| Conduct production threat model | BL-044 covers the hosted paper threat model; a real-money threat model is outside this program |
| Define separate real-money readiness gates | Outside this program (D-02, D-03); requires a separate production-readiness review |

---

## 13. Open questions requiring owner decisions

v0.2 reconciles the twenty v0.1 questions with the approved decisions. Remaining open items are tracked as UD IDs in `product-requirements.md` §10.

| # | v0.1 question | v0.2 status |
|---|---|---|
| 1 | Intended future capital range | Deferred: real money is out of scope (D-02, D-03) |
| 2 | Experimental loss tolerance | Partly resolved: simulated $2,500 (D-04); profile loss limits UD-01, UD-02 |
| 3 | Primary objective | Resolved: D-05 |
| 4 | Definition of a successful result | Open: UD-21 |
| 5 | Required response to a 10% weekly decline | Resolved in principle by hybrid loss handling (D-12); thresholds UD-01, UD-02, UD-15 |
| 6 | Maximum acceptable portfolio drawdown | Profile-dependent (D-11); values UD-01 |
| 7 | Leverage policy | Resolved: no leverage (D-03) |
| 8 | Initial asset universe | Resolved: rules-based tiers (D-22 to D-26); slice BTC and ETH (H-05); lists UD-06 |
| 9 | Base/quote currency preference | Partly resolved: USD accounting (A-02); venue quote currency UD-20 |
| 10 | Spot versus derivatives scope | Resolved: spot only; derivatives data read-only in V1.5 (D-37) |
| 11 | Desired trade frequency | Resolved: adaptive, 1h and 4h decision timeframes (D-15, D-16); no HFT (D-21) |
| 12 | Typical holding period | Resolved: roughly one hour through several days (D-17) |
| 13 | Whether multiple simultaneous positions are allowed | Resolved in principle (D-27 concentration caps imply several positions); maximum UD-12 |
| 14 | Desired autonomy model | Resolved: autonomous in paper after deterministic approval (D-33, D-34) |
| 15 | Permitted data sources | Resolved: progressive provider architecture (D-37, D-38) |
| 16 | Whether every trade requires a generated explanation | Partly resolved: complete chain journaled (D-29 step 9); default `every_decision` is R-13 |
| 17 | Preferred exchange or paper environment | Open: UD-05, UD-20 |
| 18 | Local-only versus hosted operation | Resolved: hybrid (D-42); provider and topology UD-09 |
| 19 | CLI, web API, or both first | Resolved: CLI first (D-40); API later (RT-07) |
| 20 | Human approval in the order path after paper testing | Resolved for paper: no approval click (D-34); anything beyond paper is out of scope |

v0.1 inconsistency noted: §12 referred to a "16-question interview" while §13 listed 20 questions. In v0.2 the questionnaire is generated from the schema fields (§6.1), so no fixed count is needed.

---

## 14. Architecture decision records

ADR-001 to ADR-004 are carried from v0.1. ADR-005 to ADR-015 record approved decisions. ADR-016 to ADR-018 are proposals made in v0.2. Full ADR files are created under `docs/decisions/` in P0.

### ADR-001: Paper trading is the initial execution mode

- **Status:** Accepted
- **Decision:** The MVP executes only through dry-run, paper, or sandbox environments with simulated funds (D-02).
- **Reason:** Enables end-to-end testing without exposing capital while order state, retries, risk rules, and monitoring are immature.
- **Consequence:** Paper results may differ from live execution; production readiness requires separate analysis.

### ADR-002: LLM output cannot directly create executable orders

- **Status:** Accepted (amended by ADR-008 in v0.2)
- **Decision:** LLM output is limited to proposed profiles, explanations, and research assistance. It must pass schemas and deterministic policy checks. v0.2 amendment: AI and models may also directly influence the D-31 areas through typed contracts (`RegimeAssessment`, `EnsembleDecision`, asset ranking), but still cannot create orders or set any D-32 item.
- **Reason:** LLM output can be inconsistent and should not control financial side effects directly.
- **Consequence:** More explicit contracts and adapters are required, but behavior is testable and auditable.

### ADR-003: Freqtrade/FreqAI will be evaluated before a custom engine

- **Status:** Proposed
- **Decision:** Prototype using the framework's backtesting/dry-run capabilities, then replace only components that create a demonstrated limitation.
- **v0.2 recommendation (R-03):** Implement the M1 slice with a minimal in-house deterministic bar-replay simulator behind the `ExecutionAdapter` interface, and run a time-boxed Freqtrade spike (BL-032) that reproduces the buy-and-hold and `sma_trend` results on the same datasets. Adopt Freqtrade as an adapter or cross-check if the spike shows a clear benefit.
- **Reason:** Accelerates development and creates a usable baseline, while keeping the risk engine authoritative and contracts framework-neutral.
- **Consequence:** The internal domain contracts remain framework-neutral; the owner decides this ADR after BL-032.

### ADR-004: Baseline strategies precede ML

- **Status:** Accepted
- **Decision:** Implement buy-and-hold and simple systematic strategies before ML; FreqAI only after non-ML baselines exist (RT-03).
- **Reason:** ML must demonstrate incremental value against simpler, more interpretable alternatives.
- **Consequence:** The first useful prototype will not depend on model training.

### ADR-005: Hybrid risk-profile model with deterministic final authority

- **Status:** Accepted (D-08 to D-14)
- **Decision:** The owner selects Conservative, Balanced, or Aggressive (initially Balanced). The system adapts only inside the selected profile's boundaries. Loss handling is hybrid (reassess, reduce size, hard overrides, circuit breaker). Deterministic code has final authority; AI and ML may recommend but not bypass hard limits.
- **Consequence:** All limits live in versioned `RiskProfile` files; unresolved values are `TBD` (UD-01 to UD-04, UD-12 to UD-19).

### ADR-006: Regime-aware ensemble; no single opaque model has total control

- **Status:** Accepted (D-29, D-30)
- **Decision:** The nine-stage pipeline in §7.2. Every model output passes through the ensemble contract and the risk engine.
- **Consequence:** M1 implements pass-through stages so the pipeline shape is stable.

### ADR-007: Autonomous paper execution with a manual kill switch and full traceability

- **Status:** Accepted (D-33 to D-36)
- **Decision:** In paper mode, approved trades execute automatically with no approval click; a manual kill switch always exists; every order is traceable to its signal, versions, risk decision, configuration, and market-data timestamp.

### ADR-008: AI authority boundary

- **Status:** Accepted (D-14, D-31, D-32)
- **Decision:** The authority matrix in §4.3.

### ADR-009: Champion/challenger separation with explicit promotion

- **Status:** Accepted (D-43)
- **Decision:** Experiments run in the research environment; only owner-promoted versions enter the active paper trader; promotion is never automatic. Thresholds are UD-08.

### ADR-010: Progressive data-provider architecture

- **Status:** Accepted (D-37, D-38)
- **Decision:** Provider interfaces for V1, V1.5, V2, and Experimental sources; V1 runs with V1 providers only.

### ADR-011: Tiered, rules-based universe with eligibility checks for every asset

- **Status:** Accepted (D-22 to D-28)
- **Decision:** Core, Major, Speculative, and Blocked tiers; manual allowlist subject to eligibility; profile- and tier-dependent concentration limits; Balanced caps H-01 to H-04 are hypotheses.

### ADR-012: Isolated, capped intraday sleeve; high-frequency and latency arbitrage excluded

- **Status:** Accepted (D-18 to D-21)
- **Decision:** Minute-level data refines 1h/4h decisions or powers separately approved intraday strategies in an isolated, capped sleeve with stricter evaluation; caps of 5%, 10%, 15%, and 20% are tested; the selected cap is UD-14.

### ADR-013: CLI and core engine first

- **Status:** Accepted (D-39 to D-41)
- **Decision:** The CLI and core engine are built first; dashboard and conversational interface follow and never block the pipeline.

### ADR-014: Hybrid deployment

- **Status:** Accepted direction (D-42); provider and topology UD-09
- **Decision:** Local environment for development and research; later a continuously running hosted paper trader.

### ADR-015: Framework-neutral domain contracts

- **Status:** Accepted (D-44, D-45)
- **Decision:** The thirteen contracts in §17 live in `trader.domain` with no framework imports.

### ADR-016: Unresolved values fail closed; experiment parameter sets only in research backtests

- **Status:** Proposed (R-02)
- **Decision:** Every risk value carries a provenance status (`approved`, `hypothesis`, `unresolved`). A required `TBD` value blocks the run (exit code 3) with its UD ID. In backtests only, an experiment parameter set may supply values for `unresolved` or `hypothesis` fields; such values are labelled `experiment` in the `CompiledProfile`, the journal, and every report. Experiment values are refused in the `paper` environment and can never change approved values or safety constants.
- **Reason:** Lets the M1 slice run end to end and lets experiments produce evidence for UD decisions, without inventing profile values.

### ADR-017: Decimal arithmetic and UTC-only time

- **Status:** Proposed (R-04, R-07)
- **Decision:** Money and quantities use `Decimal` with documented rounding (quantities round down to the instrument step; USD amounts quantized to cents for reporting only). All timestamps are timezone-aware UTC; candles are labelled by open time and become available at close time.

### ADR-018: Append-only, hash-chained journal with journal-before-act

- **Status:** Proposed (R-05)
- **Decision:** SQLite triggers forbid updates and deletes; each event stores the previous event's hash; order intents are written before submission.

---

## 15. Experiment record template

Moved to `experiment-plan.md` §13 (expanded with experiment parameters, provenance, overfit checks, and holdout access). Records are still stored under `docs/experiments/` (human-readable) and `data/experiments/` (machine-readable `ExperimentRecord`).

## 16. Definition of done for the initial prototype

Superseded by the V1 acceptance criteria in `product-requirements.md` §11 and the definition of done in `code-session-handoff.md` §11. Mapping of the v0.1 bullets:

| v0.1 definition-of-done bullet | v0.2 acceptance criterion |
|---|---|
| A user can complete the questionnaire and generate a valid profile | AC-01 (authored profile in M1); questionnaire moved to V1 should-have (BL-031) per D-40 |
| Incomplete or contradictory profiles are blocked | AC-02, AC-03 |
| Historical BTC and ETH data can be downloaded and validated | AC-05 (CSV import or optional public download; venue UD-20) |
| At least two baselines can be backtested reproducibly | AC-06, AC-07, AC-16 |
| Fees and slippage are included | AC-15 |
| Candidate signals pass through a deterministic risk engine | AC-08 to AC-13 |
| Approved orders execute only in paper/dry-run/sandbox mode | AC-17 |
| Every signal, rejection, order, and fill is journaled | AC-14 |
| A report compares results with buy-and-hold and shows maximum drawdown | AC-15 |
| Tests verify that leverage, unsupported assets, excessive sizing, stale data, duplicate orders, and breached loss limits are rejected | AC-02 (leverage), AC-08 to AC-12 |
| Setup and run commands are documented for a fresh checkout | AC-19 |

---

## 17. Framework-neutral domain contracts (new in v0.2)

### 17.1 Conventions

- **Location and technology.** `trader.domain`, Pydantic v2 models with `extra="forbid"` and `frozen=True`. No framework imports (D-44).
- **Schema versioning.** Every contract carries `schema_version` (semantic version). Major: breaking change; minor: new optional field; patch: documentation only. Readers reject unknown major versions. Content versions (`version` on profiles, `strategy_version`, `classifier_version`, `ensemble_version`, `risk_engine_version`, `adapter_version`) are separate from `schema_version`.
- **Time.** Timezone-aware UTC only; field names end in `_utc`; ISO-8601 with `Z`. Naive datetimes are rejected.
- **Numbers.** Money and quantities are `Decimal` (serialized as strings). Suffixes: `_usd`, `_pct` (0 to 100), `_bps`. Feature values may be `Decimal` or null; NaN is not allowed.
- **Identifiers.** Prefixed strings: `run-`, `cyc-`, `cor-`, `snap-`, `fs-`, `reg-`, `sig-`, `ens-`, `rsk-`, `ord-`, `exe-`, `pos-`, `evt-`, `ds-`, `EXP-`. In backtests, IDs are run-scoped sequence numbers from an injectable generator, so identical runs produce identical IDs (R-06). Paper sessions use ULIDs.
- **Correlation.** `cycle_id` identifies one decision time and timeframe; `correlation_id` identifies one instrument's chain within a cycle (snapshot to position update).
- **Canonical JSON for hashing.** UTF-8, sorted keys, no insignificant whitespace, `Decimal` as string, datetimes as ISO-8601 `Z`. Hashes are SHA-256, written `sha256:<hex>`.

### 17.2 Contract catalogue

| # | Contract | Owner (producer) | Inputs | Outputs (consumers) | Key fields | Validation rules | Versioning |
|---|---|---|---|---|---|---|---|
| 1 | `TradingProfile` | Profile service; content authored by owner | YAML file | Compiler → `CompiledProfile`; journal (`PROFILE_COMPILED`) | `profile_id`, `version`, `status`, `objective`, `capital`, `risk_selection`, `universe`, `horizon`, `execution`, `explanations`, `data_sources` | `trading-profile.schema.yaml` plus policy rules PV-01 to PV-10; declared status re-verified at load | `schema_version` (schema) + `version` (content) + content hash; never edited in place once validated |
| 2 | `RiskProfile` | Risk engine owns semantics; values owned by owner | YAML file | Compiler → effective risk values | `risk_profile_id`, `version`, `limits`, `sizing`, `concentration`, `allocation`, `cooldown`, `data_and_execution_faults`, `kill_switch`, `halt_and_liquidation` | `risk-profile.schema.yaml` plus RP-01 to RP-12; `unresolved` ⇔ `TBD`; `approved` requires approver and date | As `TradingProfile` |
| 3 | `MarketSnapshot` | Market data service | Datasets (backtest) or provider responses (paper); decision time | Features, regime, risk (freshness), sizing (reference price), journal | `snapshot_id`, `instrument_id`, `timeframe`, `as_of_utc`, `latest_bar`, `expected_latest_close_utc`, `is_fresh`, `quality_status`, `dataset_ids`, `source` | `latest_bar.close_time_utc <= as_of_utc`; `is_fresh` true only if `latest_bar.close_time_utc == expected_latest_close_utc`; OHLC consistency | `schema_version`; data lineage through `dataset_ids` |
| 4 | `FeatureSet` | Feature pipeline | `MarketSnapshot` window; feature definitions | Strategies, regime classifier, sizing (ATR), journal | `feature_set_id`, `instrument_id`, `timeframe`, `as_of_utc`, `feature_set_version`, `definitions_hash`, `values`, `max_input_close_time_utc`, `warmup_complete`, `input_dataset_ids` | `max_input_close_time_utc <= as_of_utc`; names registered; no NaN | `feature_set_version` + `definitions_hash` |
| 5 | `RegimeAssessment` | Regime classifier | `FeatureSet`; snapshot freshness | Ensemble (eligibility), journal, evaluation | `regime_assessment_id`, `instrument_id`, `as_of_utc`, `trend_state`, `volatility_state`, `data_state`, `label`, `confidence`, `method`, `classifier_id`, `classifier_version`, `feature_set_id` | `data_state = stale` whenever the snapshot is stale; `method = not_evaluated` implies `unknown` states; confidence in [0, 1] or null | `classifier_version`; model version when `method` is `ml_model` or `ai_assisted` |
| 6 | `SignalCandidate` | Strategy engine | `FeatureSet`; optional `RegimeAssessment`; strategy parameters | Ensemble, journal | `signal_id`, `correlation_id`, `cycle_id`, `instrument_id`, `timeframe`, `decision_time_utc`, `strategy_id`, `strategy_version`, `sleeve`, `side`, `strength`, `confidence`, `expected_horizon`, `entry_reference_price`, `invalidation`, `feature_set_id`, `regime_assessment_id`, `model_id`, `model_version`, `rationale_codes` | No quantity, notional, or order fields; `decision_time_utc == FeatureSet.as_of_utc`; strength in [0, 1]; `intraday` sleeve only for registered intraday strategies | `schema_version` + `strategy_version` |
| 7 | `EnsembleDecision` | Ensemble layer | Eligible `SignalCandidate` objects; `RegimeAssessment`; position state | Risk engine, journal | `ensemble_decision_id`, `correlation_id`, `instrument_id`, `decision_time_utc`, `action`, `position_state`, `contributing_signal_ids`, `ignored_signals`, `combined_score`, `confidence`, `conflict`, `no_trade_reason`, `ensemble_id`, `ensemble_version`, `weighting_method` | `enter_long` requires flat position and at least one buy; `exit_long` requires a long position; `no_trade` requires a reason; all signals share instrument and decision time | `ensemble_version`; `weighting_method` names the UD-07 option in use |
| 8 | `RiskDecision` | Risk engine | `EnsembleDecision`, `CompiledProfile`, `PositionSnapshot`, `MarketSnapshot`, `FeatureSet`, `UniverseSnapshot`, operational state | `OrderIntent` creation, journal, evaluation | `risk_decision_id`, `correlation_id`, `ensemble_decision_id`, `instrument_id`, `decision_time_utc`, `action_evaluated`, `status`, `approved_quantity`, `approved_notional_usd`, `reference_price`, `stop`, `loss_state`, `rule_results`, `reason_codes`, `binding_constraint`, `config_hash`, `risk_engine_version` | Approved/modified ⇒ quantity > 0; rejected ⇒ quantity 0 and at least one reason code; every RR rule has a result; `config_hash` matches the run | `risk_engine_version` + per-rule versions |
| 9 | `OrderIntent` | Risk engine (sizing stage) | `RiskDecision`, `EnsembleDecision`, signals | Execution gate and adapter, journal | `order_intent_id`, `correlation_id`, `idempotency_key`, `risk_decision_id`, `ensemble_decision_id`, `signal_ids`, `strategy_versions`, `model_versions`, `instrument_id`, `side`, `purpose`, `order_type`, `quantity`, `reference_price`, `stop_price`, `notional_estimate_usd`, `valid_until_utc`, `environment`, `funds`, `config_hash`, `market_data_timestamp_utc` | `quantity <= approved_quantity`; `funds == simulated`; entry ⇒ buy, exit and protective stop ⇒ sell; all D-36 traceability fields present; `idempotency_key = sha256(config_hash, instrument_id, side, purpose, decision_time_utc)` | `schema_version` |
| 10 | `ExecutionReport` | Execution service / adapter | `OrderIntent`; adapter state; bar data (simulator) | Portfolio, journal, evaluation | `execution_report_id`, `order_intent_id`, `correlation_id`, `adapter_id`, `adapter_version`, `venue`, `status`, `reason_code`, `filled_quantity`, `average_fill_price`, `expected_price`, `fees_usd`, `fee_rate_pct`, `slippage_bps_assumed`, `slippage_usd`, `submitted_at_utc`, `filled_at_utc`, `fill_bar_open_time_utc`, `latency_ms` | `filled_quantity <= quantity`; fill price within the bar's low-high range; `filled` ⇒ full quantity; fees ≥ 0 | `adapter_version` |
| 11 | `PositionSnapshot` | Portfolio service | `ExecutionReport` objects; mark prices | Risk engine, reports, dashboard (later) | `position_snapshot_id`, `as_of_utc`, `cash_usd`, `committed_cash_usd`, `equity_usd`, `hwm_equity_usd`, `drawdown_pct`, `day_start_equity_usd`, `daily_pnl_pct`, `positions`, `exposure`, `open_positions_count`, `breaker_open`, `daily_lockout_until_utc`, `cooldowns` | Equity equals cash plus market value exactly; quantities ≥ 0; cash ≥ 0 | `schema_version` |
| 12 | `TradeEvent` | Journal | Any contract above as payload | Audit, verification, evaluation, explanations | `event_id`, `run_id`, `seq`, `event_type`, `event_time_utc`, `recorded_at_utc`, `cycle_id`, `correlation_id`, `payload_type`, `payload_schema_version`, `payload`, `prev_event_hash`, `event_hash`, `code_revision`, `config_hash` | `seq` contiguous; `event_hash` = SHA-256 of previous hash plus canonical content excluding `run_id`, `recorded_at_utc`, and `event_hash`; append-only | `schema_version` + `payload_schema_version` |
| 13 | `ExperimentRecord` | Research and promotion service | Experiment definition; run outputs | `docs/experiments/`, promotion decisions | `experiment_id`, `title`, `hypothesis`, `purpose`, `status`, `data`, `strategy`, `profile_refs`, `experiment_parameters`, `assumptions`, `method`, `results`, `overfit_checks`, `failure_analysis`, `decision`, `reproduction`, `run_ids` | ID pattern `EXP-YYYY-NNN`; parameters only target `unresolved` or `hypothesis` fields; reproduction command and code revision present | `schema_version`; a decided record is immutable (re-runs create a new record) |

**Event types** (`TradeEvent.event_type`): `RUN_STARTED`, `RUN_BLOCKED`, `RUN_COMPLETED`, `RUN_FAILED`, `PROFILE_COMPILED`, `DATASET_VALIDATED`, `UNIVERSE_EVALUATED`, `CYCLE_STARTED`, `DATA_STALE`, `PROVIDER_DEGRADED`, `FEATURES_COMPUTED`, `REGIME_ASSESSED`, `SIGNAL_GENERATED`, `ENSEMBLE_DECIDED`, `RISK_EVALUATED`, `ORDER_INTENT_CREATED`, `ORDER_SUBMITTED`, `ORDER_REJECTED`, `ORDER_FILLED`, `ORDER_CANCELED`, `STOP_TRIGGERED`, `POSITION_UPDATED`, `CIRCUIT_BREAKER_OPENED`, `DAILY_LOCKOUT_STARTED`, `COOLDOWN_STARTED`, `KILL_SWITCH_ENGAGED`, `KILL_SWITCH_DISENGAGED`, `EXECUTION_ERROR`, `RECONCILIATION_FAILED`, `EXPLANATION_GENERATED`, `CYCLE_COMPLETED`.

### 17.3 Supporting types

| Type | Owner | Purpose |
|---|---|---|
| `CompiledProfile` | Profile compiler | Effective configuration for one run: profile references and hashes, environment, effective values with provenance (`approved`, `hypothesis`, `experiment`, or `fixture` in tests only), blockers, `config_hash` |
| `Candle` | Market data service | One OHLCV bar: `open_time_utc`, `close_time_utc`, `open`, `high`, `low`, `close`, `volume` |
| `DatasetManifest` | Market data service | Immutable dataset description: `dataset_id`, instrument, timeframe, source, retrieval time, range, row count, content hash, quality report |
| `UniverseSnapshot` | Universe service | Point-in-time tier and eligibility result per asset, with criterion outcomes and reasons |
| `RuleResult` | Risk engine | `rule_id`, `rule_version`, `outcome` (`pass`, `fail`, `clamped`, `not_evaluated`, `not_applicable`), `reason_code`, inputs, threshold reference |
| `KillSwitchState` | Operational control service | `state`, `changed_at_utc`, `changed_by`, `trigger`, `reason`; history is append-only |
| `ExperimentDefinition` | Research service | Input file for an experiment: hypothesis, data, strategy, cost scenario, experiment parameters |
| `PromotionRecord` | Research and promotion service | Owner-approved promotion with evidence experiment IDs and gate results G-01 to G-11 |
| `ChampionBundle` | Research and promotion service | Immutable artifact loaded by the active paper trader (§8.6) |

### 17.4 Compatibility and change policy

- A contract change that affects stored journals requires a migration note in the change log and a new `schema_version` major version; old journals stay readable through versioned readers.
- `OrderIntent`, `RiskDecision`, and `TradeEvent` changes require updating `trader journal verify` and test T-39.
- No contract may gain a field that lets a strategy, model, or AI component set a D-32 item.

---

## 18. Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-10-08 | Initial architecture, safety boundary, components, implementation sequence, backlog, and ADRs |
| 0.2 | 2026-10-08 | Revised against the Cowork kickoff and the approved design decisions. Added decision references and status labels; updated scope and non-goals (D-21, D-43); added principles P-11 and P-12; component boundaries, authority matrix, and module rules (§4.2 to §4.4); technology verdicts (§5.3, §5.4); risk rule catalogue RR-01 to RR-20 and execution gate EG-01 to EG-05; ensemble, universe, operational-control, and research components (§6.12 to §6.15); data, control, execution, loss-response, and traceability flows (§7.4 to §7.7); research versus active paper-trader separation and champion bundles (§8.5, §8.6); halt mechanisms and failure-mode table (§9.2, §9.4, §9.5); local and hosted deployment views (§10.1, §10.2); framework-neutral domain contracts (§17); ADR-005 to ADR-018. Moved implementation sequence, backlog, experiment template, and definition of done to `execution-plan.md`, `experiment-plan.md`, `product-requirements.md`, and `code-session-handoff.md`, with mapping tables. Reconciled v0.1 open questions. Superseded the v0.1 example profile ($10,000) with the approved $2,500 Balanced profile. |
