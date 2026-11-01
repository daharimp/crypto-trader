# Product Requirements: AI-Assisted Crypto Paper-Trading System

**Document status:** Draft for owner review
**Version:** 0.2 (first issue, aligned with `architecture.md` v0.2)
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Controlling inputs:** `cowork-kickoff.md` (controlling specification), `decisions-summary.md` (approved design decisions), `architecture.md` v0.1
**Package role:** Canonical home of the decision baseline (approved decisions, hypotheses, recommendations index, unresolved decisions) and of the V1 requirements and acceptance criteria. See `README.md` for the package index and dependency map.

> **Safety boundary.** The MVP uses paper, dry-run, or simulated funds only. No real-money execution, leverage, margin, short selling, withdrawals, transfers, or unrestricted trade placement exists in the MVP. Deterministic risk controls have final authority (D-02, D-03, D-13).

---

## 1. Problem statement

Dahari wants to research and engineer an AI-assisted crypto trading system that pursues strong returns with consistent performance and controlled drawdown, without risking real money while the system is immature. The hard parts are not signal generation alone. They are:

1. turning objectives and risk appetite into **enforceable, versioned configuration** rather than improvised behavior;
2. letting AI and models contribute where they add value (regime classification, strategy selection, signal combination, explanations) **without letting any model bypass hard risk limits**;
3. evaluating strategies **honestly** (time-ordered, cost-aware, leakage-free, against simple baselines) so that apparent backtest profits are not mistaken for skill;
4. making every simulated order **fully traceable** from market data through risk decision to execution outcome.

The product is a research and engineering system (D-01). It must never claim or assume guaranteed profitability (D-07).

## 2. Target user and jobs to be done

**Primary user:** the owner, a single technically capable operator who acts as researcher, risk owner, and operator. There are no other users in V1 (assumption A-01).

| ID | Job to be done | Primary requirements |
|---|---|---|
| JTBD-1 | When I define my objective and risk appetite, I want it compiled into a validated, versioned profile so the system only trades inside boundaries I chose. | FR-PROF-*, FR-RISK-* |
| JTBD-2 | When I research a strategy, I want cost-aware, leakage-free comparisons against simple baselines so I do not fool myself with an overfit backtest. | FR-EVAL-*, FR-RSCH-* |
| JTBD-3 | When the system trades on paper, I want ordinary approved trades to execute without manual clicks, and every decision to be explained and traceable. | FR-EXEC-*, FR-JRNL-* |
| JTBD-4 | When something goes wrong, I want the system to fail closed and give me a manual kill switch that always works. | FR-RISK-12, SAFE-06, SAFE-07 |
| JTBD-5 | When a challenger looks better, I want promotion to require explicit evidence and my explicit approval, never automatic. | FR-RSCH-04, SAFE-10 |
| JTBD-6 | When I am ready to go beyond BTC and ETH, I want new assets to pass objective eligibility checks and tier-specific limits, including assets I nominate myself. | FR-UNIV-* |

---

## 3. Decision baseline (canonical registers)

### 3.1 Status labels used across the package

| Label | Meaning | ID format |
|---|---|---|
| **APPROVED** | Owner-approved decision from the kickoff or the approved design-decisions summary. Quoted verbatim below. Must not be rewritten into a materially different requirement. | `D-nn` |
| **HYPOTHESIS** | Recorded starting hypothesis. Usable as a labelled starting value; must be tested; not a permanent production limit. | `H-nn` |
| **RECOMMENDATION** | Proposal made while formalizing the package. Not approved until the owner accepts it. | `R-nn`, `RT-nn` |
| **UNRESOLVED** | Open decision. Its value is `TBD` everywhere. Code must fail closed rather than invent a value. | `UD-nn` |

Architecture principles carried forward from `architecture.md` v0.1 are labelled `P-nn` and treated as accepted baseline.

### 3.2 Approved decisions

Text in the "Approved decision" column is quoted verbatim from `cowork-kickoff.md` unless the source column says otherwise. The last column quotes the matching line of the approved design-decisions summary (DS) where one exists.

| ID | Area | Approved decision (verbatim) | Source | DS counterpart |
|---|---|---|---|---|
| D-01 | Mission | "This is a research and engineering project." | Kickoff, Mission | — |
| D-02 | Safety | "The initial system must use paper, dry-run, or simulated funds only." | Kickoff, Mission | "Paper, dry-run, or simulated funds only in the MVP." |
| D-03 | Safety | "Do not design real-money autonomous execution, leverage, withdrawals, or unrestricted trade placement into the MVP." | Kickoff, Mission | "No leverage, withdrawals, or unrestricted autonomous real-money trading." |
| D-04 | Portfolio | "Initial simulated portfolio: $2,500." | Kickoff, Portfolio and objective | "Initial simulated capital: $2,500." |
| D-05 | Objective | "Primary objective: balance strong returns with consistent performance and controlled drawdown." | Kickoff, Portfolio and objective | "Objective: balance strong returns with consistency and controlled drawdown; aggression is profile-dependent." |
| D-06 | Objective | "A more aggressive operating profile may exist, but only as an explicitly selected risk profile." | Kickoff, Portfolio and objective | (aggression is profile-dependent) |
| D-07 | Objective | "The system must not claim or assume guaranteed profitability." | Kickoff, Portfolio and objective | — |
| D-08 | Risk model | "Use a hybrid risk-profile model." | Kickoff, Risk model | "Hybrid risk model: adaptive behavior within hard selected-profile boundaries." |
| D-09 | Risk model | "The user selects an overall profile, initially Balanced." | Kickoff, Risk model | — |
| D-10 | Risk model | "The system may become more defensive or aggressive inside that profile's boundaries." | Kickoff, Risk model | (adaptive behavior within hard selected-profile boundaries) |
| D-11 | Risk model | "Maximum drawdown and related thresholds are profile-dependent." | Kickoff, Risk model | "Profile-dependent drawdown limits." |
| D-12 | Risk model | "Loss handling is hybrid: 1. reassess signals and market conditions; 2. reduce position sizes as losses accumulate; 3. allow hard thresholds to override every strategy and model; 4. stop opening new trades after a profile-specific circuit breaker is reached." | Kickoff, Risk model | "Hybrid loss response: adaptive reassessment followed by deterministic hard stops." |
| D-13 | Risk model | "Deterministic code has final authority over risk." | Kickoff, Risk model | "Deterministic risk controls have final authority." |
| D-14 | Risk model | "AI and ML may recommend but may not bypass hard limits." | Kickoff, Risk model | — |
| D-15 | Trading pace | "Holding period is adaptive." | Kickoff, Trading pace | "Adaptive holding periods, primarily 1-hour and 4-hour signals for V1." |
| D-16 | Trading pace | "Primary V1 decision timeframes should be 1-hour and 4-hour." | Kickoff, Trading pace | (same line as D-15) |
| D-17 | Trading pace | "Typical positions may last from roughly one hour through several days." | Kickoff, Trading pace | — |
| D-18 | Trading pace | "Minute-level data is allowed in two roles: refine entries and exits for slower strategies; power separately approved intraday strategies." | Kickoff, Trading pace | "Minute-level data can refine entries/exits and power approved isolated intraday strategies." |
| D-19 | Trading pace | "Independent intraday strategies must use an isolated, capped allocation and stricter evaluation rules." | Kickoff, Trading pace | — |
| D-20 | Trading pace | "Test candidate intraday allocation caps of 5%, 10%, 15%, and 20%; do not assume the largest allocation is best." | Kickoff, Trading pace | "Intraday allocation determined by testing candidate caps of 5%, 10%, 15%, and 20%." |
| D-21 | Trading pace | "High-frequency and latency-arbitrage trading are out of scope." | Kickoff, Trading pace | — |
| D-22 | Universe | "Begin with a rules-based universe of liquid crypto assets." | Kickoff, Asset universe | "Start with a rules-based liquid-asset universe, then move toward dynamic discovery." |
| D-23 | Universe | "Progress toward dynamic opportunity discovery." | Kickoff, Asset universe | (same line as D-22) |
| D-24 | Universe | "Allow the user to provide a manual asset allowlist." | Kickoff, Asset universe | "Support user-provided asset allowlists subject to eligibility checks." |
| D-25 | Universe | "Every asset, including manually nominated assets, must pass eligibility checks." | Kickoff, Asset universe | (same line as D-24) |
| D-26 | Universe | "Use asset tiers: Core: BTC, ETH, or other explicitly approved core assets; Major: established, liquid altcoins; Speculative: smaller or higher-volatility assets with strict limits; Blocked: assets that fail liquidity, data-history, spread, support, or explicit exclusion rules." | Kickoff, Asset universe | "Tier assets as Core, Major, Speculative, and Blocked." |
| D-27 | Universe | "Use profile- and tier-dependent concentration limits." | DS, Approved | (DS is the source) |
| D-28 | Universe | "Treat these as testable starting hypotheses, not permanently accepted production limits." (applies to H-01 to H-04) | Kickoff, Asset universe | "Starting hypotheses, not permanent decisions" (DS heading) |
| D-29 | Strategy | "Use a hybrid regime-aware ensemble: 1. ingest and validate market data; 2. classify the market regime; 3. determine which strategies are eligible for that regime; 4. generate candidates from strategies such as trend, momentum, mean reversion, breakout, and later ML; 5. combine candidates through a confidence/ensemble layer; 6. allow a deterministic risk engine to approve, modify, or reject the proposed trade; 7. size approved positions deterministically; 8. send approved orders to paper execution only; 9. journal the complete decision chain." | Kickoff, Strategy architecture | "Hybrid regime-aware strategy ensemble." |
| D-30 | Strategy | "No single opaque model receives total control." | Kickoff, Strategy architecture | — |
| D-31 | AI authority | "AI and models may directly influence: market-regime classification; eligible-strategy selection; ranking of eligible assets; combination and interpretation of signals; explanations; proposed research experiments; later interpretation of news and other unstructured sources." | Kickoff, AI authority | — |
| D-32 | AI authority | "AI may recommend but not unilaterally determine: final position size; hard stop-loss policy; portfolio exposure ceilings; drawdown limits; daily loss limits; speculative and intraday allocation caps; leverage permissions; kill-switch behavior; promotion of experimental strategies into the active trader." | Kickoff, AI authority | — |
| D-33 | Execution | "In paper mode, ordinary approved trades execute automatically." | Kickoff, Execution autonomy | "Autonomous execution in paper mode after deterministic risk approval." |
| D-34 | Execution | "No approval click is required after deterministic risk validation." | Kickoff, Execution autonomy | (same line as D-33) |
| D-35 | Execution | "The user must have a manual kill switch." | Kickoff, Execution autonomy | — |
| D-36 | Execution | "Every order must be traceable to its signal, strategy/model versions, risk decision, configuration, and market-data timestamp." | Kickoff, Execution autonomy | — |
| D-37 | Data | "Use a progressive provider architecture: V1: price/candles, volume, volatility, technical features; V1.5: order book, cross-asset relationships, derivatives data where available; V2: news, on-chain information, and macroeconomic inputs; Experimental: social sentiment and other alternative signals." | Kickoff, Data architecture | "Progressive data architecture from market data toward derivatives, news, on-chain, macro, and experimental sentiment." |
| D-38 | Data | "The provider interfaces should anticipate later sources, but V1 must not depend on them." | Kickoff, Data architecture | — |
| D-39 | UX | "Long-term interaction is hybrid: conversational interface for objectives, directives, questions, and explanations; dashboard for portfolio, positions, signals, risk state, and strategy performance; CLI for backtesting, experiments, operations, and debugging." | Kickoff, User experience | "Hybrid conversation, dashboard, and CLI experience; CLI/core engine first." |
| D-40 | UX | "Build the CLI and core engine first." | Kickoff, User experience | (same line as D-39) |
| D-41 | UX | "Do not let UI work block the initial end-to-end paper-trading pipeline." | Kickoff, User experience | — |
| D-42 | Deployment | "Use a hybrid deployment direction: local environment for development, backtesting, experimentation, and strategy research; later continuously running hosted paper trader for monitoring, signal generation, risk checks, simulated execution, journaling, and alerts." | Kickoff, Deployment | "Local research/development plus eventual continuously running hosted paper trader." |
| D-43 | Deployment | "Use champion/challenger separation: experimental strategies and models run in the research environment; only explicitly approved versions may enter the hosted paper trader; promotion must never be automatic in the initial architecture." | Kickoff, Deployment | "Champion/challenger separation with explicit promotion." |
| D-44 | Contracts | "Do not let the framework leak into every domain model. Keep profile, signal, risk-decision, order-intent, and trade-event contracts framework-neutral." | Kickoff, Recommended technical direction | — |
| D-45 | Contracts | Required framework-neutral contracts: "`TradingProfile`, `RiskProfile`, `MarketSnapshot`, `FeatureSet`, `RegimeAssessment`, `SignalCandidate`, `EnsembleDecision`, `RiskDecision`, `OrderIntent`, `ExecutionReport`, `PositionSnapshot`, `TradeEvent`, `ExperimentRecord`. For each contract, document ownership, inputs, outputs, validation rules, and versioning." | Kickoff, Required framework-neutral contracts | — |
| D-46 | V1 slice | "Validated Balanced paper profile -> load BTC and ETH historical candles -> validate data quality -> run buy-and-hold benchmark -> run one trend/momentum baseline -> generate SignalCandidate events -> apply deterministic RiskProfile checks -> simulate orders using paper/dry-run execution -> persist TradeEvent journal -> report returns, fees, drawdown, and benchmark comparison" | Kickoff, V1 vertical slice | — |
| D-47 | V1 slice | "The vertical slice is not complete unless tests prove that invalid profiles, unsupported assets, stale data, excessive sizing, duplicate orders, breached loss limits, and disabled execution states are rejected." | Kickoff, V1 vertical slice | — |

### 3.3 Hypotheses

| ID | Hypothesis (verbatim) | Source | Status and use |
|---|---|---|---|
| H-01 | "Balanced Core cap: 35% per asset." (kickoff: "Core asset: up to 35% each") | DS + Kickoff | Starting value in `risk-profile.schema.yaml` Balanced, `status: hypothesis`. Tested in EXP-2026-003. Governed by D-28. |
| H-02 | "Balanced Major cap: 15% per asset." (kickoff: "Major asset: up to 15% each") | DS + Kickoff | As H-01. |
| H-03 | "Balanced Speculative cap: 5% per asset." (kickoff: "Speculative asset: up to 5% each") | DS + Kickoff | As H-01. |
| H-04 | "Balanced total Speculative cap: 10%." (kickoff: "Total speculative exposure: up to 10%") | DS + Kickoff | As H-01. This is the Balanced "speculative allocation cap". |
| H-05 | "BTC and ETH are the initial vertical-slice assets." | DS | The kickoff's V1 slice (D-46) uses BTC and ETH. The DS labels the choice a starting hypothesis, so BTC and ETH are the slice scope, not a permanent universe decision. |

Hypothesis values may be used in backtests and in paper sessions as labelled starting values. Every report that relies on a hypothesis value must say so (FR-EVAL-05).

### 3.4 Recommendations register

Recommendations are not approved. Each is detailed where listed and must be accepted, changed, or rejected by the owner.

**Kickoff "recommended technical direction to evaluate" (RT).** Verdicts are in `architecture.md` §5.

| ID | Recommendation from the kickoff | Package verdict (RECOMMENDATION) |
|---|---|---|
| RT-01 | Python 3.11+ | Adopt. |
| RT-02 | Freqtrade for backtesting/dry-run capabilities | Evaluate in a time-boxed spike (BL-032) behind the execution-adapter boundary; do not depend on it for the M1 vertical slice (R-03, ADR-003). |
| RT-03 | FreqAI only after non-ML baselines exist | Adopt as a sequencing rule (P8 depends on P7). |
| RT-04 | CCXT or framework-specific adapters behind a framework-neutral execution interface | Adopt. CCXT is used only for public market data until UD-05 is resolved. |
| RT-05 | Pydantic for validated contracts | Adopt (v2). |
| RT-06 | Typer for CLI | Adopt. |
| RT-07 | FastAPI for later local/hosted API | Adopt later (P9/P10). |
| RT-08 | SQLite plus Parquet locally, with PostgreSQL/object storage later | Adopt. |
| RT-09 | pytest for unit and integration tests | Adopt. |
| RT-10 | Structured JSON logs and correlation IDs | Adopt in M1. |
| RT-11 | Docker for reproducibility after the first local vertical slice | Adopt after M1 (BL-033). |

**Package recommendations (R).**

| ID | Recommendation | Detailed in |
|---|---|---|
| R-01 | Signal-conflict resolution: regime gate, opposition veto for entries, exit precedence, no trade on conflict (the kickoff-required conflict recommendation) | `strategy-spec.md` §7 |
| R-02 | Value-provenance model: every risk value is approved, hypothesis, or unresolved; unresolved values fail closed; experiment parameter sets may fill unresolved values in research backtests only | `architecture.md` ADR-016, `risk-profile.schema.yaml`, `experiment-plan.md` §11 |
| R-03 | M1 uses an in-house deterministic bar-replay simulator behind the execution-adapter interface; Freqtrade is evaluated in a spike | `architecture.md` ADR-003, §5 |
| R-04 | Decimal arithmetic for money and quantities with explicit rounding | `architecture.md` ADR-017 |
| R-05 | Append-only, hash-chained journal; journal before act | `architecture.md` ADR-018 |
| R-06 | Run-scoped deterministic identifiers in backtests | `architecture.md` §17.1 |
| R-07 | Candle time convention: open-time label, available at close, decide at bar close, fill at next bar open | `data-architecture.md` §5 |
| R-08 | Two-axis regime taxonomy with a data-state override; deterministic V1 classifier parameters | `strategy-spec.md` §3 |
| R-09 | `sma_trend` baseline parameters (fast 20, slow 50; cross-up entry, state-based exit) | `strategy-spec.md` §4.3 |
| R-10 | Cost scenarios `low`, `base`, `stress` | `experiment-plan.md` §6 |
| R-11 | Time-ordered split, sealed 12-month holdout, expanding walk-forward folds | `experiment-plan.md` §3–4 |
| R-12 | Overfit rejection criteria OF-01 to OF-12 with thresholds | `experiment-plan.md` §14 |
| R-13 | Explanation preference default `every_decision`, generated from journal facts by templates | `trading-profile.schema.yaml`, `architecture.md` §6.10 |
| R-14 | `observe_only` autonomy mode (journal signals and risk decisions without orders) | `trading-profile.schema.yaml` |
| R-15 | Kill switch persisted across restarts, owner-only disengage with a reason, initial state disengaged, open positions held unchanged until UD-19 is resolved | `architecture.md` §9.2, `risk-profile.schema.yaml` |
| R-16 | Release staging of non-data capabilities (UI, hosting, ML, intraday) | This document §4 |
| R-17 | Tooling: uv, ruff, mypy, pandas plus pyarrow, PyYAML, jsonschema, hypothesis | `code-session-handoff.md` §4 |
| R-18 | Drawdown circuit breaker is latched; only an owner command resets it (and rebases the high-water mark) | `architecture.md` §9.2, `risk-profile.schema.yaml` |
| R-19 | Concentration and exposure caps constrain risk-increasing orders at decision time using a conservative reference price; price drift after entry does not force trimming in V1 | `strategy-spec.md` §9 |
| R-20 | Benchmarks are computed analytically and are not routed through the risk engine or execution | `strategy-spec.md` §4.1 |
| R-21 | The spread eligibility criterion is `not_applicable` on candle-only V1 data and becomes mandatory with V1.5 order-book data (pending UD-18) | `data-architecture.md` §4.5 |
| R-22 | V1 adaptation is defensive-only; upward adaptation waits for UD-15 | `strategy-spec.md` §9.4 |
| R-23 | Minute-level refinement and the intraday sleeve start in V1.5 | This document §4, `execution-plan.md` |
| R-24 | Promotion gates G-01 to G-11 (thresholds remain UD-08) | `strategy-spec.md` §12 |

### 3.5 Unresolved decisions summary

UD-01 to UD-11 are the kickoff's "Unresolved decisions to preserve", in kickoff order. UD-12 to UD-21 were identified while formalizing the package: each is a value or policy the kickoff requires a field for but no decision exists. Full analysis is in §10.

| ID | Unresolved decision | Origin | Must be resolved before |
|---|---|---|---|
| UD-01 | Exact Conservative, Balanced, and Aggressive drawdown thresholds | Kickoff | Paper activation of the profile (P5); backtests may use experiment values |
| UD-02 | Exact daily-loss limits | Kickoff | Paper activation (P5) |
| UD-03 | Exact risk-per-trade limits | Kickoff | Paper activation (P5) |
| UD-04 | Exact reserve ranges | Kickoff | Paper activation (P5) |
| UD-05 | First paper broker/exchange adapter | Kickoff | Forward paper trading (P5, BL-027) |
| UD-06 | Exact tradable Major and Speculative asset lists | Kickoff | Any non-Core asset in a paper session |
| UD-07 | Signal-conflict weighting formula | Kickoff | Ensemble in a champion bundle (P7) |
| UD-08 | Promotion thresholds for challengers | Kickoff | First promotion (P10) |
| UD-09 | Hosted cloud provider and topology | Kickoff | Hosted deployment (P10) |
| UD-10 | Alert channels | Kickoff | Hosted deployment (P10) |
| UD-11 | Retention durations | Kickoff | Hosted deployment (P10) |
| UD-12 | Total exposure cap and maximum open positions per profile | Formalization | Paper activation (P5) |
| UD-13 | Tier caps for Conservative and Aggressive; production status of Balanced hypotheses H-01 to H-04 | Formalization | Selecting Conservative or Aggressive outside experiments |
| UD-14 | Selected intraday allocation cap and intraday sleeve loss limits | Formalization (process approved in D-20) | Enabling any intraday strategy |
| UD-15 | Loss-response size-reduction schedule and adaptation bounds | Formalization (behavior approved in D-10, D-12) | Paper activation (schedule); upward adaptation (bounds) |
| UD-16 | Hard stop-loss policy (method and parameters) | Formalization (authority set in D-32) | Paper activation (P5) |
| UD-17 | Cooldown, exchange-error, stale-data grace, clock-skew, and external reconciliation thresholds | Formalization | Paper activation (cooldown, errors); forward paper (grace, skew) |
| UD-18 | Asset eligibility thresholds (liquidity, data history, spread, support) | Formalization (criteria approved in D-25, D-26) | Paper activation; backtests may use experiment values |
| UD-19 | Post-halt liquidation policy and kill-switch effect on open positions | Formalization (v0.1 §9.2; authority set in D-32) | Paper activation (P5) |
| UD-20 | V1 market-data venue, quote currency, and venue cost schedule | Formalization | Downloading real datasets for evaluation experiments (EXP-2026-002 onward) |
| UD-21 | Numeric success targets for the objective | Formalization (v0.1 Q4) | V1 MVP exit evaluation (M2) and UD-08 |

---

## 4. Scope and staged release

Data-source staging is approved (D-37). Staging of other capabilities is a recommendation (R-16, R-23) consistent with D-40 and D-41.

| Stage | Contents | Status |
|---|---|---|
| **M1: V1 vertical slice** | The kickoff slice (D-46) with the required rejection tests (D-47): validated Balanced paper profile, BTC and ETH candles, data-quality validation, buy-and-hold benchmark, one trend/momentum baseline (`sma_trend`), `SignalCandidate` events, deterministic risk checks, simulated execution, `TradeEvent` journal, report. CLI and core engine only. | APPROVED scope (D-46, D-47); implementation details RECOMMENDATION |
| **V1 (MVP)** | M1 plus: additional baselines (momentum, mean reversion, breakout), deterministic regime classifier and rules-based ensemble, walk-forward evaluation, templated explanations, local forward paper trading with autonomous execution after risk approval, manual kill switch, local alerts. Universe: Core (BTC, ETH). Timeframes 1h and 4h. V1 data only. | APPROVED direction (D-15, D-16, D-22, D-29, D-33 to D-35, D-37, D-40); staging RECOMMENDATION |
| **V1.5** | Order book, cross-asset relationships, derivatives data where available (read-only inputs; derivatives are never traded); minute-level entry/exit refinement; intraday sleeve experiments (D-20) and, if approved, an isolated intraday sleeve; Major tier through eligibility screening; optional ML challenger in research only; Freqtrade adapter if ADR-003 is accepted. | Data APPROVED (D-37); other items RECOMMENDATION |
| **V2** | News, on-chain information, macroeconomic inputs; dynamic opportunity discovery; conversational interface; dashboard; continuously running hosted paper trader. | Data APPROVED (D-37); direction APPROVED (D-23, D-39, D-42); timing RECOMMENDATION |
| **Experimental** | Social sentiment and other alternative signals, research environment only. | APPROVED (D-37) |
| **Out of scope for this program** | Real-money execution of any kind, leverage, margin, futures/options/perpetual trading, short selling, withdrawals, transfers, high-frequency and latency-arbitrage trading, automatic promotion. Any future real-money work needs a separate production-readiness review outside this package. | APPROVED (D-02, D-03, D-21, D-43) |

---

## 5. Functional requirements

Each requirement cites the decisions it realizes. "Shall" statements are binding for the stage shown.

### 5.1 Profiles and configuration (FR-PROF)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-PROF-01 | The system shall load `TradingProfile` documents that conform to `trading-profile.schema.yaml` and reject any document that fails schema validation, with a specific error code per failure. | M1 | D-45, D-47 |
| FR-PROF-02 | The initial Balanced profile shall set simulated paper capital to $2,500 and `funds: simulated`. Any other `funds` value is invalid. | M1 | D-02, D-04 |
| FR-PROF-03 | A profile shall select exactly one risk profile (`conservative`, `balanced`, `aggressive`). The initial selection is `balanced`. Selecting `aggressive` requires an explicit acknowledgement block. The system shall never switch profiles on its own. | M1 | D-06, D-09 |
| FR-PROF-04 | A profile shall record the objective statement verbatim and `guaranteed_profitability_assumed: false`. | M1 | D-05, D-07 |
| FR-PROF-05 | Profiles shall have a declared lifecycle status (`draft`, `validated`, `active`, `suspended`). The declared status can only restrict use: it is re-verified at every load. `draft` and `suspended` profiles cannot run; `validated` profiles may run backtests; only `active` profiles may run paper sessions. | M1 (backtest gates), V1 (activation) | Kickoff §3 deliverable |
| FR-PROF-06 | The profile compiler shall merge the `TradingProfile`, the selected `RiskProfile`, the eligibility rules, and (in backtests only) an experiment parameter set into a `CompiledProfile` that records the provenance of every effective value and a content hash (`config_hash`). | M1 | D-36, R-02 |
| FR-PROF-07 | Any required value that is `TBD` for the requested environment shall block the run with exit code 3 and a blocker report listing each field and its UD ID. No default may be substituted. | M1 | Kickoff quality bar; R-02 |
| FR-PROF-08 | The compiler shall detect contradictions (policy rules PV-01 to PV-10 in `trading-profile.schema.yaml` and RP-01 to RP-12 in `risk-profile.schema.yaml`) and refuse to compile until they are resolved. | M1 | v0.1 §6.1 |
| FR-PROF-09 | Validated and active profiles shall never be mutated silently. Any change requires a version increment, and the journal shall record profile ID, version, and content hash for every run. | M1 | P-06, v0.1 §9.3 |
| FR-PROF-10 | A guided questionnaire and, later, the conversational interface may produce a *proposed* profile. Proposals shall pass the same validation and require owner review before use. | V1 should (CLI questionnaire), V2 (conversation) | D-39, v0.1 §6.1–6.2 |

### 5.2 Asset universe (FR-UNIV)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-UNIV-01 | The system shall maintain an asset registry with tiers Core, Major, Speculative, and Blocked. Core initially contains BTC and ETH; other Core assets require explicit owner approval. | M1 | D-26 |
| FR-UNIV-02 | The owner may add assets through a manual allowlist. Allowlisted assets shall pass the same eligibility checks as every other asset; failures are treated as Blocked with a recorded reason. | M1 (mechanism) | D-24, D-25 |
| FR-UNIV-03 | Assets on the profile's disallowed list or the registry blocklist shall be Blocked. | M1 | D-26 |
| FR-UNIV-04 | Eligibility shall evaluate liquidity, data history, spread, support, and explicit exclusion. Thresholds are UD-18. A criterion that cannot be evaluated because its threshold is unresolved fails closed. | M1 | D-25, D-26 |
| FR-UNIV-05 | Each decision cycle shall use a point-in-time `UniverseSnapshot` that is journaled. | M1 | D-36, P-07 |
| FR-UNIV-06 | The universe shall progress from rules-based screening (V1.5) toward dynamic opportunity discovery (V2), in which AI may rank eligible assets but may not add ineligible ones. | V1.5–V2 | D-22, D-23, D-31 |
| FR-UNIV-07 | Concentration limits shall depend on profile and tier. Balanced starting values are H-01 to H-04. | M1 | D-27, D-28 |

### 5.3 Market data and features (FR-DATA)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-DATA-01 | A `CandleProvider` interface shall supply OHLCV candles for 1h and 4h (and 1m for later roles) from local CSV, a deterministic synthetic generator, and optionally a CCXT public-data provider with an explicitly specified venue. | M1 | D-16, D-37 |
| FR-DATA-02 | Data-quality checks DQ-01 to DQ-12 (`data-architecture.md` §6) shall run on every dataset; failing datasets are unusable. | M1 | D-29 step 1, D-46 |
| FR-DATA-03 | Backtests shall use immutable datasets identified by a content hash and described by a `DatasetManifest`. | M1 | P-06, v0.1 §6.3 |
| FR-DATA-04 | All timestamps shall be timezone-aware UTC; naive timestamps are rejected. | M1 | v0.1 §6.3 |
| FR-DATA-05 | At decision time the system shall verify that the latest expected closed candle is present; otherwise the snapshot is stale and no new orders are created for that instrument. | M1 | P-09, D-47 |
| FR-DATA-06 | Interfaces for V1.5, V2, and Experimental providers shall exist as protocols, but the V1 pipeline shall run with only V1 providers registered. | M1 (protocols), later (implementations) | D-37, D-38 |
| FR-DATA-07 | Features shall be computed causally and versioned, with lineage to input datasets (`FeatureSet`). | M1 | P-07, v0.1 §6.4 |
| FR-DATA-08 | Source, retrieval time, and symbol mapping shall be recorded for every dataset. | M1 | v0.1 §6.3 |

### 5.4 Strategy, regime, and ensemble (FR-STRAT)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-STRAT-01 | Strategies shall emit `SignalCandidate` objects only; they shall never emit quantities, notionals, or orders. | M1 | D-29, D-32 |
| FR-STRAT-02 | Baselines: cash, buy-and-hold BTC, buy-and-hold ETH, equal-weight BTC/ETH, and `sma_trend` in M1; time-series momentum, mean reversion, volatility breakout, and a random-entry control in V1. | M1, V1 | D-29 step 4, D-46, P-08 |
| FR-STRAT-03 | A regime classifier shall produce a `RegimeAssessment` per instrument per cycle. M1 uses a null classifier (`not_evaluated`); V1 uses the deterministic classifier in `strategy-spec.md` §3. | M1, V1 | D-29 step 2 |
| FR-STRAT-04 | Only strategies eligible for the current regime may contribute to an entry. | V1 | D-29 step 3 |
| FR-STRAT-05 | An ensemble layer shall turn eligible signals into one `EnsembleDecision` per instrument per decision time, including explicit conflict and no-trade outcomes. M1 uses single-strategy pass-through; V1 uses R-01 until UD-07 is resolved. | M1, V1 | D-29 step 5, UD-07 |
| FR-STRAT-06 | Every signal shall carry strategy ID and version, feature-set version, and model version (null for rule-based strategies). | M1 | D-36 |
| FR-STRAT-07 | Minute-level data may only (a) refine entries and exits of 1h/4h decisions without changing direction or increasing size, or (b) power separately approved intraday strategies in an isolated, capped sleeve evaluated under stricter rules. | V1.5 | D-18, D-19 |
| FR-STRAT-08 | Strategy and model versions shall move through the champion/challenger lifecycle in `strategy-spec.md` §11; promotion requires an owner-approved `PromotionRecord`. | V1 should (registry), P10 (hosted) | D-43 |
| FR-STRAT-09 | Every path from any strategy or model to an order shall pass through the ensemble contract and the deterministic risk engine. No component other than the risk/sizing stage may create an `OrderIntent`. | M1 | D-13, D-30 |

### 5.5 Deterministic risk (FR-RISK)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-RISK-01 | The deterministic risk engine shall evaluate every entry and exit proposal and return a `RiskDecision` (`approved`, `modified`, `rejected`) that records every rule evaluated (rule catalogue RR-01 to RR-20, `architecture.md` §6.7). | M1 | D-13, D-29 step 6 |
| FR-RISK-02 | Hard limits shall override every strategy and model. AI and ML outputs may only act as recommendations that the engine clamps or rejects. | M1 | D-12 step 3, D-14 |
| FR-RISK-03 | Loss handling shall follow D-12: reassess signals and conditions every cycle; reduce size as drawdown accumulates (schedule UD-15); apply hard thresholds; stop opening new trades once the profile circuit breaker (UD-01) is reached. | M1 | D-12 |
| FR-RISK-04 | When the daily loss limit (UD-02) is reached, new entries shall be rejected until the next UTC day. Exits remain allowed. | M1 | D-11, D-12 |
| FR-RISK-05 | When the drawdown circuit breaker is reached, new entries shall be rejected until the owner resets the breaker (R-18). Exits remain allowed. | M1 | D-12 step 4 |
| FR-RISK-06 | Approved entries shall be sized deterministically: risk-per-trade budget (UD-03) divided by stop distance (UD-16), multiplied by the loss-scaling multiplier, then clamped by tier cap, speculative cap, total exposure cap, reserve floor, and available cash; quantities are rounded down. | M1 | D-29 step 7, D-32 |
| FR-RISK-07 | Concentration, exposure, reserve, and open-position limits shall be enforced per profile and tier (H-01 to H-04, UD-04, UD-12, UD-13). | M1 | D-27 |
| FR-RISK-08 | Cooldowns shall block new entries for a strategy-instrument pair after repeated losses (UD-17). | M1 | v0.1 §6.7 |
| FR-RISK-09 | Stale data, data-quality failure, invalid configuration, and repeated execution errors shall stop new orders (fail closed). | M1 | P-09 |
| FR-RISK-10 | The engine shall reject duplicate orders using deterministic idempotency keys and open-order checks. | M1 | D-47 |
| FR-RISK-11 | Adaptation shall stay inside the selected profile's boundaries and never switch profiles. V1 adaptation is defensive-only (R-22). | M1 | D-10 |
| FR-RISK-12 | A manual kill switch shall always be available, persist across restarts, block all new orders when engaged, and be disengaged only by an owner command with a reason. | M1 | D-35, R-15 |
| FR-RISK-13 | Risk values change only through owner-edited, versioned configuration. AI may propose values in a separate proposal; proposals are never applied automatically. | M1 | D-32 |
| FR-RISK-14 | Spot long-only: buys require available cash and sells cannot exceed the held quantity. | M1 | D-03 |

### 5.6 Execution (FR-EXEC)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-EXEC-01 | Execution shall use a framework-neutral `ExecutionAdapter` interface. Only simulated, paper, dry-run, or sandbox adapters may be registered; the registry rejects anything else. | M1 | D-02, D-03, D-44 |
| FR-EXEC-02 | An execution gate shall re-validate each `OrderIntent` immediately before submission (gate checks EG-01 to EG-05, `architecture.md` §6.9) and reject oversized, unlinked, duplicate, expired, or disabled-state orders. | M1 | D-47 |
| FR-EXEC-03 | In paper mode, approved orders shall execute automatically without a per-trade approval click. | M1 | D-33, D-34 |
| FR-EXEC-04 | Orders shall follow the state machine `accepted → open → partially_filled → filled`, or end in `canceled`, `rejected`, `expired`, or `error`. | M1 | v0.1 §6.9 |
| FR-EXEC-05 | Retries shall only be attempted for idempotent operations. | M1 | v0.1 §6.9 |
| FR-EXEC-06 | Internal positions shall be reconciled against adapter state after every fill; a mismatch engages the kill switch. | M1 (simulator), V1 (forward paper) | v0.1 §6.9, §9.2 |
| FR-EXEC-07 | The simulator shall fill market orders at the next bar open adjusted by slippage, charge fees, enforce minimum notional, never fill outside the bar's observed range, and execute attached protective stops intrabar. | M1 | v0.1 §8.2 |

### 5.7 Journal and explanations (FR-JRNL)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-JRNL-01 | Every decision cycle shall write `TradeEvent` records for the complete decision chain: snapshot, features, regime, signals, ensemble decision, risk decision, order intent, execution report, position update. | M1 | D-29 step 9 |
| FR-JRNL-02 | Every `OrderIntent` shall reference its signal IDs, strategy and model versions, risk decision ID, `config_hash`, and market-data timestamp. `trader journal verify` shall prove this for every order. | M1 | D-36 |
| FR-JRNL-03 | Order intents shall be journaled before submission; if the journal write fails, nothing is submitted. | M1 | R-05 |
| FR-JRNL-04 | The journal shall be append-only and hash-chained; tampering shall be detectable. | M1 | v0.1 §9.3 |
| FR-JRNL-05 | Human-readable explanations shall be generated from recorded facts (templates in V1). AI-written explanations (later) must cite journal event IDs and are never the source of truth. | V1 | D-31, v0.1 §6.10 |

### 5.8 Evaluation and reporting (FR-EVAL)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-EVAL-01 | Each backtest report shall include total and annualized return, fees, slippage cost, maximum drawdown, and comparison with cash, buy-and-hold, and equal-weight benchmarks. | M1 | D-46 |
| FR-EVAL-02 | Reports shall include the v0.1 evaluation views (volatility, downside deviation, Sharpe-like and Sortino-like ratios, Calmar, profit factor, win rate, turnover, exposure, trade count, holding period). | M1 (core subset), V1 (all) | v0.1 §6.11 |
| FR-EVAL-03 | Reports shall count rejected proposals by reason code. | M1 | v0.1 §6.11 |
| FR-EVAL-04 | Reports shall break down performance by regime. | V1 | D-29, v0.1 §6.11 |
| FR-EVAL-05 | Every report shall carry a disclaimer that results are simulated and profitability is not guaranteed, and a provenance banner listing every effective risk value that is a hypothesis or experiment input. | M1 | D-07, D-28, R-02 |

### 5.9 Research and promotion (FR-RSCH)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-RSCH-01 | Every experiment shall produce an `ExperimentRecord` with a reproduction command and code revision. | M1 (slice run), V1 | v0.1 §15 |
| FR-RSCH-02 | Evaluation shall use time-ordered splits and walk-forward folds; random splits are not used for primary evaluation. | V1 | v0.1 §8.1 |
| FR-RSCH-03 | Intraday allocation caps of 5%, 10%, 15%, and 20% shall be tested (with a 0% control) before any intraday cap is approved. | V1.5 | D-20 |
| FR-RSCH-04 | Promotion of a strategy, ensemble, or model into the active paper trader shall require an owner-approved `PromotionRecord` that cites evidence; promotion is never automatic. | V1 should, P10 | D-32, D-43 |
| FR-RSCH-05 | The research environment shall be separated from the active paper trader; only champion bundles backed by a `PromotionRecord` may be loaded by the active trader. | V1 (local), P10 (hosted) | D-42, D-43 |

### 5.10 User experience (FR-UX)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-UX-01 | A Typer CLI shall provide `profile validate|compile`, `data synth|import|fetch|validate|list`, `backtest run`, `report show`, `journal verify`, and `killswitch status|engage|disengage`. | M1 | D-39, D-40 |
| FR-UX-02 | A dashboard shall show portfolio, positions, signals, risk state, and strategy performance. It is read-only for trading actions except the kill switch. | V2 | D-39 |
| FR-UX-03 | A conversational interface shall accept objectives, directives, questions, and explanation requests. Directives compile into *proposed* profile changes that require validation and owner approval. | V2 | D-31, D-32, D-39 |
| FR-UX-04 | UI work shall not be a dependency of any phase P0 to P7. | All | D-41 |

### 5.11 Operations (FR-OPS)

| ID | Requirement | Stage | Source |
|---|---|---|---|
| FR-OPS-01 | The full research workflow shall run locally from a fresh checkout. | M1 | D-42 |
| FR-OPS-02 | A continuously running hosted paper trader shall provide monitoring, signal generation, risk checks, simulated execution, journaling, and alerts. | P10 | D-42, UD-09, UD-10 |
| FR-OPS-03 | Logs shall be structured JSON with correlation IDs. | M1 | RT-10 |
| FR-OPS-04 | No secrets are needed for M1. Future keys must be sandbox or read-only, must never carry withdrawal permission, and must be kept out of source control. | M1 | P-10, v0.1 §9.1 |
| FR-OPS-05 | The kill switch shall be operable in every deployment. | M1, P10 | D-35 |

---

## 6. Nonfunctional requirements

| ID | Requirement | Verification |
|---|---|---|
| NFR-01 | **Determinism.** Identical inputs (dataset hashes, `config_hash`, code revision) produce byte-identical journal content hashes and report JSON. | T-43 |
| NFR-02 | **Framework neutrality.** The `trader.domain` package imports only the standard library and Pydantic. | T-47 |
| NFR-03 | **Fail closed.** Missing, stale, invalid, or unresolved inputs stop new orders; no code path substitutes defaults for unresolved risk values. | T-07, T-23, T-44 |
| NFR-04 | **Auditability.** Append-only journal with hash chain; UTC timestamps; versions attached to every decision. | T-37, T-38, T-39 |
| NFR-05 | **Numeric precision.** Money and quantities use `Decimal`; quantities round down; rounding rules are documented. | Unit tests in T-25 |
| NFR-06 | **Test depth (RECOMMENDATION).** At least 95% branch coverage for `trader.risk` and `trader.execution`, and 85% overall. | Coverage report |
| NFR-07 | **Performance (RECOMMENDATION).** A backtest of two instruments over five years of 1h candles completes in under 120 seconds on a typical laptop. | Benchmark test (non-blocking) |
| NFR-08 | **Observability.** JSON logs with `run_id`, `cycle_id`, and `correlation_id`. | T-42 log assertions |
| NFR-09 | **Security and least privilege.** No secrets in the repository; no withdrawal, transfer, margin, or live-order code paths. | T-46 |
| NFR-10 | **Portability.** Runs on macOS, Linux, and Windows with Python 3.11 or later via `uv`. | Fresh-checkout check |
| NFR-11 | **Maintainability.** `ruff` clean, `mypy --strict` clean for `trader.domain` and `trader.risk`. | CI commands |
| NFR-12 | **Documentation.** The specification package lives in `docs/spec/`; ADRs in `docs/decisions/`; blockers in `BLOCKERS.md`. | Review |

## 7. Safety boundaries

| ID | Boundary | Enforcement | Source |
|---|---|---|---|
| SAFE-01 | Simulated funds only. `funds` is the constant `simulated`; there is no real-money mode, flag, or adapter. | Schema constants, adapter allowlist, T-03, T-46 | D-02 |
| SAFE-02 | No leverage, margin, derivatives trading, or short selling. Spot long-only. | Schema constants, RR-04, RR-08, T-34 | D-03 |
| SAFE-03 | No withdrawals or transfers. No such functions exist; any future API key must lack withdrawal permission. | T-46, FR-OPS-04 | D-03, P-10 |
| SAFE-04 | No unrestricted trade placement. Orders exist only as `OrderIntent` objects linked to approved `RiskDecision` objects and re-checked by the execution gate. There is no "place arbitrary order" command. | EG-01, T-24, FR-STRAT-09 | D-03 |
| SAFE-05 | Deterministic risk has final authority; AI may recommend but not bypass limits or set D-32 items. | RR catalogue, FR-RISK-13 | D-13, D-14, D-32 |
| SAFE-06 | Fail closed on missing, stale, invalid, or unresolved inputs. | FR-PROF-07, FR-RISK-09 | P-09 |
| SAFE-07 | A manual kill switch is always available and persisted. | FR-RISK-12, T-30, T-45 | D-35 |
| SAFE-08 | Reports and explanations never claim or imply guaranteed profitability. | FR-EVAL-05, T-48 | D-07 |
| SAFE-09 | Promotion is never automatic. | FR-RSCH-04 | D-43 |
| SAFE-10 | Aggressive behavior exists only through an explicitly selected Aggressive profile; the system never escalates profiles. | FR-PROF-03, T-04 | D-06 |
| SAFE-11 | High-frequency and latency-arbitrage trading are excluded: decision bars are at least one minute, and the profile lists both styles as excluded. | Schema, FR-STRAT-07 | D-21 |
| SAFE-12 | Unresolved financial-risk values are never defaulted. | FR-PROF-07, T-07 | Kickoff quality bar |

## 8. Success metrics

Engineering and safety metrics have fixed targets. Trading-outcome metrics are measured and compared with baselines; their numeric targets are UD-21.

| ID | Metric | Target |
|---|---|---|
| SM-01 | Orders executed without an approved `RiskDecision` | 0 |
| SM-02 | Orders traceable to signal, strategy/model versions, risk decision, configuration, and market-data timestamp (D-36) | 100% (`trader journal verify` passes) |
| SM-03 | D-47 rejection categories covered by passing tests | 7 of 7 |
| SM-04 | Reruns with identical inputs producing identical journal hashes | 100% |
| SM-05 | Strategy results reported net of costs and against at least four baselines (cash, buy-and-hold BTC, buy-and-hold ETH, equal-weight) | 100% |
| SM-06 | Experiments with a complete `ExperimentRecord` and working reproduction command | 100% |
| SM-07 | Risk-adjusted performance (Sortino-like, Calmar) versus benchmarks across walk-forward folds | Measured; target UD-21 |
| SM-08 | Maximum drawdown versus the selected profile's circuit breaker | Measured; target UD-21 |
| SM-09 | Consistency (share of positive months; dispersion of rolling 90-day returns) | Measured; target UD-21 |
| SM-10 | Fee and slippage burden as a share of gross profit | Measured; reported in every run |
| SM-11 | Time from fresh checkout to first slice report, excluding data download (RECOMMENDATION) | 15 minutes or less |

## 9. Assumptions

| ID | Assumption |
|---|---|
| A-01 | Single owner-operator; no multi-user access control in V1. |
| A-02 | Accounting currency is USD; simulated capital is not linked to any real account. |
| A-03 | Spot instruments only, long-only. This follows from D-03 (no leverage) and v0.1 §2.1 (spot only). |
| A-04 | "Paper", "dry-run", and "simulated" are treated as equivalent no-real-funds modes. |
| A-05 | At 1h and 4h cadence, sub-second latency does not matter; no co-location or latency optimization is needed. |
| A-06 | Publicly available historical data may be used for research, subject to the provider's terms. |
| A-07 | Paper results may differ from live execution (v0.1 ADR-001 consequence). |
| A-08 | At a $2,500 account size, venue fees can be a large share of returns for short holding periods; cost assumptions must be conservative and stress-tested. |
| A-09 | BTC and ETH remain listed and liquid on the chosen venue during evaluation periods. |
| A-10 | "Minimum reserve range" is interpreted as a pair `[floor, defensive ceiling]`: cash never falls below the floor, and defensive adaptation may raise the required reserve up to the ceiling. To be confirmed in UD-04. |
| A-11 | The owner's machine runs macOS, Linux, or Windows with Python 3.11 or later. |

---

## 10. Unresolved decisions

Each item gives: why it matters, a small set of options, a clearly labelled recommendation, and where it must be resolved. Recommendations are **not approved values**. Until the owner resolves an item, its value stays `TBD` in `risk-profile.schema.yaml` and the eligibility rules, and any run that needs it fails closed (exit code 3). Research backtests may test option values only through an experiment parameter set (`experiment-plan.md` §11), which is labelled in every report.

### UD-01: Exact Conservative, Balanced, and Aggressive drawdown thresholds

- **Why it matters.** The portfolio drawdown circuit breaker is the point at which the system stops opening new trades (D-12 step 4). It defines what "controlled drawdown" (D-05) means for each profile (D-11), anchors the loss-scaling schedule (UD-15), and bounds promotion gates (UD-08). Too tight and the system halts in ordinary volatility; too loose and losses grow large before it halts.
- **Options** (peak-to-trough decline of total equity, Conservative / Balanced / Aggressive):
  - A: 8% / 12% / 20%
  - B: 10% / 15% / 25%
  - C: 12% / 20% / 30%
- **Recommendation (UD-01):** Option B as the starting candidate, confirmed with EXP-2026-003 by checking how often each candidate would have tripped for the baselines across walk-forward folds. BTC and ETH have historically had deep peak-to-trough declines, so with up to 70% gross Core exposure under H-01 a Balanced breaker in the low teens may trip often; 15% is a reasonable midpoint to test first.
- **Resolve before:** activating any profile for paper trading (P5). Record in `configs/risk/<profile>.yaml` (`status: approved`, `approved_by`, `approved_on`) and in this section.

### UD-02: Exact daily-loss limits

- **Why it matters.** Limits damage from a single bad day or a malfunction, and sets how often the UTC-day lockout triggers (FR-RISK-04). It must sit below the drawdown breaker and above risk per trade.
- **Options** (loss of equity versus equity at 00:00 UTC, Conservative / Balanced / Aggressive):
  - A: 2% / 3% / 5%
  - B: 1.5% / 3% / 5%
  - C: 3% / 5% / 8%
- **Recommendation (UD-02):** Option A. With Balanced risk per trade near 1% (UD-03), three full stop-outs in one day reach the limit.
- **Resolve before:** paper activation (P5).

### UD-03: Exact risk-per-trade limits

- **Why it matters.** The main sizing driver (FR-RISK-06). It sets the loss when a hard stop is hit and how many consecutive losses reach the daily limit and the breaker.
- **Options** (equity at risk to the hard stop, Conservative / Balanced / Aggressive):
  - A: 0.5% / 1.0% / 1.5%
  - B: 0.25% / 0.5% / 1.0%
  - C: 0.75% / 1.25% / 2.0%
- **Recommendation (UD-03):** Option A. Note for testing: with Balanced at 1% and ATR-based stops on 1h bars, the H-01 35% Core cap will often bind before the risk budget does. This is expected and is why caps are clamps (`modified`), not errors.
- **Resolve before:** paper activation (P5); explored in EXP-2026-003.

### UD-04: Exact reserve ranges

- **Why it matters.** Cash held back for fees, slippage, and defensive adaptation. It interacts with the total exposure cap (policy rule RP-01). Interpretation assumed in A-10: `[floor, defensive ceiling]`.
- **Options** (floor–ceiling, Conservative / Balanced / Aggressive):
  - A: 30–60% / 20–40% / 10–25%
  - B: 40–70% / 25–50% / 15–30%
  - C: 20–50% / 10–30% / 5–20%
- **Recommendation (UD-04):** Option A, and confirm the floor/ceiling interpretation at the same time.
- **Resolve before:** paper activation (P5).

### UD-05: First paper broker/exchange adapter

- **Why it matters.** Determines fill realism, fee schedule, symbol conventions, sandbox availability, and API stability. Strongly linked to UD-20.
- **Options:**
  - A: Internal deterministic simulator only, fed by public market data (no keys).
  - B: Freqtrade dry-run (framework-simulated fills against live exchange data).
  - C: Exchange spot sandbox or testnet through CCXT (availability varies by venue; sandbox order books may not resemble real markets).
  - D: A venue's own paper-trading account API.
- **Recommendation (UD-05):** Option A for M1 and the V1 MVP, because it is deterministic, framework-neutral, needs no credentials, and is already required for backtests. Evaluate B in the Freqtrade spike (BL-032). Consider C or D only after a venue is chosen under UD-20 and only with keys that cannot withdraw.
- **Resolve before:** forward paper trading (BL-027 in P5). Not needed for M1.

### UD-06: Exact tradable Major and Speculative asset lists

- **Why it matters.** Expands the universe beyond Core under tier caps H-02 to H-04, and determines exposure to less liquid assets.
- **Options:**
  - A: No Major or Speculative assets in V1 (Core only); revisit in V1.5.
  - B: A small owner-curated Major list (3 to 5 liquid large-cap assets), each passing eligibility.
  - C: A rules-generated list (top N by liquidity on the chosen venue that pass eligibility), refreshed monthly and reviewed by the owner.
- **Recommendation (UD-06):** A for V1; C with owner review in V1.5 as the first step toward dynamic discovery (D-23). Keep Speculative empty until speculative-tier evaluation rules have been exercised in research.
- **Resolve before:** any non-Core asset appears in a paper session. Research may screen candidates in EXP-2026-008.

### UD-07: Signal-conflict weighting formula

- **Why it matters.** Determines how several strategies combine (D-29 step 5). Fitted weights are easy to overfit; opaque weighting would undermine D-30.
- **Options:**
  - A: Equal-weight vote with opposition veto (R-01).
  - B: Regime-conditional static weights estimated on walk-forward training folds.
  - C: Weighting by calibrated confidence or probability.
  - D: A learned meta-model (stacking).
- **Recommendation (UD-07):** A for V1 (P7). Run B and C as challengers in EXP-2026-006. Allow D only as an ML challenger (P8), never promoted automatically.
- **Resolve before:** an ensemble configuration enters a champion bundle (P7 exit). Not needed for M1 (single strategy).

### UD-08: Promotion thresholds for challengers

- **Why it matters.** Gives an objective bar for promotion (D-43) so noise is not promoted.
- **Options:**
  - A: Relative thresholds: the challenger beats the champion and the best simple baseline on risk-adjusted metrics in a minimum share of walk-forward folds.
  - B: Absolute thresholds: minimum Sortino-like and Calmar ratios and maximum drawdown.
  - C: Statistical thresholds: bootstrap confidence that the challenger's excess return over the champion is positive, adjusted for the number of configurations tried.
- **Recommendation (UD-08):** A plus C, with the profile breaker as an absolute ceiling: (1) better Sortino-like and Calmar than the champion and the best simple baseline in at least two-thirds of test folds under `base` costs, and no worse than the best simple baseline under `stress` costs overall; (2) maximum drawdown in every fold at or below the selected profile's breaker (UD-01); (3) block-bootstrap probability of outperforming the champion of at least 0.8; (4) at least 50 closed trades across test folds (100 for intraday); (5) at least 30 days of shadow running in `observe_only` mode with signals identical to a deterministic replay of the same period.
- **Resolve before:** the first promotion into the active paper trader (P10) and any champion change.

### UD-09: Hosted cloud provider and topology

- **Why it matters.** Cost, reliability, security, and operating effort of the continuously running paper trader (D-42).
- **Options:**
  - A: One small always-on virtual machine or container host running Docker Compose, with PostgreSQL (managed or local) and object storage.
  - B: Scheduled serverless jobs per decision cycle, a managed database, and object storage; the kill switch exposed through a small authenticated endpoint.
  - C: A managed container service with a persistent volume.
  - D: A home server.
- **Recommendation (UD-09):** A: a single always-on instance (no horizontal scaling), because continuous monitoring, alerts, and an always-available kill switch are simpler with one process. Choose the provider by cost and familiarity, in a dedicated account for this project.
- **Resolve before:** P10.

### UD-10: Alert channels

- **Why it matters.** The owner must learn quickly about kill-switch engagement, breaker trips, reconciliation failures, and repeated errors.
- **Options:** A: email. B: a chat bot (for example Slack, Discord, or Telegram). C: a push-notification service. D: SMS.
- **Recommendation (UD-10):** Console and log alerts locally in V1 (BL-030). For hosted operation, one push or chat channel for critical alerts plus email for daily summaries, using the alert taxonomy in `architecture.md` §9.4.
- **Resolve before:** P10.

### UD-11: Retention durations

- **Why it matters.** Reproducibility (datasets referenced by experiments must survive), storage cost, and audit history.
- **Options:**
  - A: Keep everything indefinitely.
  - B: Tiered: journals, experiment records, promotion records, and referenced datasets kept indefinitely; unreferenced raw minute data kept 12 months; logs kept 90 days.
  - C: Minimal: delete datasets after N months unless pinned.
- **Recommendation (UD-11):** B, with the rule that a dataset is never deleted while any `ExperimentRecord` or `PromotionRecord` references it. V1 implements no automatic deletion.
- **Resolve before:** P10 (hosted storage).

### UD-12: Total exposure cap and maximum open positions per profile

- **Why it matters.** Required risk-profile fields (kickoff deliverable 4) that bound aggregate market exposure and complexity.
- **Options** (Conservative / Balanced / Aggressive):
  - Total exposure cap: A 50% / 80% / 90%; B 40% / 70% / 85%; C 60% / 80% / 95%.
  - Maximum open positions: A 3 / 5 / 8; B 2 / 4 / 6.
- **Recommendation (UD-12):** exposure option A and positions option A. Exposure plus the reserve floor must not exceed 100% (RP-01): with UD-04 option A, Balanced is 80% + 20% = 100%. In V1 only two Core instruments exist, so at most two positions can be open regardless.
- **Resolve before:** paper activation (P5).

### UD-13: Tier caps for Conservative and Aggressive; production status of Balanced hypotheses

- **Why it matters.** D-27 requires profile- and tier-dependent concentration limits, but hypotheses exist only for Balanced (H-01 to H-04).
- **Options:**
  - A: Scale the Balanced hypotheses: Conservative Core 25%, Major 10%, Speculative 2.5%, Speculative total 5%; Aggressive Core 45%, Major 20%, Speculative 7.5%, Speculative total 15%.
  - B: Owner-chosen sets without scaling.
  - C: Volatility-targeted caps per asset.
- **Recommendation (UD-13):** A, recorded as new hypotheses once approved and tested in EXP-2026-003. Balanced H-01 to H-04 stay hypotheses (D-28) and remain usable as labelled starting values.
- **Resolve before:** selecting Conservative or Aggressive outside an experiment.

### UD-14: Selected intraday allocation cap and intraday sleeve loss limits

- **Why it matters.** D-19 requires an isolated, capped allocation; D-20 requires testing 5%, 10%, 15%, and 20% without assuming the largest is best. The sleeve also needs its own loss limits so intraday losses cannot consume the core portfolio.
- **Options:**
  - Cap: one of 5%, 10%, 15%, 20% (D-20), or keep the sleeve disabled if no cap improves results against the 0% control.
  - Sleeve limits: A: same percentages as the profile limits, applied to sleeve equity; B: stricter, half of the profile limits.
- **Recommendation (UD-14):** choose the cap with EXP-2026-004 using its selection rule (the smallest cap with robust improvement; ties go to the smaller cap). Use sleeve limits option B.
- **Resolve before:** enabling any intraday strategy.

### UD-15: Loss-response size-reduction schedule and adaptation bounds

- **Why it matters.** D-12 step 2 ("reduce position sizes as losses accumulate") and D-10 (adaptation inside the profile) need concrete deterministic rules.
- **Options:**
  - Schedule: A: stepwise by share of the breaker drawdown: multiplier 1.0 below one-third, 0.5 from one-third to two-thirds, 0.25 from two-thirds to the breaker, 0 at the breaker. B: linear, `1 − drawdown / breaker`. C: halve after each consecutive losing trade and reset after a winner.
  - Upward adaptation bound: A: none in V1 (multiplier never above 1). B: up to 1.25 times within hard caps. C: up to 1.5 times.
- **Recommendation (UD-15):** schedule A (interpretable and testable) and upward bound A for V1 (R-22), revisited after V1 evidence. D-10 permits upward adaptation but does not require it.
- **Resolve before:** paper activation (schedule); enabling upward adaptation (bound).

### UD-16: Hard stop-loss policy

- **Why it matters.** Risk-per-trade sizing needs a stop distance, and D-32 reserves the hard stop-loss policy for deterministic, owner-approved configuration.
- **Options:**
  - A: ATR multiple: stop = entry − k × ATR(n) on the decision timeframe.
  - B: Fixed percentage below entry.
  - C: Strategy invalidation level, bounded by minimum and maximum distances.
  - D: A price stop combined with a time stop.
- **Recommendation (UD-16):** A with n = 14 and k = 2.0 as the first candidate; test k of 1.5, 2.0, and 3.0 in EXP-2026-003. Strategy exits still apply in addition to the hard stop.
- **Resolve before:** paper activation (P5).

### UD-17: Cooldown, exchange-error, stale-data grace, clock-skew, and external reconciliation thresholds

- **Why it matters.** Operational fail-closed tuning (FR-RISK-08, FR-RISK-09).
- **Options:**
  - Cooldown: A: profile-specific (Conservative 2 losses and 48 h, Balanced 3 and 24 h, Aggressive 4 and 12 h). B: 3 losses and 24 h for every profile.
  - Consecutive execution errors before the kill switch auto-engages: 3 or 5.
  - Paper-mode grace after a candle's expected availability before data counts as stale: 60, 120, or 300 seconds.
  - Consecutive stale cycles before escalation to the kill switch: 2, 3, or 5.
  - Clock-skew tolerance against a reference time source: 2, 5, or 10 seconds.
  - External-adapter reconciliation tolerance: zero, or the venue's lot size. (The internal simulator always requires an exact match; this is not configurable.)
- **Recommendation (UD-17):** cooldown option A; 3 consecutive execution errors; 120 seconds of grace; 3 stale cycles; 5 seconds of clock skew; external-adapter quantity tolerance equal to the venue's lot size.
- **Resolve before:** paper activation (cooldown, error count); forward paper trading (grace, skew, escalation, external reconciliation).

### UD-18: Asset eligibility thresholds

- **Why it matters.** D-25 and D-26 make eligibility mandatory for every asset, but no thresholds exist. Spread cannot be measured from candle-only V1 data.
- **Options:**
  - A: Absolute thresholds per tier on the chosen venue: 30-day median daily quote volume of at least $50M (Core), $10M (Major), $1M (Speculative); continuous history of at least 365, 365, and 180 days; median relative spread of at most 10, 25, and 50 basis points when spread data exists.
  - B: Rank-based: top N assets by venue volume.
  - C: External market-capitalization data (a V2 source).
  - Spread handling in V1: (i) `not_applicable` on candle-only data with conservative cost assumptions (R-21); (ii) an OHLC-based spread estimator; (iii) require ticker snapshots from the venue.
- **Recommendation (UD-18):** A with spread handling (i), making spread mandatory once V1.5 order-book data exists. The owner should confirm that (i) is an acceptable reading of D-26 for V1.
- **Resolve before:** paper activation. Backtests may use experiment values.

### UD-19: Post-halt liquidation policy and kill-switch effect on open positions

- **Why it matters.** v0.1 §9.2 requires a separate, explicit liquidation policy; D-32 reserves kill-switch behavior for deterministic owner configuration.
- **Interim behavior until resolved (carried forward from v0.1):** engaging the kill switch blocks all new orders; open positions and their attached protective stops are left unchanged; nothing is liquidated automatically.
- **Options:** A: keep the interim behavior permanently. B: flatten all positions at market on engagement. C: staged de-risking (for example cut non-Core first, then halve Core). D: interim behavior by default, plus an explicit owner command to flatten through the execution gate.
- **Recommendation (UD-19):** D.
- **Resolve before:** paper activation (P5).

### UD-20: V1 market-data venue, quote currency, and venue cost schedule

- **Why it matters.** Data realism and accounting. USD-quoted pairs avoid stablecoin depeg risk in accounting; fees at a small account size materially affect results (A-08).
- **Options:** A: a USD-quoted spot venue the owner can legally access. B: a stablecoin-quoted venue, treating the stablecoin as USD with explicit depeg-risk notes. C: an aggregated data vendor.
- **Recommendation (UD-20):** A, the same venue as the eventual paper adapter (UD-05), with the fee tier a $2,500 account would actually pay recorded as the `base` cost scenario. Until then, use the `low`/`base`/`stress` grid (R-10).
- **Resolve before:** downloading real datasets for evaluation experiments (EXP-2026-002 onward). M1 can run on synthetic data or owner-supplied CSV files.

### UD-21: Numeric success targets for the objective

- **Why it matters.** D-05 is qualitative, and v0.1 Q4 ("definition of a successful result") is still open. Success metrics SM-07 to SM-09 need targets.
- **Options:** A: relative targets (beat the benchmarks on risk-adjusted terms with drawdown inside the breaker). B: absolute targets (for example a minimum annualized return with a maximum drawdown). C: consistency targets (share of positive months, rolling-window Sortino above zero).
- **Recommendation (UD-21):** A plus C. Avoid absolute return targets, which encourage overfitting and conflict with D-07.
- **Resolve before:** V1 MVP exit (M2) and UD-08.

### 10.1 Resolution procedure

1. The owner chooses an option (or another value) and records it in this section with the date.
2. The owner updates the affected configuration file: `status: approved`, `approved_by`, `approved_on`, new `version`.
3. An ADR is added under `docs/decisions/` if the choice changes architecture.
4. `trader profile validate` must then show the blocker removed. Values chosen by AI are never applied without this procedure (D-32).

---

## 11. Acceptance criteria for V1

Test IDs refer to the catalogue in `execution-plan.md` §6, replicated in `code-session-handoff.md` §9.

### 11.1 M1: vertical slice (all must pass)

| ID | Acceptance criterion | Verified by |
|---|---|---|
| AC-01 | `trader profile validate configs/profiles/balanced-paper.yaml --environment backtest --experiment experiments/EXP-2026-001-vertical-slice.yaml` exits 0 and the compiled output shows paper capital 2500, risk profile `balanced`, `funds: simulated`, and a `config_hash`. | T-01, T-10 |
| AC-02 | Invalid profiles are rejected with exit code 2 and a specific error code: schema-invalid documents, forbidden safety values, Aggressive without acknowledgement, `draft` or `suspended` profiles used for a run, and contradictory limits. | T-02 to T-06 |
| AC-03 | Without an experiment parameter set, `trader backtest run` with the shipped Balanced profile exits 3 and lists the UD IDs of every unresolved required value; it creates no order events. | T-07, T-44 |
| AC-04 | Experiment parameter sets are rejected in the `paper` environment and cannot change approved values or safety constants. | T-08, T-09 |
| AC-05 | Datasets with conflicting duplicates, misordered or misaligned timestamps, OHLC inconsistencies, or naive timestamps fail validation with named check IDs; gaps are recorded as warnings; the same input always produces the same dataset hash; datasets cannot be overwritten. | T-11 to T-18 |
| AC-06 | Cash, buy-and-hold BTC, buy-and-hold ETH, and equal-weight benchmarks are computed and match hand-calculated values on a synthetic series. | T-21 |
| AC-07 | `sma_trend` emits `SignalCandidate` objects with no quantity fields, using only candles closed at or before decision time (future-perturbation test). | T-19, T-20 |
| AC-08 | Unsupported assets are rejected: unknown, blocked, disallowed, non-spot, outside the profile universe, or ineligible. | T-22 |
| AC-09 | Stale data is rejected with `STALE_DATA`. | T-23 |
| AC-10 | Excessive sizing is rejected: an `OrderIntent` above its approved quantity is rejected by the execution gate with `EXCESSIVE_SIZE`, and no approved size ever exceeds a cap (property test). | T-24, T-25 |
| AC-11 | Duplicate orders are rejected with `DUPLICATE_ORDER`. | T-26, T-41 |
| AC-12 | Breached loss limits are rejected: daily loss limit (`DAILY_LOSS_LIMIT` until the next UTC day), drawdown breaker (`CIRCUIT_BREAKER_OPEN`, latched), and size reduction as drawdown deepens. | T-27 to T-29, T-33 |
| AC-13 | Disabled execution states are rejected: kill switch engaged, profile suspended, `observe_only` mode, execution disabled; a reconciliation mismatch engages the kill switch. | T-30 to T-32, T-36 |
| AC-14 | Every `OrderIntent` is traceable (D-36); `trader journal verify` exits 0 on an untouched journal and 4 on a tampered one. | T-37 to T-40 |
| AC-15 | The report includes returns, fees, slippage, maximum drawdown, benchmark comparison, trade count, rejections by reason code, the provenance banner, and the disclaimer; simulated fills follow the documented fee, slippage, and next-bar rules. | T-35, T-42, T-48 |
| AC-16 | Two runs with identical inputs produce identical journal content hashes and report JSON (excluding the run-metadata block). | T-43 |
| AC-17 | No live-trading, withdrawal, transfer, margin, or leverage code path exists, and spot long-only limits hold at run time; the domain package is framework-neutral. | T-34, T-46, T-47 |
| AC-18 | The kill switch can be engaged, inspected, and disengaged from the CLI, and its state survives a process restart. | T-45 |
| AC-19 | From a fresh checkout, the commands in `code-session-handoff.md` §10 succeed; `ruff`, `mypy`, and `pytest` are clean. | Fresh-checkout run |

### 11.2 M2: V1 MVP (in addition to M1)

| ID | Acceptance criterion | Verified by |
|---|---|---|
| AC-20 | At least four strategies (`sma_trend`, time-series momentum, mean reversion, volatility breakout) run through the deterministic regime classifier and the R-01 ensemble; conflicts produce `no_trade` with `SIGNAL_CONFLICT`. | T-53 to T-55 |
| AC-21 | Walk-forward evaluation with a sealed holdout produces `ExperimentRecord` files; holdout access is logged and limited. | T-56, T-57 |
| AC-22 | Reports include regime-level performance and the full v0.1 evaluation views. | T-42 (extended) |
| AC-23 | A local forward paper session runs the same pipeline on live public candles with autonomous execution after risk approval, reconciliation after every fill, and auto-engagement of the kill switch on integrity failures. It refuses to start while any paper-required value is unresolved. | T-50 to T-52 |
| AC-24 | Templated explanations exist for every decision, generated only from journal facts. | T-49 |
| AC-25 | EXP-2026-002 (baseline comparison) and EXP-2026-003 (risk-parameter evidence) are complete, giving the owner evidence to resolve UD-01 to UD-04, UD-12, UD-15, and UD-16. | Review |

---

## 12. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue. Canonical decision registers (D-01 to D-47, H-01 to H-05, RT-01 to RT-11, R-01 to R-24, UD-01 to UD-21), requirements, safety boundaries, success metrics, assumptions, unresolved-decision analysis, and V1 acceptance criteria. Version aligned with `architecture.md` v0.2. |
