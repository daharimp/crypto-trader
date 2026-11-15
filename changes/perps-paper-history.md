### Added
- `/api/perps-paper` (read-only) now also returns the paper perps account's closed trades
  with dollars won or lost after fees, the equity it recorded at its start and at each day
  change, and for every open position the leverage and liquidation price recorded when it
  opened. All of it is rebuilt from the session's event log by `trader.perps.history`; the
  session itself is unchanged.
