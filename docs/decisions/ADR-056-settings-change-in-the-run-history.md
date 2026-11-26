# ADR-056: A change of settings is written into the run's own history

- **Status:** Accepted (2026-11-26).
- **Context:** A paper perps run continues when a value in its settings file changes: only
  another signal, timeframe or market list needs a new run (ADR-041). That is how the
  owner's choices are meant to go in (RUNBOOK 2d, 2f: edit the value, raise `version`,
  restart, no reset). Until now nothing in the run recorded it. The state file kept the
  version the run started under, the archive summary reported that first version for the
  whole run, and the event log had no line saying when a value changed. With the cooldown
  (ADR-053) and the size range (ADR-054) about to be switched on in a running account,
  trades before and after the change could only be told apart by guessing from deploy
  times. The owner asked for logs and data to improve the bots from; a comparison across a
  settings change needs the change in the data.
- **Decision:**
  1. The state file's `meta` holds `settings`: every resolved value of the account except
     its market list (`trader.perps.account_state.settings_record`), numbers as text, an
     option that is off as null.
  2. When a session resumes and the settings differ from that record, the first cycle that
     processes a bar writes one `SETTINGS_CHANGED` event before any other event of that
     cycle: `from_version`, `to_version` and `changed` (each changed setting with its old
     and new value), then updates `meta.settings` and `meta.config_version`. It is written
     with a cycle that saves, so it appears exactly once.
  3. The event is also a phone alert, in one line. A settings change is rare and always the
     owner's decision, and the alert confirms the server picked it up.
  4. Edges: the same number written differently (`1` and `1.0`) is not a change. A raised
     version with no changed value is reported with an empty `changed`. A value changed
     without raising the version is reported too (same version twice), so a skipped
     version shows. A run saved before this record only knows its version: another version
     is reported without values, the same version is not reported, and the record is added
     silently. A setting that newer code adds and leaves off is not a change.
- **Consequences:** Reviews and later experiments can split a run's trades at the exact
  cycle a setting changed. The archive summary's `config_version` is now the version the
  run ended under; the event log holds every version before it. Nothing about trading
  changes: no risk value, no sizing, no order. Deploying this to the running accounts
  writes no event (their versions did not change) and adds the record at their next cycle.
- **Alternatives rejected:** starting a new run for every change (it would throw away open
  positions and the run's history, and the owner asked for no resets); recording only the
  version (it does not say what changed, and a value edited without a version would stay
  invisible).
