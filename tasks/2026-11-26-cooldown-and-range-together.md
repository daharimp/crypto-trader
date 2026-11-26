# 2026-11-26: Check the cooldown and the size range together before both are switched on

The cooldown (ADR-053, EXP-2026-025) and the size range chosen by confidence (ADR-054,
EXP-2026-026) were each tested alone. Both are recommended for the ten-coin paper account
(owner decisions UD-34 and UD-35, open), so they are replayed together first. Research
only; no settings file changes.

- [x] Plan written and committed before any run with both rules on
      (`research/EXP-2026-028-plan.md`)
- [ ] `research/run_exp028.py`: the loop equals the three earlier loops before anything
      else is read
- [ ] The four slices, the verdict under the plan's two rules, results file
- [ ] The owner is told the result before either setting is switched on
