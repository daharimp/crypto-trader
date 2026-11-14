# 2026-11-12: Use Jupiter's documented borrow rate in paper perps (owner decision UD-28)

- [x] `configs/perps/jupiter.yaml` v9: `borrow_rate_pct_per_hour` 0.0016, approved by the owner
- [ ] Owner: on the server, `git pull`, `docker compose up -d --force-recreate perps`
- [ ] Re-check the rate against Jupiter's live "Borrow Rate" figure from time to time; it changes with pool utilization
