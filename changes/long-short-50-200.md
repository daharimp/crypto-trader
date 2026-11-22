### Changed
- Every paper perps account now picks long or short from one shared trend rule, `trader/regimes/trend.py`: 50-candle vs 200-candle average of 4h closes, switching to 10/30 when the last 30 days are choppy (efficiency ratio < 0.05) (ADR-044). New default signal `trend_50_200_range_10_30`, replacing `tsmom_30d`; the old signals stay selectable with `--signal`.

### Added
- `spot-perps` paper account (`configs/perps/jupiter-spot-perps.yaml`, compose service `perps-spot-perps`): spot's trend rule long and short at 1x, because spot code stays long-only (ADR-044, UD-32).
