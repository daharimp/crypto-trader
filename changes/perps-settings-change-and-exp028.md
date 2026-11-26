### Added
- Paper perps accounts write a `SETTINGS_CHANGED` event (old and new value of each changed
  setting, both versions) into their event log at the first cycle after a settings change,
  and send it as one alert; the state file records the settings in force (ADR-056). The run
  continues as before; no trading behaviour changes.
- Research: EXP-2026-028, the cooldown (ADR-053) and the size range (ADR-054) replayed
  together on the ten-coin hourly account, with its plan, run script and results.
