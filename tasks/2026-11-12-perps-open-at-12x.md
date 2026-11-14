# 2026-11-12: Paper perps open at 12x (owner decision UD-25)

- [x] `configs/perps/jupiter.yaml` v6: `target_leverage` 12, approved by the owner 2026-11-12
- [x] Test that 12x clears the 8% liquidation-distance rule and the total-size cap
- [ ] Owner: on the server, `git pull`, then `docker compose up -d perps` (restart) to use v6
