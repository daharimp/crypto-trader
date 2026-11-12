# ADR-033: Measured perps funding as the holding cost in research replays

- **Status:** Accepted (2026-11-12; research tooling only)
- **Context:** EXP-2026-013 showed that the answer to "does shorting add money?" was decided
  by an assumed holding cost (0.01% per hour, about 88% of position size per year). On
  perpetual futures the real holding cost is the funding rate paid between longs and shorts.
- **Decision:**
  1. `scripts/fetch_funding_history.py` downloads public hourly funding (no key, no account)
     from Deribit, Hyperliquid, and Kraken Futures into `data/funding/` (git-ignored).
  2. `trader.research.funding` loads it, sums it per 4h bar, and `simulate_funded` charges
     fees plus position times funding with the lab's timing (decide at a close, hold from the
     next open). A bar with a missing hour is NaN and is dropped by the caller; a missing
     rate is never filled in or assumed to be zero.
  3. Deribit is the deciding source for EXP-2026-014 because it has the longest history
     reachable from the cloud environment; the others are cross-checks. BitMEX refuses the
     environment's location; Binance, Bybit, OKX and others are not on its allow-list.
  4. Timestamp conventions: a Deribit or Hyperliquid record stamped *T* covers the hour ending
     at *T*; a Kraken record stamped *T* covers the hour starting at *T*.
- **Reason:** a measured cost replaces an assumption without touching any approved value.
- **Consequence:** research only. The module is never imported by the trading pipeline, the
  paper perps session, or its config; the owner-approved venue values (UD-23) are unchanged.
  Spot prices still stand in for perps prices, and Deribit does not serve US customers, so
  results describe funding-style venues in general, not a venue the owner can use today.
- **References:** ADR-025, ADR-027, ADR-031, UD-23, UD-24, EXP-2026-013, EXP-2026-014.
