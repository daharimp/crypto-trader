# ADR-020: features-m1 computation details

- **Status:** Accepted (implementation decision, M1)
- **Date (UTC):** 2026-11-01
- **Context:** `sma_trend` needs `sma_20[t-1]` and `sma_50[t-1]` to detect a cross, and the
  handoff does not say how much history Wilder ATR should be seeded from.
- **Decision:** (1) `FeatureSet.values` also contains `sma_20_prev` and `sma_50_prev`, computed
  from the same causal window minus its last bar. (2) Features are computed from the last
  `FEATURE_WINDOW_BARS = 150` closed bars. ATR(14) is seeded with the mean of the window's first
  14 true ranges, then Wilder-smoothed. (3) Warm-up is complete at 51 closed bars.
- **Reason:** Values depend only on a fixed window of closed bars, so they are causal (LA-02),
  reproducible, and unaffected by dataset length or future data (T-20).
- **Consequence:** ATR differs slightly from a full-history Wilder ATR. The window size is part
  of `definitions_hash`, so any change is visible in lineage.
