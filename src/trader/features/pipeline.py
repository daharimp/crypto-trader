"""Causal feature computation from a snapshot window (LA-02)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trader.domain.candles import Candle
from trader.domain.features import FeatureSet

from .definitions import DEFINITIONS_HASH, FEATURE_SET_VERSION, WARMUP_BARS


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


def compute_features(
    window: list[Candle],
    instrument_id: str,
    timeframe: str,
    as_of_utc: datetime,
    feature_set_id: str,
    dataset_ids: list[str],
) -> FeatureSet:
    """
    Compute ``features-m1`` at ``as_of_utc`` from closed candles only.

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
    values: dict[str, Decimal | None] = {
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "sma_20_prev": sma(closes[:-1], 20),
        "sma_50_prev": sma(closes[:-1], 50),
        "atr_14": wilder_atr(window, 14),
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
