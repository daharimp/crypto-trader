# ADR-029: Live market snapshot judged against history

- **Status:** Accepted (2026-11-10; owner asked for more real-time quant analysis, with
  history as the yardstick: "history is very important in the market")
- **Context:** Backtests answer "what would a rule have done"; they do not say what the
  market looks like now or how today's state compares with the past. The owner wants both.
- **Decision:**
  1. `trader research snapshot` reads public Kraken candles (4h, daily) and order books for
     the five universe coins (fixed allowlist), measures each coin's state (1/3/12-month
     returns, 4h RSI, side of the 200-bar average, volatility and squeeze percentiles,
     spread and depth within 1%), and cross-coin correlation.
  2. For coins with local history (`data/long/<coin>_usd_4h.csv`), it finds past bars in the
     same state (momentum pattern, then plus RSI bucket or trend side), keeps non-overlapping
     episodes per horizon, and reports what a long earned over the next week and month in
     dollars, with a bootstrap 90% range.
  3. It states how many "range excludes $0" rows luck alone would produce, so a single hit is
     read as a lead, not a finding.
  4. Read-only: no keys, no orders, never imported by the trading pipeline. Network access
     goes through injectable fetchers so tests run offline. A coin whose data fails is
     reported and skipped; if none can be read the command exits 3.
- **Consequences:** Conditional samples are small (often 10 to 50 episodes), so most ranges
  include $0; that is the honest answer, not a defect. History comes from Coinbase while live
  state comes from Kraken; prices track closely for these pairs, but they are not identical.
