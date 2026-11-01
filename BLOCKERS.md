# Blockers

**Open blockers: none in the code.** No risk value was invented and no check was bypassed.

## Owner decisions

On **2026-11-01** the owner resolved UD-01 to UD-13 and UD-15 to UD-21 (record:
`docs/spec/product-requirements.md` §10.2; ADR-022). The shipped Balanced profile now
backtests without an experiment set, and `paper` has no unresolved values.

Still open:

| ID | What is missing | Needed before | Current behavior |
|---|---|---|---|
| UD-20 | Market-data venue and the fee tier a $2,500 account pays there (depends on the owner's location) | Real-data evaluation (EXP-2026-002+), forward paper sessions | Synthetic or owner-supplied CSV data; `base` cost scenario stays the R-10 recommendation (0.40% fee, 10 bps) |
| UD-14 | Intraday allocation cap (chosen by EXP-2026-004) | Enabling any intraday strategy | Sleeve disabled; `INTRADAY_NOT_APPROVED` / `INTRADAY_SLEEVE_DISABLED` |

## Not blockers, but not built yet

- Profile activation (BL-028) and forward paper sessions (BL-027): `paper` is still refused
  with `PROFILE_NOT_RUNNABLE [PV-08]`.
- Owner flatten command required by UD-19 option D (BL-048).
