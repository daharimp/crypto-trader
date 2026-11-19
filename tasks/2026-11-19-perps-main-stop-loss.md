# 2026-11-19: Stop-loss on the main perps account, and always assess one (owner request)

- [x] Require `stop_loss_pct_of_collateral` in every perps config (exit 3 without it)
- [x] Main account stop at 50% of collateral, `jupiter.yaml` v10 (UD-31, ADR-042)
- [x] Confirm spot already sizes from and rests a stop on every entry (UD-16)
- [ ] Sweep stop levels (30-70%) on the main account's settings with `research/guarded_replay.py` once replay data is available
