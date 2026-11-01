# ADR-021: Interpretations made while implementing M1

- **Status:** Accepted (implementation decisions, M1). Each choice is the more restrictive
  reading, or is neutral for safety.
- **Date (UTC):** 2026-11-01

| # | Topic | Interpretation |
|---|---|---|
| 1 | Liquidity (eligibility) | Median of daily `sum(volume x close)` over the complete UTC days that exist in the 30 calendar days before `t`. With no complete day the asset is ineligible. |
| 2 | Continuous history | Days from the first bar after the last gap (or the first bar) to `t`. Any gap restarts the count. |
| 3 | Exits and RR-08 | Exits approve the full held quantity; a held quantity of 0 is `SPOT_CONSTRAINT_VIOLATION`. For entries RR-08 requires available cash (cash minus committed) > 0; sizing enforces the rest. |
| 4 | Circuit breaker latch | Checked in RR-09 and also at every mark-to-market, so the breaker latches even when no entry is attempted. |
| 5 | Protective stops | Stops are exempt from the simulator's minimum notional (they protect an existing position). `valid_until_utc` bounds only the submission check (EG-05) at the entry fill time; the stop then rests until filled or canceled. |
| 6 | Expired orders | No `ORDER_EXPIRED` event type exists, so expiry is journaled as `ORDER_CANCELED` with status `expired` and reason `INTENT_EXPIRED`, and counted in rejections by reason. |
| 7 | Benchmarks | Buy-and-hold quantities round down to the instrument step; the remainder stays as cash. Equity marks (strategy and benchmarks) do not deduct a hypothetical exit fee. |
| 8 | Fixture experiments | `EXP-0000-*` IDs are accepted only from a path containing `fixtures`; anything else is rejected, so fixture values cannot be passed off as experiment evidence. |
| 9 | Paper + experiment | `profile validate --environment paper --experiment ...` reports both `EXPERIMENT_PARAMETERS_REJECTED` and `PROFILE_NOT_RUNNABLE` (no activation record exists in M1). Exit 2. |
| 10 | PV-10 registry | `(profile_id, version) -> content hash` is recorded in `data/state/operational.sqlite` at first compile. |
| 11 | Strategy loading | `code_ref` is matched against an in-repo allowlist rather than imported dynamically. |
| 12 | Snapshot lineage | Market snapshots are journaled inside `FEATURES_COMPUTED` (payload `SnapshotAndFeatures`); `journal verify` matches each order's `market_data_timestamp_utc` against them. |
