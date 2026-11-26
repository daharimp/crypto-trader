# 2026-11-26: Write a settings change into the run's own history (found while preparing UD-34 and UD-35)

A paper perps run continues when a value in its settings file changes, and nothing in the
run recorded it: trades before and after the change could only be told apart from deploy
times. The owner's two open choices for the ten-coin account (UD-34, UD-35) go in exactly
that way, so the change is recorded first (ADR-056). No trading behaviour changes.

- [x] The state file records the settings in force (`settings_record`)
- [x] One `SETTINGS_CHANGED` event at the first cycle after a change, with the old and new
      value of each changed setting and both versions; sent as one alert
- [x] Edges covered by tests: the same number written differently, a raised version alone,
      a value changed without a version, a run saved before the record, a restart inside
      the same candle, another market list (still needs a new run)
- [x] Dry run of the real bot loop through a switch (`research/live_path_switch.py`)
- [x] ADR-056, RUNBOOK 2d, change note
- [x] The four running accounts' saved versions equal their files' versions (main 11,
      degen 2, spot-perps 1, top10 1 in the server's status push of 2026-11-26 10:20 UTC),
      so deploying this writes no event and sends no alert
