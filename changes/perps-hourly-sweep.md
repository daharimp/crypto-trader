### Added
- Hourly sweep (ADR-040): `trader perps paper run --timeframe 1h` now trades, checking every
  hour with the 30-day trend and volatility read from 4h candles; the degen account runs hourly
  in Compose (the main account is unchanged).
- Dashboard **All** view: every account's open positions grouped by account, combined value
  and merged trades; each position card now shows entry, price now, liquidation or stop, and
  when it opened.
