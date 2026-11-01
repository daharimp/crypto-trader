# AI-Assisted Crypto Paper-Trading System: Specification Package

**Package version:** 0.2
**Date:** 2026-10-08
**Owner:** Dahari Morgan-Parker
**Controlling specification:** `cowork-kickoff.md`. Approved decisions: `decisions-summary.md`. Baseline: `architecture.md` v0.1.

> **Safety boundary.** The first implementation uses paper, dry-run, or simulated funds only. It contains no real-money execution, leverage, margin, short selling, withdrawals, transfers, or unrestricted trade placement. Deterministic risk controls have final authority. Promotion of strategies or models is never automatic.

This package formalizes the architecture and approved decisions into implementation-ready documents for a later Microsoft Copilot Code session. Start with `code-session-handoff.md` to implement; start with `product-requirements.md` §3 and §10 to review decisions.

## 1. Status labels

| Label | Meaning | ID format | Register |
|---|---|---|---|
| APPROVED | Owner-approved decision, quoted verbatim | `D-01` to `D-47` | `product-requirements.md` §3.2 |
| HYPOTHESIS | Recorded starting hypothesis; testable, not a permanent limit | `H-01` to `H-05` | `product-requirements.md` §3.3 |
| RECOMMENDATION | Proposed while formalizing; not approved until the owner accepts | `R-01` to `R-24`, `RT-01` to `RT-11` | `product-requirements.md` §3.4 |
| UNRESOLVED | Open decision; value `TBD`; code fails closed | `UD-01` to `UD-21` | `product-requirements.md` §3.5 and §10 |

## 2. Document index

| # | File | Kickoff deliverable | What it contains |
|---|---|---|---|
| 1 | `architecture.md` (v0.2) | 1 | Purpose, scope, non-goals; system context and component boundaries; authority matrix; data, control, and execution flows; research versus active paper trader; failure handling and operational controls; local and hosted deployment views; framework-neutral domain contracts; ADR-001 to ADR-018; change log |
| 2 | `product-requirements.md` | 2 | Problem; users and jobs to be done; **decision registers**; staged release scope; functional and nonfunctional requirements; safety boundaries; success metrics; assumptions; **unresolved-decision analysis (UD-01 to UD-21)**; V1 acceptance criteria |
| 3 | `trading-profile.schema.yaml` | 3 | JSON Schema for `TradingProfile` plus the initial Balanced paper profile; policy rules PV-01 to PV-10; lifecycle |
| 4 | `risk-profile.schema.yaml` | 4 | JSON Schema for `RiskProfile` plus Conservative, Balanced, Aggressive (values `TBD` except hypotheses H-01 to H-04); required-field sets; policy rules RP-01 to RP-12 |
| 5 | `strategy-spec.md` | 5 | Regime taxonomy; baseline strategies; signal and ensemble contracts; **signal-conflict recommendation (R-01)**; minute-level rules; sizing boundary; versioning; champion/challenger lifecycle; promotion gates |
| 6 | `data-architecture.md` | 6 | Provider interfaces; V1 to Experimental roadmap; identifiers; UTC policy; data-quality checks; immutable datasets; feature lineage; leakage prevention; retention; degraded behavior |
| 7 | `experiment-plan.md` | 7 | Baselines; time-ordered splits; walk-forward; look-ahead checks; cost assumptions; intraday allocation matrix; regime evaluation; benchmarks and metrics; robustness; experiment parameter sets; record template; overfit rejection criteria |
| 8 | `execution-plan.md` | 8 | Phases P0 to P10 with dependencies, outputs, tests, exit criteria; **prioritized V1 backlog**; **test catalogue T-01 to T-66**; decision gates |
| 9 | `code-session-handoff.md` | 9 | Self-contained implementation prompt and specification for the first vertical slice (M1) |
| — | `README.md` | Quality bar | This index and the dependency map |
| — | `traceability-audit.md` | Quality bar | Final audit of every kickoff decision against the package, with omissions and interpretations |

## 3. Dependency map

```text
                cowork-kickoff.md + decisions-summary.md + architecture.md v0.1
                                         │
                                         ▼
                           product-requirements.md
              (decision registers, requirements, UD analysis, acceptance criteria)
                                         │
                                         ▼
                               architecture.md v0.2
                 (boundaries, flows, rule catalogue, contracts, ADRs)
                    │                    │                     │
                    ▼                    ▼                     ▼
     trading-profile.schema.yaml   data-architecture.md   strategy-spec.md
     risk-profile.schema.yaml             │                     │
                    │                     └──────────┬──────────┘
                    │                                ▼
                    │                       experiment-plan.md
                    │                                │
                    └───────────────┬────────────────┘
                                    ▼
                            execution-plan.md
                     (phases, backlog, test catalogue)
                                    │
                                    ▼
                         code-session-handoff.md
                                    │
                                    ▼
                         traceability-audit.md (checks everything above)
```

| Document | Depends on | Used by |
|---|---|---|
| `product-requirements.md` | Kickoff, decisions summary, architecture v0.1 | All documents |
| `architecture.md` | `product-requirements.md` | All later documents |
| `trading-profile.schema.yaml` | `product-requirements.md`, `architecture.md` §17 | `execution-plan.md`, `code-session-handoff.md` |
| `risk-profile.schema.yaml` | `product-requirements.md` §10, `architecture.md` §6.7 | `strategy-spec.md` §9, `experiment-plan.md` §11, `code-session-handoff.md` |
| `data-architecture.md` | `product-requirements.md`, `architecture.md` | `strategy-spec.md`, `experiment-plan.md`, `code-session-handoff.md` |
| `strategy-spec.md` | `architecture.md`, `risk-profile.schema.yaml`, `data-architecture.md` | `experiment-plan.md`, `execution-plan.md`, `code-session-handoff.md` |
| `experiment-plan.md` | `strategy-spec.md`, `data-architecture.md`, `risk-profile.schema.yaml` | `execution-plan.md`, `code-session-handoff.md` |
| `execution-plan.md` | All of the above | `code-session-handoff.md` |
| `code-session-handoff.md` | All of the above (self-contained for M1) | Microsoft Copilot Code |
| `traceability-audit.md` | All documents | Owner review |

## 4. Where to find things

| Topic | Location |
|---|---|
| Approved decisions (verbatim) | `product-requirements.md` §3.2 |
| Unresolved decisions with options and recommendations | `product-requirements.md` §10 |
| What must be decided before paper activation | `execution-plan.md` §7 |
| V1 acceptance criteria | `product-requirements.md` §11 |
| Prioritized V1 backlog | `execution-plan.md` §5 |
| Test requirements | `execution-plan.md` §6; detailed M1 tests in `code-session-handoff.md` §9 |
| Risk rule catalogue and execution gate | `architecture.md` §6.7, §6.9 |
| Domain contracts | `architecture.md` §17; field-level in `code-session-handoff.md` §7.3 |
| Signal-conflict recommendation | `strategy-spec.md` §7 |
| Intraday allocation experiment | `experiment-plan.md` §7 |
| Decision audit | `traceability-audit.md` |

## 5. Identifier scheme

| Prefix | Meaning | Defined in |
|---|---|---|
| `D`, `H`, `R`, `RT`, `UD` | Decisions, hypotheses, recommendations, unresolved decisions | `product-requirements.md` §3 |
| `P` | Architecture principles | `architecture.md` §3 |
| `FR`, `NFR`, `SAFE`, `SM`, `A`, `AC`, `JTBD` | Requirements, safety boundaries, success metrics, assumptions, acceptance criteria, jobs to be done | `product-requirements.md` |
| `RR`, `EG`, `FM`, `ADR` | Risk rules, execution gate checks, failure modes, decision records | `architecture.md` |
| `PV`, `RP` | Profile and risk-profile policy rules | Schema files |
| `S`, `E`, `C`, `M`, `I`, `E-I`, `G` | Signal, ensemble, conflict, minute-refinement, intraday, intraday-evaluation rules; promotion gates | `strategy-spec.md` |
| `DQ` | Data-quality checks | `data-architecture.md` §6 |
| `LA`, `RB`, `OF`, `EXP` | Look-ahead checks, robustness checks, overfit criteria, experiments | `experiment-plan.md` |
| `P0` to `P10`, `M1` to `M4`, `BL`, `T`, `PR` | Phases, milestones, backlog, tests, project risks | `execution-plan.md` |

## 6. Owner's next decisions

To move from the M1 vertical slice (which needs no further decisions) to local paper trading, the owner needs to resolve UD-01, UD-02, UD-03, UD-04, UD-12, UD-15, UD-16, UD-17, UD-18, and UD-19, plus UD-05 and UD-20 for forward paper sessions. EXP-2026-003 is designed to provide evidence for most of them. Options and recommendations for each are in `product-requirements.md` §10.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 2026-10-08 | First issue of the package, aligned with `architecture.md` v0.2. |
