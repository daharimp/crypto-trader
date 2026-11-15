# 2026-11-15: Paper perps on the 1-month trend rule, shown on the dashboard (owner request)

Signals built on 2026-11-12/14 in PRs #24 and #26 (stacked, never merged into
`crypto-trader`); landed here with the dashboard card at the owner's request (at most 15
files per pull request).

- [x] `trader.perps.signals`: `tsmom_30d` (default), `sma_stance_20_50`, `consensus_sma_tsmom`
- [x] `trader perps paper run --signal`; a saved account refuses a different signal
- [x] Read-only `/api/perps-paper` and the "Leverage practice · paper account" card
- [x] Tests: signals, session CLI, dashboard route (not started, served, read-only, 502)
- [x] Owner: merge, then restart `perps` with a fresh account and `dashboard` (RUNBOOK 2c) (status shows `tsmom_30d`, 2026-11-15)
