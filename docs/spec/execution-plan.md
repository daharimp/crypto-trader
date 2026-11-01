# Execution Plan

**Document status:** Draft for owner review
**Version:** 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Depends on:** all other package documents; replaces `architecture.md` v0.1 §11 (implementation sequence) and §12 (backlog)
**Used by:** `code-session-handoff.md`

Status labels: **APPROVED** (D-nn), **HYPOTHESIS** (H-nn), **RECOMMENDATION** (R-nn), **UNRESOLVED** (UD-nn).

---

## 1. Purpose and how to use this plan

This plan divides implementation into the eleven phases the kickoff requires (P0 to P10), each with dependencies, outputs, test requirements, and exit criteria. The phases describe capabilities. Delivery happens in milestones that cut across phases: the first milestone (M1) is a thin vertical slice through P0 to P6, and later milestones complete each phase.

The sequence follows D-40 (CLI and core engine first) and D-41 (UI never blocks the pipeline). Every phase stays inside the safety boundary: paper, dry-run, or simulated funds only, and no leverage, withdrawals, or real-money execution (D-02, D-03).

## 2. Milestones

| Milestone | Scope | Phases touched | Exit |
|---|---|---|---|
| **M1: V1 vertical slice** | The kickoff slice (D-46) with all required rejection tests (D-47) | P0 to P6 (slice scope) | All M1 acceptance criteria AC-01 to AC-19 pass (`product-requirements.md` §11.1) |
| **M2: V1 MVP** | Full baselines, regime classifier, R-01 ensemble, walk-forward, explanations, local forward paper trading | P4 to P7 (full scope) | AC-20 to AC-25 pass |
| **M3: V1.5** | V1.5 data, minute-level refinement, intraday sleeve experiments, Major tier, optional ML challenger, Freqtrade decision | P2, P7, P8 | Experiment records for EXP-2026-004, -006, -007, -008; owner decisions on UD-06, UD-07, UD-14 |
| **M4: V2** | Dashboard, conversation, hosted paper trader, V2 data | P9, P10 | 30 days of hosted paper operation without integrity failures |

## 3. Phase dependency map

```text
P0 Foundation
 └─> P1 Schemas / profile compiler
      └─> P2 Data pipeline
           └─> P3 Baseline backtesting
                └─> P4 Deterministic risk engine
                     └─> P5 Paper execution
                          └─> P6 Journal and evaluation ──────────────┐
                               └─> P7 Ensemble / regime layer          │
                                    └─> P8 Optional ML challenger      │
                                                                       ├─> P9 Dashboard / conversation
                                                                       │     (needs P6; never blocks P0-P7)
P5 + P6 + P7 champion + promotion tooling (BL-035) ────────────────────┴─> P10 Hosted paper deployment
```

| Phase | Depends on | Blocking decisions before the phase can exit |
|---|---|---|
| P0 Foundation | — | None |
| P1 Schemas/profile compiler | P0 | None (unresolved values become blockers, not defaults) |
| P2 Data pipeline | P1 | UD-20 only for real-data evaluation experiments, not for M1 |
| P3 Baseline backtesting | P1, P2 | None |
| P4 Deterministic risk engine | P1, P2, P3 | None for backtests; paper activation needs UD-01 to UD-04, UD-12, UD-15 to UD-19 |
| P5 Paper execution | P4 | M1: none. Forward paper: UD-05, UD-17, UD-19, UD-20 and all paper-required risk values |
| P6 Journal and evaluation | P3, P4, P5 | None for M1; UD-21 for M2 exit |
| P7 Ensemble/regime layer | P3, P6 | UD-07 before an ensemble enters a champion bundle |
| P8 Optional ML challenger | P7 | UD-08 before any promotion |
| P9 Dashboard/conversation | P6 | None |
| P10 Hosted paper deployment | P5, P6, P7, BL-035 | UD-08, UD-09, UD-10, UD-11 |

---

## 4. Phases

### 4.1 P0 Foundation

- **Goal:** a repository that installs, tests, and lints cleanly from a fresh checkout.
- **Backlog:** BL-001, BL-002.
- **Outputs:** repository layout (`code-session-handoff.md` §3); `pyproject.toml` and `uv.lock`; ruff, mypy, and pytest configuration; `.gitignore` (including `data/`) and `.env.example` (no secrets needed); `docs/spec/` with this package; ADR template and ADR-001 to ADR-018 files; `BLOCKERS.md`; common utilities (clock, ID generator, canonical JSON, hashing, JSON logging with correlation IDs); `trader version` command.
- **Tests:** smoke test (package imports; `trader version`); unit tests for canonical JSON, hashing, clock, ID generation.
- **Exit criteria:** `uv sync`, `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` succeed from a fresh checkout.
- **Change from v0.1:** "Choose the first paper/sandbox adapter" is now UD-05 and no longer blocks P0.

### 4.2 P1 Schemas and profile compiler

- **Goal:** invalid, incomplete, or contradictory configuration can never run.
- **Depends on:** P0.
- **Backlog:** BL-003, BL-004, BL-005, BL-006.
- **Outputs:** the 13 framework-neutral contracts and supporting types (`architecture.md` §17); schema files; YAML loaders; profile compiler with policy rules PV-01 to PV-10 and RP-01 to RP-12; experiment parameter overlay (backtest only); blocker report; `config_hash`; shipped configuration files; `trader profile validate` and `trader profile compile`.
- **Tests:** T-01 to T-10.
- **Exit criteria:** the shipped Balanced profile is blocked (exit 3, UD IDs listed) without an experiment parameter set and compiles with EXP-2026-001; every invalid-profile test passes.

### 4.3 P2 Data pipeline

- **Goal:** reproducible, quality-checked, immutable BTC and ETH datasets.
- **Depends on:** P1.
- **Backlog:** BL-007, BL-008, BL-009.
- **Outputs:** CSV, synthetic, and optional CCXT public-data candle providers; checks DQ-01 to DQ-12; dataset store with manifests; asset registry; eligibility evaluation; `UniverseSnapshot`; `trader data synth|import|fetch|validate|list`.
- **Tests:** T-11 to T-18; T-22 (eligibility part); T-62 (V1).
- **Exit criteria:** BTC and ETH datasets are created and validated reproducibly with stable dataset IDs.

### 4.4 P3 Baseline backtesting

- **Goal:** benchmarks and the first trend/momentum baseline running on a deterministic bar-replay clock.
- **Depends on:** P1, P2.
- **Backlog:** BL-010, BL-011, BL-012, BL-017.
- **Outputs:** feature set `features-m1`; benchmarks `bm_cash`, `bm_bh_btc`, `bm_bh_eth`, `bm_ew_btc_eth`; `sma_trend` 1.0.0; null regime classifier; single-strategy pass-through ensemble; bar-replay runner skeleton.
- **Tests:** T-19, T-20, T-21.
- **Exit criteria:** benchmark values match hand calculations; signals contain no size fields; the future-perturbation test passes.

### 4.5 P4 Deterministic risk engine

- **Goal:** every proposal passes through RR-01 to RR-20; no path bypasses them.
- **Depends on:** P1, P2, P3.
- **Backlog:** BL-013, BL-019.
- **Outputs:** rule catalogue with reason codes; deterministic sizing (`strategy-spec.md` §9); loss state (high-water mark, drawdown, UTC-day start equity); circuit breaker, daily lockout, cooldowns; persisted kill switch with CLI.
- **Tests:** T-22 to T-34.
- **Exit criteria:** every D-47 category is rejected under test; the property test shows approved sizes never exceed any cap.
- **Decision gate:** backtests run with experiment values. Paper activation needs the paper-required values resolved (§7).

### 4.6 P5 Paper execution

- **Goal:** approved intents execute automatically against simulated adapters only; positions reconcile.
- **Depends on:** P4.
- **Backlog:** BL-014, BL-015 (M1); BL-027, BL-028 (V1).
- **Outputs:** execution gate EG-01 to EG-05; adapter registry with allowlist; `SimulatedExecutionAdapter`; order state machine; portfolio ledger and `PositionSnapshot`; reconciliation. V1 adds the local forward paper session (scheduler, live public candles, the same pipeline, persisted state, auto-engage triggers) and profile activation.
- **Tests:** T-24, T-26, T-35, T-36, T-41 (M1); T-50 to T-52 (V1).
- **Exit criteria (M1):** orders execute only through the simulator; no code path to real funds exists.
- **Exit criteria (V1; RECOMMENDATION):** a local forward paper session runs for 7 consecutive days with zero integrity failures (journal, reconciliation, clock) and a successful kill-switch drill.
- **Decision gate:** forward paper trading needs UD-05, UD-17, UD-19, UD-20 and all paper-required risk values.

### 4.7 P6 Journal and evaluation

- **Goal:** every decision is traceable, and results are reported honestly against benchmarks.
- **Depends on:** P3, P4, P5.
- **Backlog:** BL-016, BL-018, BL-020 (M1); BL-021, BL-025, BL-026, BL-029, BL-030 (V1).
- **Outputs:** append-only hash-chained journal; `trader journal verify`; reports (JSON and Markdown) with disclaimer and provenance banner; `ExperimentRecord` writer. V1 adds templated explanations, the walk-forward harness, holdout sealing, regime-level and full-metric reporting, the risk-parameter evidence experiment (EXP-2026-003), and local alerts.
- **Tests:** T-37 to T-48 (M1); T-49, T-56, T-57 (V1).
- **Exit criteria (M1):** the vertical-slice definition of done (`code-session-handoff.md` §11).
- **Exit criteria (V1):** EXP-2026-002 and EXP-2026-003 records complete; the owner has the evidence to resolve UD-01 to UD-04, UD-12, UD-15, UD-16.

### 4.8 P7 Ensemble and regime layer

- **Goal:** the hybrid regime-aware ensemble (D-29) with transparent conflict handling.
- **Depends on:** P3, P6.
- **Backlog:** BL-022, BL-023, BL-024.
- **Outputs:** `tsmom`, `mean_reversion`, `volatility_breakout`, `random_entry`; deterministic regime classifier; regime eligibility matrix; R-01 ensemble.
- **Tests:** T-53 to T-55.
- **Exit criteria:** EXP-2026-005 and EXP-2026-006 records show whether the ensemble adds value over single strategies after costs.
- **Decision gate:** UD-07 before an ensemble enters a champion bundle.

### 4.9 P8 Optional ML challenger

- **Goal:** test whether ML adds stable value over non-ML baselines (ADR-004).
- **Depends on:** P7.
- **Backlog:** BL-040.
- **Outputs:** an ML challenger (FreqAI if ADR-003 is accepted, otherwise scikit-learn) in the research environment only, producing `SignalCandidate` objects.
- **Tests:** T-58; LA-06; LA-08.
- **Exit criteria:** ML is retained only if it adds stable value after costs and risk controls (v0.1 Phase 6 exit), shown in EXP-2026-007.
- **Decision gate:** UD-08 before any promotion.

### 4.10 P9 Dashboard and conversation

- **Goal:** the long-term hybrid experience (D-39) without touching the core safety model.
- **Depends on:** P6. Never a dependency of P0 to P7 (D-41).
- **Backlog:** BL-041, BL-042, BL-043.
- **Outputs:** read-only FastAPI service; dashboard (portfolio, positions, signals, risk state, strategy performance); conversational interface for objectives, directives, questions, and explanations. Directives compile into proposed profile changes that need validation and owner approval.
- **Tests:** T-65, T-66.
- **Exit criteria:** the dashboard offers no order placement (only the kill switch); conversation output never changes an active profile directly.

### 4.11 P10 Hosted paper deployment

- **Goal:** the continuously running hosted paper trader (D-42) with champion/challenger separation (D-43).
- **Depends on:** P5, P6, a P7 champion, and BL-035 (registry and promotion tooling).
- **Backlog:** BL-033, BL-044.
- **Outputs:** Docker image; hosted deployment (UD-09); champion bundles; promotion records; alerting (UD-10); backups and retention (UD-11); hosted paper threat model.
- **Tests:** T-59, T-60, T-61.
- **Exit criteria (RECOMMENDATION):** 30 days of hosted paper operation without integrity failures; kill-switch drill from the owner's device; restore-from-backup drill.
- **Decision gate:** UD-08, UD-09, UD-10, UD-11.

---

## 5. Prioritized V1 backlog

Priority levels: **P0-M1** = required for the vertical slice (implement in ID order); **P1-V1** = V1 MVP must-have; **P2-V1** = V1 should-have; **P3-Later** = V1.5 and beyond. Every item stays inside the safety boundary.

| ID | Priority | Phase | Item | Depends on | Tests / criteria | Blocking UD |
|---|---|---|---|---|---|---|
| BL-001 | P0-M1 | P0 | Repository scaffold, uv environment, ruff/mypy/pytest config, `.gitignore`, `.env.example`, `BLOCKERS.md`, `docs/spec/`, ADR template and stubs | — | P0 exit | — |
| BL-002 | P0-M1 | P0 | Common utilities: UTC clock (simulated and wall), deterministic ID generator, canonical JSON, SHA-256 hashing, Decimal helpers, JSON logging with correlation IDs | BL-001 | Unit tests | — |
| BL-003 | P0-M1 | P1 | The 13 domain contracts and supporting types as Pydantic v2 models | BL-002 | T-47 | — |
| BL-004 | P0-M1 | P1 | Schema files and YAML loaders; JSON-schema validation of shipped configs | BL-003 | T-02, T-03 | — |
| BL-005 | P0-M1 | P1 | Profile compiler: policy rules, experiment overlay, provenance, blocker report, `config_hash`; `trader profile validate|compile` | BL-004 | T-01, T-04 to T-10 | — |
| BL-006 | P0-M1 | P1 | Ship configs: Balanced profile, three risk profiles, asset registry, eligibility rules, cost scenarios, `sma_trend` registry entry, EXP-2026-001 | BL-004 | T-01, T-07 | — |
| BL-007 | P0-M1 | P2 | Candle providers: CSV import, deterministic synthetic generator, optional CCXT public OHLCV (explicit venue, no keys, mocked in tests) | BL-003 | T-16 | — |
| BL-008 | P0-M1 | P2 | Data-quality checks DQ-01 to DQ-12, dataset manifests, immutable dataset store | BL-007 | T-11 to T-18 | — |
| BL-009 | P0-M1 | P2 | Asset registry, point-in-time eligibility, `UniverseSnapshot` | BL-008 | T-22 | — |
| BL-010 | P0-M1 | P3 | Causal feature pipeline `features-m1` (SMA 20, SMA 50, ATR 14) with lineage | BL-008 | T-20 | — |
| BL-011 | P0-M1 | P3 | Benchmarks: cash, buy-and-hold BTC, buy-and-hold ETH, equal-weight | BL-008 | T-21 | — |
| BL-012 | P0-M1 | P3 | `sma_trend` 1.0.0; null regime classifier; single-strategy pass-through ensemble | BL-010 | T-19, T-20 | — |
| BL-013 | P0-M1 | P4 | Risk engine RR-01 to RR-20, sizing, loss state, breaker, daily lockout, cooldowns | BL-005, BL-009, BL-012 | T-22 to T-34 | — (experiment values) |
| BL-014 | P0-M1 | P5 | Execution gate EG-01 to EG-05, adapter allowlist, `SimulatedExecutionAdapter`, order state machine | BL-013 | T-24, T-26, T-35 | — |
| BL-015 | P0-M1 | P5 | Portfolio ledger, mark-to-market, `PositionSnapshot`, reconciliation | BL-014 | T-36 | — |
| BL-016 | P0-M1 | P6 | Journal: SQLite append-only store, hash chain, journal-before-act, `trader journal verify` | BL-003 | T-37 to T-41 | — |
| BL-017 | P0-M1 | P3 to P6 | Bar-replay backtest runner and decision-cycle orchestrator; `trader backtest run` | BL-011 to BL-016 | T-42 to T-44 | — |
| BL-018 | P0-M1 | P6 | Metrics and reports (JSON and Markdown) with disclaimer and provenance banner; `trader report show` | BL-017 | T-42, T-48 | — |
| BL-019 | P0-M1 | P4 | Kill switch: persisted operational store; `trader killswitch status|engage|disengage` | BL-002 | T-30, T-45 | — |
| BL-020 | P0-M1 | All | Safety and neutrality static tests; full M1 test suite; README run instructions | All above | T-46, T-47, AC-19 | — |
| BL-021 | P1-V1 | P6 | Templated explanations generated from journal facts | BL-016 | T-49 | — |
| BL-022 | P1-V1 | P7 | Baselines `tsmom`, `mean_reversion`, `volatility_breakout`, `random_entry` | BL-012 | T-19 pattern | — |
| BL-023 | P1-V1 | P7 | Deterministic regime classifier and eligibility matrix | BL-010 | T-53, T-55 | — |
| BL-024 | P1-V1 | P7 | R-01 ensemble (equal weight, opposition veto, exit precedence) | BL-022, BL-023 | T-54 | UD-07 (for champion use) |
| BL-025 | P1-V1 | P6 | Walk-forward harness, holdout seal and access log, `ExperimentRecord` automation | BL-017 | T-56, T-57 | — |
| BL-026 | P1-V1 | P6 | Regime-level, full-metric, and rejection-reason reporting | BL-018, BL-023 | T-42 (extended) | — |
| BL-027 | P1-V1 | P5 | Local forward paper session: scheduler, live public candles, same pipeline, persisted state, reconciliation, auto-engage triggers | BL-017, BL-019 | T-50 to T-52 | UD-01 to UD-05, UD-12, UD-15 to UD-20 |
| BL-028 | P1-V1 | P5 | Profile activation and suspension commands with activation records | BL-005 | T-05, T-52 | — |
| BL-029 | P1-V1 | P6 | Run EXP-2026-002 (baselines) and EXP-2026-003 (risk-parameter evidence) on real data | BL-025 | AC-25 | UD-20 |
| BL-030 | P1-V1 | P6 | Local alerts (console and log file) using the alert taxonomy | BL-019 | T-61 (local part) | — |
| BL-031 | P2-V1 | P1 | CLI questionnaire producing a proposed `TradingProfile` (questions generated from the schema) | BL-005 | Proposal must validate | — |
| BL-032 | P2-V1 | P3 | Freqtrade evaluation spike: reproduce benchmark and `sma_trend` results on the same datasets; recommend on ADR-003 | BL-018 | Spike report | — |
| BL-033 | P2-V1 | P0 | Docker image for reproducibility (after M1, RT-11) | BL-020 | Image runs the M1 commands | — |
| BL-034 | P2-V1 | P6 | Automated robustness and cost-sensitivity report (RB-01 to RB-11) | BL-025 | Report review | — |
| BL-035 | P2-V1 | P6 | Strategy registry lifecycle states, `PromotionRecord`, champion bundle builder (no hosting) | BL-025 | T-59 | UD-08 (to promote) |
| BL-036 | P3-Later | P7 | Minute-level entry/exit refinement (Role A) | BL-024 | T-64 | — |
| BL-037 | P3-Later | P7 | Intraday sleeve and EXP-2026-004 cap matrix | BL-025 | T-63 | UD-14 (to enable) |
| BL-038 | P3-Later | P2 | V1.5 providers: order book, cross-asset, derivatives data (read-only) | BL-007 | T-62 | — |
| BL-039 | P3-Later | P2 | Major tier through eligibility screening (EXP-2026-008) | BL-038 | T-22 pattern | UD-06, UD-18 |
| BL-040 | P3-Later | P8 | ML challenger in research only | BL-024, BL-025 | T-58 | UD-08 (to promote) |
| BL-041 | P3-Later | P9 | Read-only local API (FastAPI) | BL-018 | T-65 | — |
| BL-042 | P3-Later | P9 | Dashboard | BL-041 | T-65 | — |
| BL-043 | P3-Later | P9 | Conversational interface (proposals only) | BL-041 | T-66 | — |
| BL-044 | P3-Later | P10 | Hosted paper trader, alerting, backups, hosted threat model | BL-027, BL-033, BL-035 | T-60, T-61 | UD-09, UD-10, UD-11 |
| BL-045 | P3-Later | P2 | V2 providers: news, on-chain, macro | BL-038 | T-62 pattern | — |
| BL-046 | P3-Later | P2 | Experimental social-sentiment research (research environment only) | BL-045 | — | — |
| BL-047 | P3-Later | P2 | Dynamic opportunity discovery (AI ranks eligible assets only) | BL-039 | Ranking never admits ineligible assets | UD-06, UD-18 |

---

## 6. Test catalogue

Test files live under `tests/`. M1 tests (T-01 to T-48) are fully specified in `code-session-handoff.md` §9. "D-47" marks the seven rejection categories the kickoff requires.

| ID | Test | Phase | Proves | AC |
|---|---|---|---|---|
| T-01 | Balanced profile compiles with EXP-2026-001: capital 2500, `funds: simulated`, `balanced`, `config_hash` | P1 | D-04, D-09 | AC-01 |
| T-02 | Schema-invalid profiles rejected (missing, wrong type, unknown fields) | P1 | D-47 invalid profiles | AC-02 |
| T-03 | Forbidden safety values rejected (funds, leverage, margin, shorting, withdrawals, transfers, real money, non-spot, live environment) | P1 | D-02, D-03 | AC-02 |
| T-04 | Aggressive without acknowledgement rejected | P1 | D-06 | AC-02 |
| T-05 | `draft` and `suspended` profiles cannot run; `validated` cannot run paper | P1 | D-47 invalid profiles | AC-02 |
| T-06 | Contradictions rejected (PV-01, PV-02, RP-01 to RP-06) | P1 | v0.1 §6.1 | AC-02 |
| T-07 | Unresolved values block the run: exit 3, UD IDs listed, no order events | P1 | Kickoff quality bar | AC-03 |
| T-08 | Experiment parameters refused in `paper` | P1 | R-02 | AC-04 |
| T-09 | Experiment parameters cannot override approved values, safety constants, or kill-switch policy | P1 | D-32 | AC-04 |
| T-10 | `config_hash` is deterministic; provenance labels correct; H-01 to H-04 shown as hypotheses | P1 | D-28, D-36 | AC-01 |
| T-11 | Conflicting duplicate candles rejected (DQ-05) | P2 | D-29 step 1 | AC-05 |
| T-12 | Misordered and misaligned timestamps handled (DQ-03, DQ-04) | P2 | D-29 step 1 | AC-05 |
| T-13 | OHLC inconsistencies rejected (DQ-07) | P2 | D-29 step 1 | AC-05 |
| T-14 | Naive timestamps rejected (DQ-02) | P2 | UTC policy | AC-05 |
| T-15 | Gaps recorded as warnings, never filled (DQ-06) | P2 | Fail closed | AC-05 |
| T-16 | Incomplete last candle dropped (DQ-11) | P2 | P-07 | AC-05 |
| T-17 | Same input gives the same dataset ID | P2 | P-06 | AC-05 |
| T-18 | Datasets cannot be overwritten; integrity mismatch exits 4 | P2 | Immutability | AC-05 |
| T-19 | `sma_trend` signal contract: no size fields; entry on cross up; exit while below | P3 | D-32, S-01 | AC-07 |
| T-20 | Future-perturbation test (LA-01) and feature causality (LA-02) | P3 | P-07 | AC-07 |
| T-21 | Benchmarks match hand calculations | P3 | D-46 | AC-06 |
| T-22 | Unsupported assets rejected: unknown, blocked, disallowed, outside universe, non-spot, ineligible (including unresolved thresholds and point-in-time history) | P4 | D-47 unsupported assets; D-25 | AC-08 |
| T-23 | Stale data rejected with `STALE_DATA` | P4 | D-47 stale data | AC-09 |
| T-24 | Execution gate rejects oversized, missing, or mismatched risk decisions (`EXCESSIVE_SIZE`, `RISK_DECISION_MISSING`, `RISK_DECISION_MISMATCH`) | P4/P5 | D-47 excessive sizing | AC-10 |
| T-25 | Property test: approved size never exceeds any cap; quantities round down | P4 | D-47 excessive sizing; D-27 | AC-10 |
| T-26 | Duplicate orders rejected (RR-07, EG-03) | P4/P5 | D-47 duplicate orders | AC-11 |
| T-27 | Daily loss limit blocks entries until the next UTC day; exits allowed | P4 | D-47 breached loss limits | AC-12 |
| T-28 | Circuit breaker latches; only owner reset reopens; exits allowed | P4 | D-47 breached loss limits; D-12 | AC-12 |
| T-29 | Loss-scaling schedule reduces size as drawdown grows | P4 | D-12 step 2 | AC-12 |
| T-30 | Kill switch blocks all new orders (RR-03 and EG-02) | P4 | D-47 disabled execution; D-35 | AC-13 |
| T-31 | Suspended profile blocks orders mid-run | P4 | D-47 disabled execution | AC-13 |
| T-32 | `observe_only` and execution-disabled create no orders | P4 | D-47 disabled execution | AC-13 |
| T-33 | Cooldown after consecutive losses | P4 | v0.1 §6.7 | AC-12 |
| T-34 | Spot long-only: no buy beyond cash, no sell beyond holdings | P4 | D-03 | AC-17 |
| T-35 | Simulator fill rules: next-bar open, slippage, fees, range clamp, stop gaps, minimum notional (LA-03) | P5 | v0.1 §8.2 | AC-15 |
| T-36 | Portfolio accounting and reconciliation; a mismatch engages the kill switch | P5 | v0.1 §6.9 | AC-13 |
| T-37 | Journal rejects UPDATE and DELETE | P6 | v0.1 §9.3 | AC-14 |
| T-38 | Hash chain verifies; tampering detected (verify exits 4) | P6 | v0.1 §9.3 | AC-14 |
| T-39 | Every order traceable to signal, versions, risk decision, configuration, market-data timestamp | P6 | D-36 | AC-14 |
| T-40 | Journal-before-act: a journal failure means nothing is submitted | P6 | R-05 | AC-14 |
| T-41 | Re-running a cycle creates no duplicate orders | P5/P6 | D-47 duplicate orders | AC-11 |
| T-42 | End-to-end slice through the CLI: synth, validate, backtest, report; report and log contents | P6 | D-46 | AC-15 |
| T-43 | Two identical runs give identical journal hashes and report JSON | P6 | NFR-01 | AC-16 |
| T-44 | End-to-end run without an experiment set is blocked (exit 3, `RUN_BLOCKED`, no orders) | P6 | Fail closed | AC-03 |
| T-45 | Kill-switch CLI engage, status, disengage; state survives restart | P4 | D-35 | AC-18 |
| T-46 | No forbidden capabilities: no withdrawal, transfer, margin, leverage, or live-order code paths; adapter allowlist is simulated-only | All | D-02, D-03 | AC-17 |
| T-47 | `trader.domain` imports only the standard library and Pydantic | P1 | D-44 | AC-17 |
| T-48 | Report has the disclaimer, the provenance banner, and no profitability claims | P6 | D-07 | AC-15 |
| T-49 | Explanations generated only from journal facts | P6 (V1) | v0.1 §6.10 | AC-24 |
| T-50 | Forward paper session uses the same pipeline code as backtests | P5 (V1) | P-03 | AC-23 |
| T-51 | Reconciliation mismatch and clock skew auto-engage the kill switch in forward paper | P5 (V1) | `architecture.md` §9.2 | AC-23 |
| T-52 | Forward paper refuses unresolved or experiment values and inactive profiles | P5 (V1) | R-02, PV-08 | AC-23 |
| T-53 | Regime classifier is deterministic and causal | P7 | D-29 step 2 | AC-20 |
| T-54 | Ensemble conflict rules C-01 to C-08 (worked examples in `strategy-spec.md` §7.2) | P7 | R-01 | AC-20 |
| T-55 | Regime eligibility gates entries but never exits | P7 | D-29 step 3 | AC-20 |
| T-56 | Walk-forward split integrity: ordering, no overlap, embargo | P6 (V1) | v0.1 §8.1 | AC-21 |
| T-57 | Holdout seal and access log (LA-07) | P6 (V1) | R-11 | AC-21 |
| T-58 | ML challenger cannot emit quantities, stops, or limits | P8 | D-32 | — |
| T-59 | Promotion requires an owner-signed `PromotionRecord`; automation can only demote | P6/P10 | D-43 | — |
| T-60 | Hosted trader refuses unpromoted bundles | P10 | D-43 | — |
| T-61 | Critical events raise alerts | P6/P10 | D-42 | — |
| T-62 | The V1 pipeline runs with only V1 providers registered; missing later providers do not affect it | P2 (V1) | D-38 | — |
| T-63 | Intraday sleeve isolation: sleeve losses cannot consume core capital; sleeve disabled while cap is TBD | P7 (V1.5) | D-19 | — |
| T-64 | Minute-level refinement cannot change direction or increase size | P7 (V1.5) | D-18 | — |
| T-65 | Dashboard and API expose no order placement (kill switch only) | P9 | D-41, SAFE-04 | — |
| T-66 | Conversational directives produce proposals only | P9 | D-32 | — |

## 7. Decision gates by activity

| Activity | Must be resolved first |
|---|---|
| M1 vertical slice | Nothing. Unresolved values are supplied as labelled experiment inputs (EXP-2026-001) |
| Evaluation experiments on real data (EXP-2026-002 onward) | UD-20 |
| Activating a profile for paper trading | UD-01, UD-02, UD-03, UD-04, UD-12, UD-15 (schedule), UD-16, UD-17 (cooldown, error count), UD-18, UD-19 |
| Forward paper session | The activation list, plus UD-05, UD-17 (grace, skew, escalation), UD-20 |
| Selecting Conservative or Aggressive outside experiments | UD-13 and that profile's values |
| Enabling any intraday strategy | UD-14 (after EXP-2026-004) and separate strategy approval |
| Adding Major or Speculative assets to paper | UD-06, UD-18 |
| Ensemble in a champion bundle | UD-07 |
| Upward adaptation | UD-15 (bound) |
| Any promotion | UD-08, UD-21 |
| Hosted deployment | UD-09, UD-10, UD-11 |

## 8. Project risks and mitigations

| ID | Risk | Mitigation |
|---|---|---|
| PR-01 | Unresolved risk values delay paper activation | Run EXP-2026-003 early; §7 gives the owner a single decision checklist |
| PR-02 | Overfitting mistaken for skill | Walk-forward, sealed holdout, OF-01 to OF-12, random-entry control |
| PR-03 | Fee drag on a $2,500 account | `stress` costs, turnover and fee-burden reporting, 1h versus 4h comparison |
| PR-04 | Data quality or venue mismatch | DQ checks, immutable datasets, UD-20 |
| PR-05 | Framework lock-in | Framework-neutral contracts (D-44); adapter boundary; T-47 |
| PR-06 | UI scope creep delays the pipeline | D-41; P9 depends on P6 and blocks nothing |
| PR-07 | Silent safety regression | Safety tests T-03, T-34, T-46 run in every test command |
| PR-08 | Scheduler or clock faults in forward paper | Idempotency keys, clock-skew check, kill-switch auto-engage |

## 9. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue: milestones, phases P0 to P10 with dependencies, outputs, tests, and exit criteria; prioritized backlog BL-001 to BL-047; test catalogue T-01 to T-66; decision gates; project risks. Replaces `architecture.md` v0.1 §11 and §12. |
