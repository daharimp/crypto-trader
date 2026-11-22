### Added
- Perps take-profit ladder (ADR-045, UD-32): TP1 moves the stop to breakeven, TP2 to TP1,
  TP3 closes the rest; partial closes are journaled as `TAKE_PROFIT` and alerted.

### Changed
- Main and degen paper perps: stop at 30% of collateral (main was 50%) and the ladder at
  TP 4/8/12R closing 25/25/50 (`jupiter.yaml` v11, `jupiter-degen.yaml` v2).
