### Added
- A second, separate paper perps account, `degen` (ADR-038, UD-29): `trader perps paper run
  --account degen` with its own settings (`configs/perps/jupiter-degen.yaml`: buffer 3, 5% per
  position, stop at 30% of collateral, 15% bad-day stop), state file, event log, alerts,
  Compose service `perps-degen`, and a **Degen · paper** dashboard view showing its settings.
- Optional perps risk value `stop_loss_pct_of_collateral`: closes a position at that share of
  its collateral lost and waits until the next UTC day before reopening that market.
- A `DAY_HALTED` event and phone alert when the daily loss limit is reached (both accounts).
