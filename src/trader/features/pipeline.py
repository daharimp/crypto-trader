"""Causal feature computation from a snapshot window (LA-02)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from trader.common.clock import timeframe_delta
from trader.domain.candles import Candle
from trader.domain.features import FeatureSet

from .definitions import DEFINITIONS_HASH, FEATURE_SET_VERSION, SMOOTHING_WINDOW_BARS, WARMUP_BARS


def sma(values: list[Decimal], n: int) -> Decimal | None:
    """
    Simple moving average of the last ``n`` values.

    Args:
        values (list[Decimal]): Series.
        n (int): Period.

    Returns:
        Decimal | None: Mean, or None if fewer than ``n`` values.
    """
    if len(values) < n:
        return None
    return sum(values[-n:], Decimal(0)) / Decimal(n)


def wilder_atr(candles: list[Candle], n: int = 14) -> Decimal | None:
    """
    Wilder ATR over the given candles.

    Args:
        candles (list[Candle]): Window, oldest first.
        n (int): Period.

    Returns:
        Decimal | None: ATR, or None if fewer than ``n + 1`` candles.
    """
    if len(candles) < n + 1:
        return None
    trs = [
        max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        for p, c in zip(candles, candles[1:], strict=False)
    ]
    atr = sum(trs[:n], Decimal(0)) / Decimal(n)
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / Decimal(n)
    return atr


def wilder_rsi(closes: list[Decimal], n: int = 14) -> Decimal | None:
    """
    Wilder RSI of a close series.

    Args:
        closes (list[Decimal]): Closes, oldest first.
        n (int): Period.

    Returns:
        Decimal | None: RSI in [0, 100], or None with fewer than ``n + 1`` closes.
    """
    if len(closes) < n + 1:
        return None
    diffs = [b - a for a, b in zip(closes, closes[1:], strict=False)]
    gain = sum((d for d in diffs[:n] if d > 0), Decimal(0)) / n
    loss = sum((-d for d in diffs[:n] if d < 0), Decimal(0)) / n
    for d in diffs[n:]:
        gain = (gain * (n - 1) + max(d, Decimal(0))) / n
        loss = (loss * (n - 1) + max(-d, Decimal(0))) / n
    if loss == 0:
        return Decimal(100) if gain > 0 else Decimal(50)
    return Decimal(100) - Decimal(100) / (1 + gain / loss)


def bollinger(closes: list[Decimal], n: int = 20, k: int = 2) -> tuple[Decimal, ...] | None:
    """
    Bollinger bands (population standard deviation).

    Args:
        closes (list[Decimal]): Closes.
        n (int): Period.
        k (int): Band width in standard deviations.

    Returns:
        tuple[Decimal, ...] | None: ``(lower, mid, upper)`` or None if too short.
    """
    if len(closes) < n:
        return None
    last = closes[-n:]
    mid = sum(last, Decimal(0)) / n
    std = (sum(((c - mid) ** 2 for c in last), Decimal(0)) / n).sqrt()
    return mid - k * std, mid, mid + k * std


def trailing_return(closes: list[Decimal], bars: int) -> Decimal | None:
    """
    ``close[t] / close[t - bars] - 1``.

    Args:
        closes (list[Decimal]): Closes.
        bars (int): Lookback in bars.

    Returns:
        Decimal | None: Return, or None if too short.
    """
    if len(closes) < bars + 1 or closes[-bars - 1] == 0:
        return None
    return closes[-1] / closes[-bars - 1] - 1


def compute_features(
    window: list[Candle],
    instrument_id: str,
    timeframe: str,
    as_of_utc: datetime,
    feature_set_id: str,
    dataset_ids: list[str],
) -> FeatureSet:
    """
    Compute ``features-m2`` at ``as_of_utc`` from closed candles only.

    Args:
        window (list[Candle]): Candles with ``close_time_utc <= as_of_utc``.
        instrument_id (str): Instrument.
        timeframe (str): Timeframe.
        as_of_utc (datetime): Decision time.
        feature_set_id (str): ID to assign.
        dataset_ids (list[str]): Input datasets.

    Returns:
        FeatureSet: Features (values None until warm-up).
    """
    closes = [c.close for c in window]
    smooth = window[-SMOOTHING_WINDOW_BARS:]
    bb = bollinger(closes)
    lookback = int(timedelta(days=7) / timeframe_delta(timeframe))
    prev = window[:-1]
    values: dict[str, Decimal | None] = {
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "sma_20_prev": sma(closes[:-1], 20),
        "sma_50_prev": sma(closes[:-1], 50),
        "atr_14": wilder_atr(smooth, 14),
        "rsi_14": wilder_rsi([c.close for c in smooth], 14),
        "bb_lower_20": bb[0] if bb else None,
        "bb_mid_20": bb[1] if bb else None,
        "bb_upper_20": bb[2] if bb else None,
        "high_20_prev": max(c.high for c in prev[-20:]) if len(prev) >= 20 else None,
        "low_10_prev": min(c.low for c in prev[-10:]) if len(prev) >= 10 else None,
        "ret_7d": trailing_return(closes, lookback),
        "ret_7d_prev": trailing_return(closes[:-1], lookback),
    }
    return FeatureSet(
        schema_version="1.0.0",
        feature_set_id=feature_set_id,
        instrument_id=instrument_id,
        timeframe=timeframe,
        as_of_utc=as_of_utc,
        feature_set_version=FEATURE_SET_VERSION,
        definitions_hash=DEFINITIONS_HASH,
        values=values,
        max_input_close_time_utc=window[-1].close_time_utc if window else as_of_utc,
        warmup_complete=len(window) >= WARMUP_BARS,
        input_dataset_ids=dataset_ids,
    )
