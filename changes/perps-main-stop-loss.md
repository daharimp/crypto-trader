### Added
- Main paper perps account: stop-loss at 50% of collateral, about 2 typical daily moves from entry (`configs/perps/jupiter.yaml` v10, UD-31, ADR-042).

### Changed
- Every perps config file must set `risk.stop_loss_pct_of_collateral`; a file without one fails closed with exit 3 (ADR-042).
