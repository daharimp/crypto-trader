### Changed
- The paper perps session follows the 1-month trend rule (`tsmom_30d`) by default; the
  moving-average and consensus rules stay selectable with `--signal` (owner decision UD-30,
  ADR-035). Paper only.

### Added
- Dashboard card "Leverage practice · paper account": the forward paper perps session's
  equity, gain or loss since start, open longs and shorts with leverage, largest drop, and
  fees, through a new read-only `/api/perps-paper` route.
