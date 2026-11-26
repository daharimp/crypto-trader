### Added
- Optional `risk.min_collateral_per_position_pct` for paper perps accounts (ADR-054): with
  it, `max_collateral_per_position_pct` becomes the largest size and each new position is
  sized between the two by a deterministic confidence score from 0 to 1
  (`trader.perps.confidence`: breadth, trend strength, timeframe agreement; the composite of
  EXP-2026-026). Off in every account until the owner picks a range (UD-35); `perps
  validate` shows it. An open without a score is refused (`PERP_CONFIDENCE_UNAVAILABLE`).
  With a range set, each `OPENED` event carries `confidence` and `collateral_pct`, and the
  session also reads daily candles.
- Research: `run_exp026.py engine-<slice>` shows the built range sizing takes exactly the
  trades and sizes of the research composite; results appended to
  `research/EXP-2026-026-results.txt`.
