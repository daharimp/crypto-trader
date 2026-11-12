# 2026-11-12: Let the assessed leverage go above 12x (owner decision UD-27)

- [x] `configs/perps/jupiter.yaml` v8: ceiling 25x, minimum liquidation distance 3.5%
- [x] Tests for the leverage picked at four volatility levels and for the total-size cap
- [ ] Owner: on the server, `git pull`, `docker compose build`, `docker compose up -d --force-recreate perps`
- [ ] Research (strategy session): test whether raising leverage on a strong signal helps, before building it
