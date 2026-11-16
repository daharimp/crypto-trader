# 2026-11-16: Sweep more often, and show every position (owner requests)

- [x] Replay first: hourly vs 4-hourly about even (`research/sweep-frequency-replay-results.txt`)
- [x] Owner: "make the requested changes"
- [x] `trend_timeframe` in the session; `--timeframe 1h` uses 4h candles for trend and volatility
- [x] Degen account hourly in Compose; main unchanged during its 7-day test
- [x] Dashboard All view and position details on each card; checked in Chromium at phone width
- [x] Tests: hourly trades only with the 4h trend, validation, saved-state guard, CLI, Compose, UI
- [ ] Owner: merge, `git pull && docker compose build`, reset and restart `perps-degen` (RUNBOOK 2d)
