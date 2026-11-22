### Added
- Perps take-profit ladder (ADR-044, UD-32): TP1 moves the stop to breakeven, TP2 to TP1,
  TP3 closes the rest; partial closes are journaled as `TAKE_PROFIT` and alerted. Optional
  per account; enabled on the degen paper account only.
