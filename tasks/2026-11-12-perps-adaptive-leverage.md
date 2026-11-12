# 2026-11-12: Assess each opening leverage from volatility (owner decision UD-26)

- [x] `liquidation_buffer_daily_moves` = 4 in `configs/perps/jupiter.yaml` v7 (ADR-032)
- [x] Risk code picks the opening leverage per market; replay and forward session share it
- [x] Tests: volatility measure, leverage rule, fail closed without 30 days of candles
- [ ] Owner: on the server, `git pull`, `docker compose build`, `docker compose up -d --force-recreate perps`
- [ ] Research: compare assessed vs fixed leverage on 5 to 10 years of history, in dollars
