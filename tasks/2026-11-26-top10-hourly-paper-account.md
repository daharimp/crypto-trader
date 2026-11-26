# 2026-11-26: A ten-coin hourly paper account beside the existing ones (owner request, UD-33)

Owner: "more frequent trades on more of the top cryptos"; chose "Hourly decisions only", then
"correct from top 20 to top 10". Existing accounts and their runs stay untouched; nothing is
reset; nothing is live.

- [x] Research: EXP-2026-023 (why the bots look bad) and EXP-2026-024 (twenty and ten coins,
      wider stop, decision speed), plans committed before results
- [x] `generic_perps` venue: a settings file may name any coin with a candle feed (ADR-051)
- [x] `configs/perps/top10.yaml` with the owner's values; six more Kraken pairs
- [x] Borrow accrues exactly; cents only when paid (was zero on small hourly positions)
- [x] Paced candle requests with retries; the account starts 180 s after the bar closes
- [x] `scripts/ops/start_new.sh`: the watchdog creates a service that a deploy added
- [x] Watchdog, review lists, compose service, runbook 2f
- [x] Tests: tests/unit/test_perps_top10.py, tests/integration/test_start_new_script.py
- [ ] Confirm on the server: `perps-top10` running, first hourly cycles in the status push
- [ ] Dashboard view for the account (needs Kraken prices for coins Jupiter does not list)
- [ ] EXP-2026-025: cooldown, stop guard, correlation sizing, time limit (plan committed)
- [ ] EXP-2026-026: does any confidence measure earn a size range (plan committed)
- [ ] Size range per account as a setting; a measure chooses inside it only if it passes
