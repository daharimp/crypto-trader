"""Feature set ``features-m2-1.0.0`` definitions (features-m1 plus BL-022 baselines)."""

from __future__ import annotations

from trader.common.hashing import hash_obj

FEATURE_SET_VERSION = "features-m2-1.0.0"
# Reason: ATR is Wilder-smoothed inside a fixed causal window, so values depend only on the
# last FEATURE_WINDOW_BARS closed bars and are reproducible regardless of dataset length.
FEATURE_WINDOW_BARS = 200
# Reason: ATR and RSI stay seeded on the last 150 bars (as in features-m1), so sma_trend's
# sizes are unchanged; the longer window only serves the 7-day return on 1h bars (169 bars).
SMOOTHING_WINDOW_BARS = 150
WARMUP_BARS = 51  # sma_50 at t and t-1

DEFINITIONS = {
    "sma_20": "simple mean of the last 20 closes",
    "sma_50": "simple mean of the last 50 closes",
    "sma_20_prev": "sma_20 at the previous bar close",
    "sma_50_prev": "sma_50 at the previous bar close",
    "atr_14": "Wilder ATR(14) on the decision timeframe, seeded inside the last 150 bars",
    "rsi_14": "Wilder RSI(14) of closes, seeded inside the last 150 bars",
    "bb_mid_20": "SMA(20) of closes (Bollinger middle band)",
    "bb_lower_20": "SMA(20) - 2 x population std(20) of closes",
    "bb_upper_20": "SMA(20) + 2 x population std(20) of closes",
    "high_20_prev": "highest high of the 20 bars before the current bar",
    "low_10_prev": "lowest low of the 10 bars before the current bar",
    "ret_7d": "close / close 7 days earlier - 1 (42 bars on 4h, 168 on 1h)",
    "ret_7d_prev": "ret_7d at the previous bar close",
    "window_bars": FEATURE_WINDOW_BARS,
    "smoothing_window_bars": SMOOTHING_WINDOW_BARS,
}
DEFINITIONS_HASH = hash_obj(DEFINITIONS)
