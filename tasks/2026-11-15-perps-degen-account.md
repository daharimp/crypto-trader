# 2026-11-15: Second paper perps account, "degen" (owner decision UD-29, ADR-038)

- [x] Owner approved: buffer 3, 5% per position, stop at 30% of collateral, 15% bad-day stop
      with an alert, SOL/BTC/ETH, all settings adjustable
- [x] Own config, state file, event log, alerts and Compose service; `--account` option
- [x] Stop, wait-until-next-day, `DAY_HALTED` alert; off unless configured (main unchanged)
- [x] Dashboard **Degen · paper** view with its settings (read-only)
- [x] Tests: config, stop (long, short, gap, liquidation), bad day, state, CLI, dashboard
- [ ] Owner: merge, then start it (RUNBOOK 2d); do not restart `perps` mid-test
- [ ] Next (owner request): an AI assistant that helps on bad days and with settings; proposal
      first, owner approves the design (it must not set risk values itself)
