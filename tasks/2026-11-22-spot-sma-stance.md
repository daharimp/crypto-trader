# 2026-11-22: Get the spot bot trading (owner request)

- [x] Find why paper spot made no trades (no 4h SMA20/50 cross-up on any coin since Nov 15)
- [x] EXP-2026-018: portfolio replay of 11 entry rules, 3 years, 180-day holdout
- [x] Owner chose the 50/200 stance plus a "why idle" line
- [x] `sma_stance` strategy, `sma_200` feature, per-coin watch line in state and dashboard
- [x] EXP-2026-019 long/short replay handed to the long/short thread
- [ ] Deploy to the server (git pull, docker compose build, docker compose up -d paper)
