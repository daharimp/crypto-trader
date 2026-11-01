# TASK

## 2026-11-01: Implement M1 vertical slice from the spec package

- [x] BL-001 Scaffold, uv, ruff/mypy/pytest, `.gitignore`, `.env.example`, `BLOCKERS.md`, `docs/spec/`, ADR stubs
- [x] BL-002 Common utilities (clock, IDs, canonical JSON, hashing, Decimal, JSON logging, revision)
- [x] BL-003 Domain contracts (T-47)
- [x] BL-004 Schema files, loaders, JSON-schema validation of shipped configs (T-02, T-03)
- [x] BL-005 Profile compiler, `trader profile validate|compile` (T-01, T-04..T-10)
- [x] BL-006 Shipped configs and EXP-2026-001
- [x] BL-007 CSV, synthetic, optional CCXT providers
- [x] BL-008 DQ-01..DQ-12, manifests, immutable store (T-11..T-18)
- [x] BL-009 Registry, eligibility, `UniverseSnapshot` (T-22)
- [x] BL-010 features-m1 (T-20)
- [x] BL-011 Benchmarks (T-21)
- [x] BL-012 `sma_trend`, null regime, pass-through ensemble (T-19)
- [x] BL-013 Risk engine RR-01..RR-20 (T-22..T-34)
- [x] BL-014 Execution gate, allowlist, simulator (T-24, T-26, T-35)
- [x] BL-015 Ledger, reconciliation (T-36)
- [x] BL-016 Journal, verify, journal-before-act (T-37..T-41)
- [x] BL-017 Runner and decision cycle, `trader backtest run` (T-42..T-44)
- [x] BL-018 Reports, `trader report show`, experiment records (T-48)
- [x] BL-019 Persisted kill switch and CLI (T-30, T-45)
- [x] BL-020 Safety/neutrality tests, README, demo script, DoD check (T-46, T-47)

## Discovered During Work

- [ ] Re-evaluate journal `synchronous=FULL` for the paper environment before BL-027 (ADR-019).
- [ ] DQ-12 cross-timeframe consistency is optional in M1 and not implemented (needs 1h + 4h datasets).
- [ ] Owner decisions UD-01..UD-21 (`BLOCKERS.md`, `docs/spec/product-requirements.md` §10).
- [ ] Next milestone M2: BL-021..BL-030 (`docs/spec/execution-plan.md` §5).
