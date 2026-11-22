# 2026-11-22: Every bot trades long and short from one shared trend rule (owner request)

- [x] Audit each bot's direction logic (EXP-2026-020, PR #55)
- [x] Test moving-average lengths and range switches (EXP-2026-021)
- [x] Shared 50/200 trend module; perps default signal `trend_50_200_range_10_30`
- [x] `spot-perps` 1x paper account with owner-approved values (UD-32)
- [x] Tests, ADR-044, RUNBOOK 2e
- [ ] Archive main and degen runs, deploy, start `perps-spot-perps` (after merge)
- [ ] Show the `spot-perps` account on the dashboard (after the spot "waiting for" PR merges)
- [x] Spot `sma_stance` reads `trader.regimes.trend.trend_state`
- [ ] Backtest the 10/30 range switch at spot costs before spot uses it
