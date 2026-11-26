# 2026-11-26: Check the cooldown and the size range together before both are switched on

The cooldown (ADR-053, EXP-2026-025) and the size range chosen by confidence (ADR-054,
EXP-2026-026) were each tested alone. Both are recommended for the ten-coin paper account
(owner decisions UD-34 and UD-35, open), so they are replayed together first. Research
only; no settings file changes.

- [x] Plan written and committed before any run with both rules on
      (`research/EXP-2026-028-plan.md`)
- [x] `research/run_exp028.py`: the loop equals the three earlier loops before anything
      else is read (`check`: identical on B1 with neither rule and with the built cooldown,
      and on B4 with the built range)
- [x] The four slices, the verdict under the plan's two rules, results file
      (`research/EXP-2026-028-results.txt`): both rules hold at 4, 12 and 24 hours, so the
      recommendation stands; the range's part stays small and deepens the falls
- [x] The real bot loop with both settings against the replay
      (`research/live_path_range.py` with a cooldown length), and a running account
      switched to both settings part of the way through (`research/live_path_switch.py`)
- [x] The owner is told the result before either setting is switched on (results page
      updated and a reply sent with this pull request; both settings stay off until the
      owner picks, UD-34 and UD-35)
