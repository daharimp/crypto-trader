### Added
- Optional `risk.cooldown_after_loss_hours` for paper perps accounts (ADR-053): after a
  trade that lost money after fees, that market opens nothing for the given hours, counted
  from the candle that closed it. Off in every account until the owner picks a length
  (UD-34); `perps validate` shows it. Each wait is journaled as `COOLDOWN_STARTED`.
- Research: EXP-2026-025 results (of four add-ons only the cooldown passes) and
  EXP-2026-026 results (one confidence measure, the composite, narrowly earns a size range),
  with their harnesses and run scripts.

### Changed
- A perps settings file with an unknown key under `risk:` is refused (exit 2) instead of
  the key being ignored.
