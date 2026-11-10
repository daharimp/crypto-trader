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
- [x] UD-22 set by owner 2026-11-02: $250 cap, 42 paper cycles
- [x] Universe: SOL, XRP (Major) and SUI (Speculative) added (UD-06 option B, 2026-11-02)
- [x] Real Kraken public data verified; real paper cycles run here for all five coins
- [ ] Owner: write the live acknowledgement; create API key; run preflight on the server

## 2026-11-02: GitHub repository setup

- [x] README rewrite (overview, how it works, safety controls, commands, configuration, status)
- [x] LICENSE (proprietary, all rights reserved), CONTRIBUTING, SECURITY, CODE_OF_CONDUCT,
      SUPPORT, CHANGELOG, `.editorconfig`
- [x] `.github/`: CI workflow, Dependabot (uv + actions), CODEOWNERS, PR and issue templates
- [x] Runbook: deploy key for the private repository; updating the code
- [ ] Owner: make the repository private; set the repo description and topics on GitHub;
      enable private vulnerability reporting and branch protection for `main`

## 2026-11-02: EXP-2026-002 real-data test (owner approved option 1 only)

- [x] Daily eligibility datasets in backtests; universe benchmark; proxy-aware data fetch
- [x] Fetched 120 days of real 4h Kraken data (5 coins) and ran the cost x capital grid
- [x] Report: `docs/experiments/EXP-2026-002-kraken-120d.md`. Verdict: no edge shown
- [ ] (Not approved yet) server deployment walkthrough; comparison strategies (BL-022);
      merge PR #1; full Kraken history and walk-forward (BL-025/BL-029); maker orders

## 2026-11-03: Owner approved all four next steps

- [x] Comparison strategies (BL-022) with a random-entry control
- [x] Lower costs: post-only limit orders in the simulator; fee tier in preflight
- [x] Full-history tooling: `trader data import-kraken`, `trader research compare`
- [x] EXP-2026-003 on the 120 days available: `docs/experiments/EXP-2026-003-*`
- [ ] Owner: upload Kraken OHLCVT files (XBT/ETH/SOL/XRP/SUI USD, 240 and 1440) for the
      full-history rerun
- [ ] Owner: set up the server and start paper (RUNBOOK steps 1-2)
- [ ] Live limit orders (post-only on Kraken, fill polling, prompt stops), if approved

## 2026-11-02: Jupiter Perps, paper only (ADR-025)

- [x] `trader.perps`: math, fail-closed config (UD-23), risk checks and sizing, paper simulator, replay, read-only Jupiter prices
- [x] CLI `trader perps validate|prices|backtest`; T-46 amended; paper-only safety test
- [x] Owner approved UD-23 risk limits 2026-11-02 (v2): 25x max, 10x target, 20%/position, 400% total, 8% liquidation buffer, 3 positions, 15% daily loss, $2,500 paper
- [ ] Venue values (fees, borrow rate, maintenance, venue max leverage): verify against Jupiter docs once `jup.ag` is reachable
- [ ] Allow `jup.ag` in the cloud environment's network settings, then verify `trader perps prices`
- [ ] Download SOL/ETH/BTC candles and run the perps backtest on real data
- [ ] Forward paper perps session (reuse the BL-027 scheduler) once the backtest is reviewed

## 2026-11-10: Phone dashboard (ADR-026, BL-041/BL-042 first cut)

- [x] `trader ui serve`: read-only server, phone page, TradingView Lightweight Charts bundled
- [x] Live Kraken candles + SMA 20/50, live Jupiter price, paper perps markers and liquidation line, sessions and kill switch
- [x] Tests: data builders, routes, 405 on writes, 400/404/502 handling, read-only safety scan
- [x] Jupiter docs verified (docs.jup.ag): 0.06% base + >=0.01% price impact per side, liquidation at size/500, 250x max, all remaining collateral lost on liquidation
- [x] Owner approved venue values 2026-11-10 (v3): 7 bps open/close, liquidation at size/500, 250x venue max; borrow first 0.0016%/h, then changed to the cautious 0.01%/h (v4)
- [x] Checked: charging the opening fee on top of collateral leaves the same recorded collateral as Jupiter's deposit-minus-fee; no change needed

## 2026-11-10: Strategy research lab (ADR-027, EXP-2026-010)

- [x] `trader.research.lab`: no-look-ahead harness, costs and borrow, 3 walk-forward folds, sealed 180-day holdout; 8 tests
- [x] Sweep of 40 ideas x SOL/BTC/ETH x Jupiter perps and Kraken spot costs (`research/EXP-2026-010-results.txt`)
- [x] Holdout opened once for 2 pre-chosen ideas (`research/EXP-2026-010-holdout.txt`)
- [x] QuantConnect version of the squeeze breakout for owner confirmation (`research/lean/`, not run here)
- [ ] Owner: run `research/lean/squeeze_breakout_main.py` in QuantConnect's web IDE and share the result
- [ ] Register the squeeze breakout as a real strategy class with tests, then a spot paper run (BL-022)

## 2026-11-10: Research pass + EXP-2026-011 (10 hypotheses)

- [x] Literature pass: crypto momentum real but cost-sensitive; volatility sizing mainly cuts drawdowns; volume confirmation and funding signals weakly supported
- [x] 10 hypotheses vs the squeeze control on folds only (holdout already used): `research/EXP-2026-011-results.txt`
- [x] Owner set perps collateral to 10% of equity per position (UD-23, perps config v5)
- [ ] Forward paper run of the best candidate on the server (the only clean test left)

## 2026-11-10: Deploy on the owner's n8n VPS (plan approved)

- [x] `dashboard` compose service: localhost-only port, read-only mounts, project name `crypto-trader`
- [x] RUNBOOK: 1b server with n8n, 1c ntfy, 2b Tailscale dashboard; deploy branch `crypto-trader`
- [x] `tests/safety/test_deploy_config.py`
- [ ] Owner: run RUNBOOK S1-S6 on the VPS and share the outputs

## Discovered During Work

- [ ] 2026-11-10 real-data perps replay (Coinbase 4h, Sep 2024 to Nov 2026, SOL+BTC, sma_stance): at the approved 10x it ends at $259 from $2,500 (92.8% max drawdown, 14 liquidations); long-only $1,255. A leverage sweep shows about breakeven at 1.1x and larger losses at every higher level: the signal has no edge after costs, so leverage only magnifies losses. Perps need better strategies (BL-022 to BL-025) before any forward paper run.
- [ ] 2026-11-10 real-data spot backtest (balanced profile, sma_trend, BTC+ETH): +5.4% vs +27.2% buy-and-hold BTC; max drawdown 5.3% vs 53.6%; Sortino 1.01 vs 0.71; only 6 closed trades (fails sample-size gate G-09).

- [ ] Re-evaluate journal `synchronous=FULL` for live sessions (ADR-019).
- [ ] Real-data evaluation: Kraken OHLC gives only 720 candles; long 4h backtests need Kraken's downloadable history (CSV import).
- [ ] Verify Kraken's current fee tier for the account and update `costs/base.yaml` if different.
- [ ] DQ-12 cross-timeframe consistency is optional in M1 and not implemented (needs 1h + 4h datasets).
- [x] Owner decisions UD-01..UD-21 resolved 2026-11-01 except UD-14 (deferred) and UD-20 (venue).
- [ ] Next milestone M2: BL-021..BL-030 (`docs/spec/execution-plan.md` §5).

## 2026-11-03: Riskier swing + 1h quick trades (owner request)

- [x] Generalize `trader research compare` to 1h (`--timeframe`, `--reference`); EXP-2026-004 part 1 (1h screen, 30 days of API data).
- [x] Record owner decisions: Aggressive swing profile chosen; UD-14 revisit: 1h, 10% cap, sleeve limits 2.5% / 12.5% (`aggressive.yaml` v3).
- [ ] Owner: write the Aggressive acknowledgement (PV-03) so the profile can switch to Aggressive.
- [ ] Owner: pick the 1h sleeve strategy (EXP-2026-004 part 1 is inconclusive; full history needs `*_60.csv` uploads).
- [ ] Build the isolated 1h intraday sleeve (separate ledger, sleeve loss limits, 1h session cycle), paper first.
- [x] Profile builder (2026-11-03): `trader profile build` interview + `--answers`, `trader profile questions`, web form, named risk profiles, ADR-024.
