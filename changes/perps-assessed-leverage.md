### Changed
- Paper perps opens each position at a leverage assessed from the market's recent volatility
  (liquidation kept 4 typical daily moves away), up to a 25x ceiling with a 3.5% minimum
  liquidation distance, and charges Jupiter's documented borrow rate of 0.0016%/h
  (owner decisions UD-26, UD-27, UD-28; ADR-032; perps config v9). Paper only.
