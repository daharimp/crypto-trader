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

## 2026-11-01: Apply owner decisions UD-01..UD-21 (all recommendations accepted)

- [x] Approve values in `configs/risk/{conservative,balanced,aggressive}.yaml` (v2), `configs/universe/eligibility.yaml` (v2), `configs/profiles/balanced-paper.yaml` (v2)
- [x] Record decisions in `docs/spec/product-requirements.md` §10.2 and ADR-022
- [x] Freeze the all-TBD M1 configs as test fixtures (`tests/fixtures/configs/`, `TRADER_CONFIGS_DIR`)
- [x] Tests for the approved state (`test_owner_decisions.py`, `test_shipped_configs.py`); demo updated
- [x] UD-20: Kraken (2026-11-01)
- [x] BL-048: owner flatten command through the execution gate (UD-19 option D)

## 2026-11-01: Live trading on Kraken (owner goal: live by Monday 2026-11-02)

- [x] UD-14 resolved (no intraday in V1); UD-20 Kraken; UD-09 cloud server; ADR-023 boundary
- [x] BL-028 profile activation (`trader profile activate`, activation records)
- [x] Live authorization file with UD-22 cap and paper prerequisite (fail closed)
- [x] BL-027 forward session runner (paper and live), persisted state, restart recovery
- [x] Kraken public data (4h signals, 1d eligibility) and Kraken live adapter (ccxt)
- [x] BL-048 owner flatten; breaker reset requests; webhook alerts; preflight
- [x] Dockerfile, docker-compose.yml, `.env.example`, `docs/operations/RUNBOOK.md`
- [ ] Owner: set UD-22 and the acknowledgement; create API key; run preflight on the server
- [ ] Owner: allow `api.kraken.com` here so real-data checks and backtests can run

## 2026-11-02: Jupiter Perps, paper only (ADR-024)

- [x] `trader.perps`: math, fail-closed config (UD-23), risk checks and sizing, paper simulator, replay, read-only Jupiter prices
- [x] CLI `trader perps validate|prices|backtest`; T-46 amended; paper-only safety test
- [ ] Owner: approve UD-23 values in `configs/perps/jupiter.yaml` (check venue values against Jupiter docs)
- [ ] Allow `jup.ag` in the cloud environment's network settings, then verify `trader perps prices`
- [ ] Download SOL/ETH/BTC candles and run the perps backtest on real data
- [ ] Forward paper perps session (reuse the BL-027 scheduler) once the backtest is reviewed

## Discovered During Work

- [ ] Re-evaluate journal `synchronous=FULL` for live sessions (ADR-019).
- [ ] Real-data evaluation: Kraken OHLC gives only 720 candles; long 4h backtests need Kraken's downloadable history (CSV import).
- [ ] Verify Kraken's current fee tier for the account and update `costs/base.yaml` if different.
- [ ] DQ-12 cross-timeframe consistency is optional in M1 and not implemented (needs 1h + 4h datasets).
- [x] Owner decisions UD-01..UD-21 resolved 2026-11-01 except UD-14 (deferred) and UD-20 (venue).
- [ ] Next milestone M2: BL-021..BL-030 (`docs/spec/execution-plan.md` §5).
