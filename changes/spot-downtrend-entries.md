### Added
- `sma_stance` 50/200 trend strategy for paper spot, and the `sma_200` feature (ADR-043, EXP-2026-018).
- Dashboard: the Spot account shows what each coin is waiting for, written by the session every check.
- Research: EXP-2026-018 (spot entry rules) and EXP-2026-019 (50/200 long/short, shorts on paper perps).

### Changed
- The paper spot service runs `sma_stance` by default (`TRADER_PAPER_STRATEGY` overrides it); live is unchanged.
