# 2026-11-15: Land the approved perps leverage and borrow changes (owner decisions UD-26 to UD-28)

Built on 2026-11-12 in PRs #21 and #23 (stacked, never merged into `crypto-trader`); landed
here as one pull request at the owner's request (at most 15 files per pull request).

- [x] Opening leverage assessed from volatility, 4 daily moves of buffer (UD-26, ADR-032)
- [x] Ceiling 25x, minimum liquidation distance 3.5% (UD-27)
- [x] Borrow fee 0.0016%/h, Jupiter's documented example (UD-28)
- [x] perps config v9 with approval fields; tests for params, risk, simulator, session
- [ ] Owner: merge, then restart `perps` with a fresh account (RUNBOOK 2c)
