"""Feature set ``features-m1-1.0.0`` definitions (handoff §7.7)."""

from __future__ import annotations

from trader.common.hashing import hash_obj

FEATURE_SET_VERSION = "features-m1-1.0.0"
# Reason: ATR is Wilder-smoothed inside a fixed causal window, so values depend only on the
# last FEATURE_WINDOW_BARS closed bars and are reproducible regardless of dataset length.
FEATURE_WINDOW_BARS = 150
WARMUP_BARS = 51  # sma_50 at t and t-1

DEFINITIONS = {
    "sma_20": "simple mean of the last 20 closes",
    "sma_50": "simple mean of the last 50 closes",
    "sma_20_prev": "sma_20 at the previous bar close",
    "sma_50_prev": "sma_50 at the previous bar close",
    "atr_14": "Wilder ATR(14) on the decision timeframe, seeded inside the window",
    "window_bars": FEATURE_WINDOW_BARS,
}
DEFINITIONS_HASH = hash_obj(DEFINITIONS)
