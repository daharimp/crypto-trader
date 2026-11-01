# Traceability Audit

**Document status:** Final audit for package version 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Scope:** Checks every decision, hypothesis, unresolved item, required deliverable, required contract, slice step, and quality-bar item in `cowork-kickoff.md` (and the approved design-decisions summary) against the generated package.

---

## 1. Method

1. **Registers.** Each kickoff decision was quoted verbatim into `product-requirements.md` §3.2 (D-01 to D-47), each hypothesis into §3.3 (H-01 to H-05), and each unresolved item into §3.5 and §10 (UD-01 to UD-21).
2. **Automated index.** A script indexed every occurrence of every D, H, UD, and RT identifier by document and section. Section 3 below is generated from that index; "Realized in" excludes the register itself, change logs, and the README.
3. **Automated consistency checks** (results in §12): 32 schema test cases (6 valid documents and 26 deliberately invalid variants); resolution of every cross-document section reference (118 in total); identifier range checks; completeness of the four-part analysis for every UD item; equality of configuration blocks duplicated between documents; equality of reason codes and event types between architecture and handoff; absence of guaranteed-profit language.
4. **Manual review** of each kickoff deliverable bullet (§7), contract (§8), slice step and rejection category (§9), technical recommendation (§10), and quality-bar item (§11).

Abbreviations in tables: PRD = `product-requirements.md`, ARCH = `architecture.md`, TPS = `trading-profile.schema.yaml`, RPS = `risk-profile.schema.yaml`, STRAT = `strategy-spec.md`, DATA = `data-architecture.md`, EXP = `experiment-plan.md`, EXEC = `execution-plan.md`, HAND = `code-session-handoff.md`. "Doc N" means the Nth YAML document in a schema file.

## 2. Summary

| Item checked | Count | Covered | Omissions |
|---|---|---|---|
| Approved decisions (kickoff and decisions summary) | 47 | 47 | 0 |
| Decisions-summary lines (approved, hypotheses, safety) | 26 | 26 | 0 |
| Recorded hypotheses | 5 | 5 | 0 |
| Kickoff "unresolved decisions to preserve" | 11 | 11, each with why, options, recommendation, resolve-before | 0 |
| Additional unresolved items found while formalizing | 10 | 10, same four parts | 0 |
| Required deliverables | 9 | 9 | 0 |
| Required content items across the nine deliverables | 100 | 100 | 0 |
| Required framework-neutral contracts | 13 | 13, each with owner, inputs, outputs, validation, versioning | 0 |
| V1 slice steps | 10 | 10 | 0 |
| Required rejection categories (D-47) | 7 | 7, each with tests | 0 |
| Recommended technical-direction items | 11 | 11, each with a verdict | 0 |
| Quality-bar items | 8 | 8 | 0 |

**Result:** no omissions found. Eighteen interpretations need owner confirmation (§13); none changes an approved decision.

## 3. Approved decisions (D-01 to D-47)

| ID | Decision (short form; verbatim text in PRD §3.2) | How the package realizes it | Realized in | Status |
|---|---|---|---|---|
| D-01 | Research and engineering project | Research framing in the problem statement and purpose; no production or real-money scope | PRD §1; ARCH §1; HAND §1 | Covered |
| D-02 | Paper, dry-run, or simulated funds only | `funds: simulated` constant in both schemas; simulated-only adapter allowlist (EG-04); SAFE-01; T-03, T-46 | PRD front matter, §4, §5.1, §5.6, §7; ARCH front matter, §2.1, §6.1, §12, §13 +1; TPS schema, Doc 2.capital; RPS schema; EXEC §1, §6 | Covered |
| D-03 | No real-money autonomy, leverage, withdrawals, unrestricted placement | Schema constants (leverage, margin, shorting, withdrawals, transfers all false); no live adapter; non-goals; SAFE-02 to SAFE-04; T-03, T-34, T-46 | PRD front matter, §4, §5.5, §5.6, §7 +1; ARCH front matter, §2.2, §12, §13; TPS schema; RPS schema; EXEC §1, §6 | Covered |
| D-04 | Simulated portfolio $2,500 | `paper_capital_usd: 2500` in the Balanced profile; FR-PROF-02; T-01 | PRD §5.1; ARCH §6.1, §13; TPS schema, Doc 2.capital; STRAT §9.6; EXEC §6; HAND §1 | Covered |
| D-05 | Objective: strong returns, consistency, controlled drawdown | Objective statement is a schema constant; FR-PROF-04; numeric targets left open as UD-21 | PRD §5.1, UD-01, UD-21; ARCH §13; TPS schema, Doc 2.objective; RPS Doc 3; HAND §1, §6.2, §6.3 | Covered |
| D-06 | Aggressive only as an explicit profile | Aggressive needs an acknowledgement block (schema rule, PV-03); Aggressive `explicit_selection_required: true`; SAFE-10; T-04 | PRD §5.1, §7; TPS schema, Doc 2.risk_selection; RPS schema, Doc 4; EXEC §6 | Covered |
| D-07 | No guaranteed profitability | `guaranteed_profitability_assumed: false`; report disclaimer; SAFE-08; T-48 | PRD §1, §5.1, §5.8, §7, UD-21; ARCH §2.2; TPS schema, Doc 2.objective; EXP §1; EXEC §6; HAND §1 | Covered |
| D-08 | Hybrid risk-profile model | Three selectable `RiskProfile` documents under one schema; ADR-005 | ARCH ADR-005; TPS schema; RPS schema | Covered |
| D-09 | User selects profile, initially Balanced | Initial profile selects `balanced`; Balanced `initial_default: true`; `profile_switching: owner_only` | PRD §5.1; ARCH §6.1; TPS schema, Doc 2.risk_selection; RPS schema, Doc 3; EXEC §6; HAND §1, §6.3 | Covered |
| D-10 | Adapt inside profile boundaries | `adaptation: within_selected_profile_bounds`; `sizing.adaptation` (defensive in V1, upward bound UD-15); see IN-03 | PRD §3.5, §5.5, UD-15; TPS schema, Doc 2.risk_selection; RPS schema; HAND §1 | Covered |
| D-11 | Profile-dependent thresholds | Per-profile `limits` objects; breaker values held as UD-01 | PRD §5.5, UD-01; ARCH §13; RPS schema | Covered |
| D-12 | Hybrid loss handling (4 steps) | `loss_response` steps 1 to 4 as constants plus schedule (UD-15); RR-09, RR-10, RR-13; loss-response flow; T-27 to T-29 | PRD §3.5, §5.5, UD-01, UD-15; ARCH §7.6, §9.2, §13; RPS schema; STRAT §9.4; EXEC §6; HAND §1 | Covered |
| D-13 | Deterministic code has final authority | P-01; only the risk engine creates `OrderIntent`; execution gate; `deterministic_final_authority: true` | PRD front matter, §5.4, §5.5, §7; ARCH front matter, §1, §3; RPS schema; STRAT §1 | Covered |
| D-14 | AI/ML recommend, never bypass | Authority matrix; `ai_may_override_limits: false`; FR-RISK-02 | PRD §5.5, §7; ARCH §3, ADR-005, ADR-008; RPS schema; STRAT §1; HAND §1 | Covered |
| D-15 | Adaptive holding period | `holding_period: adaptive`; `expected_horizon: null` in `sma_trend` | PRD §4; ARCH §2.1, §6.1, §6.5, §13; TPS schema, Doc 2.horizon; STRAT §4.3, §5; HAND §1 | Covered |
| D-16 | 1h and 4h decision timeframes | `primary_decision_timeframes` limited to 1h and 4h; S-05 | PRD §4, §5.3; ARCH §2.1, §6.1, §13; TPS schema, Doc 2.horizon; STRAT §5; DATA §4.1; HAND §1 | Covered |
| D-17 | About 1 hour to several days | `typical_holding` constant, explicitly not an enforced limit | ARCH §13; TPS schema, Doc 2.horizon | Covered |
| D-18 | Two roles for minute data | `minute_data.permitted_roles`; rules M-01 to M-05 and I-01 to I-05; T-64 | PRD §5.4; ARCH ADR-012; TPS schema, Doc 2.horizon; STRAT §5, §8, §8.2; EXEC §6 | Covered |
| D-19 | Isolated, capped intraday allocation; stricter evaluation | Isolated sleeve with separate ledger, cap, and loss limits (UD-14); RR-12; E-I1 to E-I7; T-63 | PRD §5.4, UD-14; TPS schema, Doc 2.horizon; RPS schema; STRAT §5, §8.2; EXEC §6 | Covered |
| D-20 | Test 5/10/15/20% intraday caps | `candidates_under_test: [5, 10, 15, 20]`; EXP-2026-004 matrix and selection rule; RP-07 | PRD §3.5, §4, §5.9, UD-14; TPS schema; RPS schema, schema.x-policy-rules; STRAT §8.2, §8.3; EXP §7 | Covered |
| D-21 | No HFT or latency arbitrage | `excluded_styles` must list both styles; SAFE-11; I-05 | PRD §4, §7; ARCH §2.2, §13, ADR-012; TPS schema, Doc 2.horizon; STRAT §8; HAND §1 | Covered |
| D-22 | Rules-based liquid universe | `construction: rules_based`; eligibility rules; FR-UNIV | PRD §4, §5.2; ARCH §2.1, §13, ADR-011; TPS schema, Doc 2.universe | Covered |
| D-23 | Toward dynamic discovery | `rules_based_with_dynamic_discovery` reserved; FR-UNIV-06; BL-047 | PRD §4, §5.2, UD-06; TPS schema | Covered |
| D-24 | Manual allowlist | `manual_allowlist`; FR-UNIV-02 | PRD §5.2; ARCH §6.13; TPS schema, Doc 2.universe | Covered |
| D-25 | Eligibility for every asset | `eligibility_required_for_all: true`; point-in-time eligibility for every asset including Core; RR-05; T-22 | PRD §3.5, §5.2, UD-18; ARCH §4.3, §6.13; TPS schema, Doc 2.universe; DATA §4.4; EXEC §6; HAND §1 | Covered |
| D-26 | Core/Major/Speculative/Blocked tiers | Asset registry tiers; tier rules; Blocked criteria (spread handling: IN-02) | PRD §3.5, §5.2, UD-18; ARCH §2.1, §13; TPS schema, Doc 2.universe; DATA §4.2, §4.4, §4.5; HAND §1 | Covered |
| D-27 | Profile- and tier-dependent concentration limits | `concentration` object per profile, aggregated across sleeves; RR-15, RR-16 | PRD §5.2, §5.5, UD-13; ARCH §13; RPS schema; EXEC §6 | Covered |
| D-28 | Balanced caps are testable hypotheses | Balanced caps carry `status: hypothesis` and H refs; report provenance banner; EXP-2026-003 | PRD §3.3, §5.2, §5.8, UD-13; ARCH ADR-011; RPS schema, Doc 3; EXEC §6; HAND §6.3 | Covered |
| D-29 | Hybrid regime-aware ensemble pipeline | Nine-stage pipeline (architecture §7.2, strategy-spec §2); M1 implements every stage, some as pass-through | PRD §4, §5.3, §5.4, §5.5, §5.7 +2; ARCH §1, §6.12, §7.2, §13, ADR-006; TPS schema; STRAT §1, §2, §5; EXEC §4.8, §6; HAND §1 | Covered |
| D-30 | No single opaque model in control | Ensemble contract is mandatory; no model creates orders; ADR-006 | PRD §5.4, UD-07; ARCH ADR-006; STRAT §1 | Covered |
| D-31 | Areas AI may directly influence | Authority matrix 'directly influence' rows; `RegimeAssessment.method`; ranking separate from eligibility | PRD §5.2, §5.7, §5.10; ARCH §1, §4.3, §6.6, §6.13, ADR-002 +1; TPS schema; STRAT §3.5, §11; DATA §2, §4.6 | Covered |
| D-32 | Areas AI may only recommend | Authority matrix 'recommend only' rows; schema constants; S-01; sizing boundary; owner-only promotion; T-58, T-66 | PRD §3.5, §5.4, §5.5, §5.9, §5.10 +4; ARCH §1, §4.3, ADR-002, ADR-008, §17.4; RPS schema, schema.x-policy-rules; STRAT §4.4, §5, §9.1, §11; EXP §1, §7; EXEC §6 | Covered |
| D-33 | Paper trades execute automatically | `autonomy_mode: paper_autonomous`; FR-EXEC-03 | PRD §4, §5.6; ARCH §1, §2.1, §13, ADR-007; TPS schema, Doc 2.execution; HAND §1 | Covered |
| D-34 | No approval click after risk validation | `per_trade_approval_required: false` constant | PRD §5.6; ARCH §1, §13; TPS schema, Doc 2.execution; HAND §1 | Covered |
| D-35 | Manual kill switch | Kill-switch policy; persisted state; CLI commands; T-30, T-45 | PRD §4, §5.5, §5.11, §7; ARCH §2.1, §9.2; RPS schema; EXEC §6; HAND §1 | Covered |
| D-36 | Order traceability | `OrderIntent` traceability fields; traceability chain; `trader journal verify`; T-39 | PRD §5.1, §5.2, §5.4, §5.7, §8 +1; ARCH §1, §6.10, ADR-007, §17.2; EXEC §6; HAND §1, §7.11, §9.2, §11 | Covered |
| D-37 | Progressive provider architecture | Source roadmap; `DataSourceRef` tier mapping | PRD §4, §5.3; ARCH §2.2, §6.3, §13, ADR-010; TPS schema, Doc 2.data_sources; DATA §1, §2 | Covered |
| D-38 | V1 independent of later sources | V1 needs only a `CandleProvider`; PV-07; T-62 | PRD §5.3; ARCH §13, ADR-010; TPS schema, schema.x-policy-rules; DATA §1; EXEC §6 | Covered |
| D-39 | Hybrid conversation, dashboard, CLI | FR-UX-01 to FR-UX-03; phase P9 | PRD §4, §5.1, §5.10; ARCH §1, ADR-013; EXEC §4.10 | Covered |
| D-40 | CLI and core engine first | M1 is CLI plus core engine; ADR-013; handoff rule 8 | PRD §4, §5.10; ARCH §1, §2.2, §5.3, §13, §16; EXEC §1 | Covered |
| D-41 | UI never blocks the pipeline | FR-UX-04; P9 depends on P6 and blocks nothing | PRD §4, §5.10; ARCH §2.2, §5.3, ADR-013; EXEC §1, §4.10, §6, §8 | Covered |
| D-42 | Local research plus hosted paper trader | Local and hosted deployment views; phase P10 | PRD §4, §5.9, §5.11, UD-09; ARCH §13, ADR-014; EXEC §4.11, §6 | Covered |
| D-43 | Champion/challenger, explicit promotion | Research versus active separation; champion bundles; automation can only demote; G-11; T-59, T-60 | PRD §4, §5.4, §5.9, §7, UD-08; ARCH §1, §2.2, §3, §6.15, ADR-009; TPS schema; STRAT §11, §12; EXP §1; EXEC §4.11, §6 | Covered |
| D-44 | Framework-neutral contracts | `trader.domain` imports only stdlib and Pydantic; adapter boundary; T-47 | PRD §5.6; ARCH §2.1, §4.4, §5.2, ADR-015, §17.1; TPS schema; EXEC §6, §8 | Covered |
| D-45 | Thirteen required contracts | 13 contracts with owner, inputs, outputs, validation, versioning (architecture §17.2); fields in handoff §7.3 | PRD §5.1; ARCH ADR-015; TPS schema | Covered |
| D-46 | V1 vertical slice | M1 slice definition and bar loop (handoff §1.1, §5.2); AC-01 to AC-19 | PRD §3.3, §4, §5.3, §5.4, §5.8; ARCH §5.2; EXP §2; EXEC §2, §6 | Covered |
| D-47 | Required rejection tests | Seven categories mapped to tests (handoff §11 item 4; audit §9) | PRD §4, §5.1, §5.3, §5.5, §5.6 +1; EXEC §2, §4.5, §6; HAND §1.1, §9.2, §11 | Covered |

## 4. Decisions-summary cross-check

| # | Decisions-summary line | Register IDs |
|---|---|---|
| 1 | "Initial simulated capital: $2,500." | D-04 |
| 2 | "Objective: balance strong returns with consistency and controlled drawdown; aggression is profile-dependent." | D-05, D-06 |
| 3 | "Hybrid risk model: adaptive behavior within hard selected-profile boundaries." | D-08, D-10 |
| 4 | "Profile-dependent drawdown limits." | D-11 |
| 5 | "Hybrid loss response: adaptive reassessment followed by deterministic hard stops." | D-12 |
| 6 | "Adaptive holding periods, primarily 1-hour and 4-hour signals for V1." | D-15, D-16 |
| 7 | "Minute-level data can refine entries/exits and power approved isolated intraday strategies." | D-18, D-19 |
| 8 | "Intraday allocation determined by testing candidate caps of 5%, 10%, 15%, and 20%." | D-20 |
| 9 | "Start with a rules-based liquid-asset universe, then move toward dynamic discovery." | D-22, D-23 |
| 10 | "Support user-provided asset allowlists subject to eligibility checks." | D-24, D-25 |
| 11 | "Tier assets as Core, Major, Speculative, and Blocked." | D-26 |
| 12 | "Use profile- and tier-dependent concentration limits." | D-27 |
| 13 | "Hybrid regime-aware strategy ensemble." | D-29 |
| 14 | "Autonomous execution in paper mode after deterministic risk approval." | D-33, D-34 |
| 15 | "Progressive data architecture from market data toward derivatives, news, on-chain, macro, and experimental sentiment." | D-37 |
| 16 | "Hybrid conversation, dashboard, and CLI experience; CLI/core engine first." | D-39, D-40 |
| 17 | "Local research/development plus eventual continuously running hosted paper trader." | D-42 |
| 18 | "Champion/challenger separation with explicit promotion." | D-43 |
| 19 to 22 | Balanced Core 35%, Major 15%, Speculative 5%, total Speculative 10% | H-01 to H-04 |
| 23 | "BTC and ETH are the initial vertical-slice assets." | H-05 |
| 24 | "Paper, dry-run, or simulated funds only in the MVP." | D-02 |
| 25 | "No leverage, withdrawals, or unrestricted autonomous real-money trading." | D-03 |
| 26 | "Deterministic risk controls have final authority." | D-13 |

## 5. Hypotheses (H-01 to H-05)

| ID | Value | Where it is used | Labelled as hypothesis? |
|---|---|---|---|
| H-01 | Balanced Core cap 35% per asset | RPS Doc 3 `concentration.core_per_asset_cap_pct` (`status: hypothesis`, `ref: H-01`); HAND §6.3; STRAT §9.2 and §9.6; EXP-2026-003 | Yes; schema check confirms the value and label |
| H-02 | Balanced Major cap 15% per asset | RPS Doc 3 `concentration.major_per_asset_cap_pct`; DATA §4.3 | Yes |
| H-03 | Balanced Speculative cap 5% per asset | RPS Doc 3 `concentration.speculative_per_asset_cap_pct`; DATA §4.3 | Yes |
| H-04 | Balanced total Speculative cap 10% | RPS Doc 3 `concentration.speculative_total_cap_pct`; ARCH §6.7 (RR-16) | Yes |
| H-05 | BTC and ETH as initial slice assets | TPS Doc 2 `instruments_in_scope`; ARCH §2.1; PRD §3.3 | Yes |

The automated schema check confirms that the shipped Balanced profile contains exactly these four numeric values, all labelled `hypothesis`, and that no other risk profile contains a numeric value. Every report must list hypothesis values in its provenance banner (FR-EVAL-05, T-48).

## 6. Unresolved decisions (UD-01 to UD-21)

All 21 items in PRD §10 contain the four parts the kickoff requires: why it matters, options, a labelled recommendation, and where it must be resolved (verified automatically). No unresolved value has been filled in anywhere: every field listed below is `TBD` with `status: unresolved`.

| ID | Kickoff item? | Where the value stays open | Must be resolved before |
|---|---|---|---|
| UD-01 | Yes | RPS `limits.portfolio_drawdown_circuit_breaker_pct` (all three profiles) | Paper activation (P5) |
| UD-02 | Yes | RPS `limits.daily_loss_limit_pct` | Paper activation (P5) |
| UD-03 | Yes | RPS `sizing.risk_per_trade_pct` | Paper activation (P5) |
| UD-04 | Yes | RPS `allocation.minimum_reserve_pct_range` | Paper activation (P5) |
| UD-05 | Yes | Adapter allowlist contains only the internal simulator (HAND §7.9); no external adapter chosen | Forward paper trading (BL-027) |
| UD-06 | Yes | Eligibility `tier_assignment.major` and `.speculative`; registry lists Core assets only | Any non-Core asset in a paper session |
| UD-07 | Yes | Ensemble `weighting_method`: M1 pass-through, V1 recommendation R-01 (STRAT §7) | Ensemble in a champion bundle (P7) |
| UD-08 | Yes | Promotion gates G-03 to G-10 have no numeric thresholds (STRAT §12) | First promotion (P10) |
| UD-09 | Yes | Hosted deployment view is provider-neutral (ARCH §10.2) | Hosted deployment (P10) |
| UD-10 | Yes | Alerts go to console and log only in V1 (ARCH §9.4) | Hosted deployment (P10) |
| UD-11 | Yes | Retention table is a recommendation; V1 deletes nothing (DATA §10) | Hosted deployment (P10) |
| UD-12 | No (formalization) | RPS `allocation.total_exposure_cap_pct`, `allocation.max_open_positions` | Paper activation (P5) |
| UD-13 | No (formalization) | RPS Conservative and Aggressive `concentration.*` (4 fields each) | Selecting Conservative or Aggressive outside experiments |
| UD-14 | No (formalization) | RPS `allocation.intraday_allocation_cap_pct` and `intraday_sleeve_limits.*` (3 fields) | Enabling any intraday strategy |
| UD-15 | No (formalization) | RPS `loss_response.size_reduction_schedule`, `sizing.adaptation.upward_multiplier_max` | Paper activation; upward adaptation |
| UD-16 | No (formalization) | RPS `sizing.hard_stop_policy` | Paper activation (P5) |
| UD-17 | No (formalization) | RPS cooldown count and duration, error count, stale grace, stale escalation, clock skew, external reconciliation tolerance (7 fields) | Paper activation; forward paper |
| UD-18 | No (formalization) | Eligibility liquidity, history, and spread thresholds per tier plus `when_no_spread_data` (10 fields) | Paper activation (backtests may use experiment values) |
| UD-19 | No (formalization) | RPS `halt_and_liquidation.liquidation_policy_after_halt` (interim: hold unchanged) | Paper activation (P5) |
| UD-20 | No (formalization) | Cost scenarios are placeholders (EXP §6); the public-data provider requires an explicit venue (no default) | Real-data evaluation experiments (EXP-2026-002 onward) |
| UD-21 | No (formalization) | Success metrics SM-07 to SM-09 have no targets (PRD §8) | V1 MVP exit (M2) and UD-08 |

## 7. Kickoff deliverable checklist

### 7.1 `architecture.md` v0.2

| Required content | Location |
|---|---|
| Revised to version 0.2 | ARCH header and §18 |
| Purpose, scope, and non-goals | ARCH §1, §2.1, §2.2 |
| System context and component boundaries | ARCH §4.1, §4.2, §4.3, §4.4 |
| Data, control, and execution flows | ARCH §7.1 to §7.7 |
| Research versus active paper-trader separation | ARCH §8.5, §8.6 |
| Failure handling and operational controls | ARCH §9.2, §9.4, §9.5 |
| Local and hosted deployment views | ARCH §10.1, §10.2 |
| Explicit framework-neutral domain contracts | ARCH §17 |
| Architecture decision records | ARCH §14 (ADR-001 to ADR-018) |
| Change log | ARCH §18 |

### 7.2 `product-requirements.md`

| Required content | Location |
|---|---|
| Problem statement | PRD §1 |
| Target user and jobs to be done | PRD §2 |
| Functional requirements | PRD §5 |
| Nonfunctional requirements | PRD §6 |
| Safety boundaries | PRD §7 |
| Staged release scope | PRD §4 |
| Success metrics | PRD §8 |
| Assumptions and unresolved decisions | PRD §9, §3.5, §10 |
| Acceptance criteria for V1 | PRD §11 |

### 7.3 `trading-profile.schema.yaml`

| Required content | Location |
|---|---|
| Human-readable, versioned schema | YAML JSON Schema with `schema_version` and content `version` (TPS Doc 1) |
| Objective | `objective` |
| Paper capital | `capital.paper_capital_usd`, `capital.funds` |
| Risk-profile selection | `risk_selection` (including the Aggressive acknowledgement) |
| Allowed universe and manual allowlist | `universe.allowed_tiers`, `core_assets`, `instruments_in_scope`, `manual_allowlist` |
| Disallowed assets | `universe.disallowed_assets` |
| Holding periods and timeframes | `horizon` |
| Autonomy mode | `execution.autonomy_mode` |
| Explanation preference | `explanations.preference` |
| Active data sources | `data_sources.active` |
| Status (draft, validated, active, suspended) | `status`, `x-lifecycle` |
| No silently assigned unresolved financial-risk values | Header rule; the profile holds no financial-risk values (they are in RPS) |

### 7.4 `risk-profile.schema.yaml`

| Required content | Field (all three profiles, RPS Docs 2 to 4) |
|---|---|
| Conservative, Balanced, and Aggressive profiles | Docs 2, 3, 4 |
| Portfolio drawdown circuit breaker | `limits.portfolio_drawdown_circuit_breaker_pct` (UD-01) |
| Daily loss limit | `limits.daily_loss_limit_pct` (UD-02) |
| Risk per trade | `sizing.risk_per_trade_pct` (UD-03) |
| Tier-specific position caps | `concentration.*_per_asset_cap_pct` (H-01 to H-03; UD-13) |
| Total exposure cap | `allocation.total_exposure_cap_pct` (UD-12) |
| Minimum reserve range | `allocation.minimum_reserve_pct_range` (UD-04) |
| Maximum open positions | `allocation.max_open_positions` (UD-12) |
| Intraday allocation cap | `allocation.intraday_allocation_cap_pct` (UD-14; candidates from D-20) |
| Speculative allocation cap | `concentration.speculative_total_cap_pct` (H-04; UD-13) |
| Cooldown behavior | `cooldown.after_consecutive_losing_trades` (UD-17) |
| Stale-data and exchange-error handling | `data_and_execution_faults` (UD-17) |
| Kill-switch state | `kill_switch.state_model` (runtime state in the operational store) |
| `TBD` for undecided values except recorded hypotheses | Verified automatically (§12) |

### 7.5 `strategy-spec.md`

| Required content | Location |
|---|---|
| Regime taxonomy | STRAT §3 |
| Initial baseline strategies | STRAT §4 |
| Signal contract | STRAT §5 |
| Ensemble contract | STRAT §6 |
| Conflict and no-trade behavior | STRAT §7 |
| Requirements for minute-level strategies | STRAT §8 |
| Deterministic position-sizing boundary | STRAT §9 |
| Model/strategy versioning | STRAT §10 |
| Champion/challenger lifecycle | STRAT §11 |
| Strategy promotion gates | STRAT §12 |
| Signal-conflict recommendation labelled as a recommendation, not an approved decision | STRAT §7 (banner; R-01) |

### 7.6 `data-architecture.md`

| Required content | Location |
|---|---|
| Source/provider interfaces | DATA §3 |
| V1 through Experimental source roadmap | DATA §2 |
| Canonical asset and market identifiers | DATA §4 |
| UTC timestamp policy | DATA §5 |
| Data-quality checks | DATA §6 |
| Immutable backtest datasets | DATA §7 |
| Feature lineage | DATA §8 |
| Look-ahead and leakage prevention | DATA §9 |
| Retention considerations | DATA §10 |
| Degraded behavior when a provider is unavailable | DATA §11 |

### 7.7 `experiment-plan.md`

| Required content | Location |
|---|---|
| Simple baselines | EXP §2 |
| Time-ordered train/validation/test design | EXP §3 |
| Walk-forward evaluation | EXP §4 |
| Look-ahead-bias checks | EXP §5 |
| Fees, spread, slippage, and latency assumptions | EXP §6 |
| Intraday allocation experiment matrix | EXP §7 |
| Regime-level evaluation | EXP §8 |
| Benchmark comparisons | EXP §9 |
| Robustness and sensitivity checks | EXP §10 |
| Experiment record template | EXP §13 |
| Explicit rejection criteria for overfit strategies | EXP §14 |

### 7.8 `execution-plan.md`

| Required phase (with dependencies, outputs, tests, exit criteria) | Location |
|---|---|
| Foundation | EXEC §4.1 (P0) |
| Schemas/profile compiler | EXEC §4.2 (P1) |
| Data pipeline | EXEC §4.3 (P2) |
| Baseline backtesting | EXEC §4.4 (P3) |
| Deterministic risk engine | EXEC §4.5 (P4) |
| Paper execution | EXEC §4.6 (P5) |
| Journal and evaluation | EXEC §4.7 (P6) |
| Ensemble/regime layer | EXEC §4.8 (P7) |
| Optional ML challenger | EXEC §4.9 (P8) |
| Dashboard/conversation | EXEC §4.10 (P9) |
| Hosted paper deployment | EXEC §4.11 (P10) |
| Clearly prioritized V1 backlog | EXEC §5 (BL-001 to BL-047, four priority levels) |
| Dependencies summary | EXEC §3 |

### 7.9 `code-session-handoff.md`

| Required content | Location |
|---|---|
| Desired repository structure | HAND §3 |
| Recommended Python stack | HAND §4 |
| First vertical slice to implement | HAND §1.1, §5 |
| Files and interfaces to create | HAND §3, §6, §7 |
| Test cases | HAND §9 |
| Commands that should work at completion | HAND §10 |
| Definition of done | HAND §11 |
| Explicit instruction not to add real-money trading, leverage, or withdrawal functionality | HAND §0.1 rule 1, §13 |
| Instruction to stop and document blockers rather than bypassing missing risk requirements | HAND §0.1 rule 4, §12 |
| Self-contained (no access to the original conversation needed) | HAND §0 to §14 include context, configuration contents, contracts, algorithms, tests, commands |

## 8. Required framework-neutral contracts

All thirteen are defined in ARCH §17.2 with owner, inputs, outputs, validation rules, and versioning, and at field level in HAND §7.3. `TradingProfile` and `RiskProfile` also have full JSON Schemas (TPS, RPS). Framework neutrality is enforced by ARCH §4.4 and test T-47.

| Contract | ARCH §17.2 row | Field definition | Schema or rules |
|---|---|---|---|
| `TradingProfile` | 1 | HAND §6.2, §7.3 | TPS; PV-01 to PV-10 |
| `RiskProfile` | 2 | HAND §6.3, §7.3 | RPS; RP-01 to RP-12 |
| `MarketSnapshot` | 3 | HAND §7.3 | DATA §5 freshness rule |
| `FeatureSet` | 4 | HAND §7.3 | DATA §8, §9 |
| `RegimeAssessment` | 5 | HAND §7.3 | STRAT §3 |
| `SignalCandidate` | 6 | HAND §7.3 | STRAT §5 (S-01 to S-08) |
| `EnsembleDecision` | 7 | HAND §7.3 | STRAT §6, §7 |
| `RiskDecision` | 8 | HAND §7.3 | ARCH §6.7 (RR-01 to RR-20) |
| `OrderIntent` | 9 | HAND §7.3 | ARCH §6.9 (EG-01 to EG-05), §7.7 |
| `ExecutionReport` | 10 | HAND §7.3 | HAND §7.9 |
| `PositionSnapshot` | 11 | HAND §7.3 | HAND §7.10 |
| `TradeEvent` | 12 | HAND §7.3 | HAND §7.11 |
| `ExperimentRecord` | 13 | HAND §7.3 | EXP §13 |

## 9. V1 vertical slice and required rejection tests

| Slice step (D-46) | Backlog | Acceptance | Tests |
|---|---|---|---|
| Validated Balanced paper profile | BL-005, BL-006 | AC-01 | T-01, T-10 |
| Load BTC and ETH historical candles | BL-007, BL-008 | AC-05 | T-17, T-42 |
| Validate data quality | BL-008 | AC-05 | T-11 to T-16 |
| Run buy-and-hold benchmark | BL-011 | AC-06 | T-21 |
| Run one trend/momentum baseline | BL-012 | AC-07 | T-19 |
| Generate `SignalCandidate` events | BL-012, BL-016 | AC-07, AC-14 | T-19, T-39 |
| Apply deterministic `RiskProfile` checks | BL-013 | AC-08 to AC-13 | T-22 to T-34 |
| Simulate orders using paper/dry-run execution | BL-014, BL-015 | AC-15, AC-17 | T-35, T-36 |
| Persist `TradeEvent` journal | BL-016 | AC-14 | T-37 to T-41 |
| Report returns, fees, drawdown, and benchmark comparison | BL-018 | AC-15 | T-42, T-48 |

| D-47 rejection category | Acceptance | Tests |
|---|---|---|
| Invalid profiles | AC-02 | T-02, T-03, T-04, T-05 (and T-06 contradictions) |
| Unsupported assets | AC-08 | T-22 |
| Stale data | AC-09 | T-23 |
| Excessive sizing | AC-10 | T-24, T-25 |
| Duplicate orders | AC-11 | T-26, T-41 |
| Breached loss limits | AC-12 | T-27, T-28 (and T-29, T-33) |
| Disabled execution states | AC-13 | T-30, T-31, T-32 (and T-36) |

## 10. Recommended technical direction (kickoff list)

| ID | Kickoff recommendation | Verdict | Location |
|---|---|---|---|
| RT-01 | Python 3.11+ | Adopt | PRD §3.4; ARCH §5.1; HAND §4 |
| RT-02 | Freqtrade for backtesting/dry-run | Evaluate in a spike, not an M1 dependency (R-03) | ARCH §5.2, §5.3, ADR-003; EXEC BL-032 |
| RT-03 | FreqAI only after non-ML baselines | Adopt as sequencing rule | ARCH ADR-004; EXEC §4.9 |
| RT-04 | CCXT or framework adapters behind a neutral interface | Adopt; CCXT for public data until UD-05 | ARCH §5.1, §6.9; DATA §3.3 |
| RT-05 | Pydantic | Adopt (v2) | ARCH §17.1; HAND §7.1 |
| RT-06 | Typer | Adopt | HAND §4, §7.14 |
| RT-07 | FastAPI later | Adopt later (P9, P10) | EXEC §4.10 |
| RT-08 | SQLite plus Parquet, later PostgreSQL and object storage | Adopt | DATA §7; ARCH §10.2 |
| RT-09 | pytest | Adopt (plus hypothesis) | HAND §4, §9 |
| RT-10 | Structured JSON logs and correlation IDs | Adopt in M1 | HAND §7.15 |
| RT-11 | Docker after the first local slice | Adopt after M1 | EXEC BL-033 |
| — | "Do not let the framework leak into every domain model" | Enforced | ARCH §4.4, §17.1; T-47 (D-44) |

## 11. Quality bar

| Kickoff quality-bar item | Evidence |
|---|---|
| Keep the package internally consistent | Automated checks in §12 all pass |
| Separate approved decisions, recommendations, hypotheses, and unresolved items | Labels and registers (PRD §3); every document carries the label legend; schema values carry `status` |
| Do not rewrite approved decisions into materially different requirements | Verbatim registers (PRD §3.2); objective stored as a schema constant; interpretations listed in §13 for confirmation |
| Prefer executable acceptance criteria | AC-01 to AC-25 each cite tests; HAND §9 gives setup, action, and expected result; HAND §10 lists commands with expected exit codes |
| Ensure Code can implement the first slice without the chat | HAND is self-contained (configuration contents, contracts, algorithms, tests, commands) |
| Keep real-money execution outside the MVP | SAFE-01 to SAFE-04; schema constants; adapter allowlist; HAND §0.1 and §13; T-46 |
| Include a document index and dependency map | `README.md` §2, §3 |
| Finish with an audit that lists omissions | This document (§14) |

## 12. Automated consistency checks

| Check | Result |
|---|---|
| TradingProfile instance validates against its schema; 14 invalid variants rejected (real funds, leverage, withdrawals, live environment, Aggressive without acknowledgement, missing HFT exclusion, 15m timeframe, rewritten objective, unknown field, missing status, experimental source required for trading, mislabelled tier, Blocked tier) | Pass |
| Conservative, Balanced, Aggressive validate; 12 invalid variants rejected (number marked unresolved, `TBD` marked approved, approval without approver, hypothesis with a UD ref, leverage, AI override, automated kill-switch disengage, missing auto-engage triggers, upward adaptation without approved bound, ATR stop without parameters, half-`TBD` reserve range, cap above 100%) | Pass |
| Shipped risk profiles contain no approved or invented values; Balanced holds exactly H-01 to H-04 | Pass |
| All 118 cross-document section references resolve to existing headings; same-document references checked | Pass |
| All identifiers fall inside their defined ranges (D, H, R, RT, UD, AC, T, BL, RR, EG, DQ, LA, OF, RB, G, PV, RP, FM, ADR, PR, SM, A, SAFE, NFR, C, S, E, M, I, P, JTBD) | Pass |
| Every D, H, and UD identifier appears in at least two documents | Pass |
| Every UD item has why, options, recommendation, resolve-before; UD-01 to UD-11 match the kickoff list in order | Pass |
| Test catalogue T-01 to T-66 and backlog BL-001 to BL-047 complete; M1 tests T-01 to T-48 present in the handoff | Pass |
| Handoff configuration blocks are identical to the schema-file instances; EXP-2026-001 identical in experiment plan and handoff; registry and eligibility blocks identical in data architecture and handoff | Pass |
| Reason codes and event types identical in architecture and handoff | Pass |
| No guaranteed-profit language outside prohibitions | Pass |

Limitation: the JSON Schemas were checked offline with a validator that implements the subset of draft 2020-12 keywords the schemas use. The handoff makes Code re-validate the shipped configuration with the `jsonschema` library (T-02, T-03).

## 13. Interpretations requiring owner confirmation

None of these changes an approved decision. Each is labelled in the package as a recommendation or an assumption.

| ID | Interpretation | Related | Where |
|---|---|---|---|
| IN-01 | "Minimum reserve range" is read as `[floor, defensive ceiling]` | A-10, UD-04 | PRD §9; RPS |
| IN-02 | On candle-only V1 data, the spread eligibility criterion is `not_applicable` with conservative slippage, becoming mandatory with V1.5 order-book data. D-26 lists spread among the Blocked criteria | R-21, UD-18 | DATA §4.5 |
| IN-03 | V1 adaptation is defensive-only; upward adaptation (permitted by D-10) waits for an approved bound | R-22, UD-15 | STRAT §9.4 |
| IN-04 | Experiment parameter sets may fill unresolved values in research backtests only; this is how the slice runs without inventing profile values | R-02, ADR-016 | EXP §11 |
| IN-05 | Hypothesis values H-01 to H-04 may be used in paper sessions as labelled values, as well as in backtests | D-28, RP-09 | PRD §3.3 |
| IN-06 | The kill switch blocks all new orders; open positions and attached protective stops stay unchanged until UD-19; a filled entry's protective stop is exempt from the kill-switch gate | R-15, UD-19 | ARCH §6.9, §9.2 |
| IN-07 | The drawdown circuit breaker is latched and reset only by an owner command, which rebases the high-water mark | R-18 | ARCH §9.2 |
| IN-08 | Benchmarks are computed analytically, outside the risk engine | R-20 | STRAT §4.1 |
| IN-09 | "Paper", "dry-run", and "simulated" are treated as equivalent no-real-funds modes | A-04 | PRD §9 |
| IN-10 | V1.5 derivatives data is a read-only input; derivatives trading stays excluded | D-37, SAFE-02 | DATA §2 |
| IN-11 | BTC and ETH are the slice scope and labelled hypothesis H-05 (following the decisions summary), not a permanent universe | H-05 | PRD §3.3 |
| IN-12 | Spot long-only: short selling is excluded. The kickoff does not mention shorting explicitly; this follows from D-03 and v0.1 "spot only" | A-03 | PRD §9; schemas |
| IN-13 | Minute-level refinement and the intraday sleeve are staged for V1.5 | R-23 | PRD §4 |
| IN-14 | The guided questionnaire (a v0.1 definition-of-done item) moves to a V1 should-have; M1 starts from an authored, validated profile per D-40 and D-46 | BL-031 | ARCH §16 |
| IN-15 | Freqtrade is evaluated in a spike rather than used in M1, consistent with the kickoff's "recommendations to validate" | RT-02, R-03 | ARCH ADR-003 |
| IN-16 | Experimental data sources cannot be marked required for trading until a strategy using them is promoted | D-37, D-43 | TPS `DataSourceRef` |
| IN-17 | The intraday matrix adds a 0% control. The approved candidates remain exactly 5%, 10%, 15%, and 20% | D-20 | EXP §7 |
| IN-18 | The daily loss window is the UTC calendar day, with day-start equity marked at 00:00 UTC | UD-02 | DATA §5 |

## 14. Omissions, deviations, and limitations

**Omissions:** none. Every kickoff decision, hypothesis, unresolved item, deliverable bullet, contract, slice step, rejection category, technical recommendation, and quality-bar item maps to at least one location in the package.

**Deviations from v0.1 (all recorded in ARCH §18):** the $10,000 example profile is superseded by the approved $2,500 Balanced profile; v0.1 implementation sequence, backlog, experiment template, and definition of done moved to other package documents, with mapping tables (ARCH §11, §12, §15, §16); the "16-question interview" is replaced by a schema-driven questionnaire (ARCH §13 note).

**Limitations:**

- Most numeric risk values are intentionally unresolved. The recommended options in PRD §10 are reasoned starting points that have not been tested on data; EXP-2026-003 is designed to supply that evidence.
- Cost scenarios are placeholders until the venue and fee tier are chosen (UD-20).
- The M1 demonstration runs on deterministic synthetic data, which verifies the pipeline but says nothing about strategy quality.
- Schema validation in this audit used an offline subset validator; Code re-validates with `jsonschema`.

## 15. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue of the audit for package version 0.2. |
