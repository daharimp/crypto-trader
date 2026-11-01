# Blockers

**M1 blockers found: None.** Every M1 item was implemented without inventing a risk value,
bypassing a check, or adding a live capability. Unresolved values stay `TBD`, and runs that
need them exit 3 with their UD IDs.

## Known, expected blockers (not M1 failures; owner decisions)

These are listed in `docs/spec/code-session-handoff.md` §12 and `execution-plan.md` §7. The
code fails closed until the owner resolves them in `configs/risk/*.yaml` /
`configs/universe/eligibility.yaml` (with a version increment):

| Activity | Needs | Current behavior |
|---|---|---|
| Backtest without an experiment set | UD-01, UD-02, UD-03, UD-04, UD-12, UD-15, UD-16, UD-17, UD-18 | Exit 3, `RUN_BLOCKED` journaled, no orders |
| Paper activation / forward paper (V1, BL-027/028) | Above plus UD-05, UD-17 (grace, skew, escalation), UD-19, UD-20 | `paper` refuses experiment values; no activation command exists yet |
| Conservative / Aggressive outside experiments | UD-13 and that profile's values | Blocked with UD-13 |
| Intraday sleeve | UD-14 | `INTRADAY_NOT_APPROVED` / `INTRADAY_SLEEVE_DISABLED` |
| Major / Speculative assets | UD-06, UD-18 | Not in the registry or profile scope |

Options and recommendations for each: `docs/spec/product-requirements.md` §10.
