"""Real perpetual-futures funding as the holding cost in research replays (EXP-2026-014).

Research only; never imported by the trading pipeline. Funding is the hourly payment between
longs and shorts on a perpetual: a positive rate means longs pay shorts, a negative rate
means shorts pay longs. Rates are measured data read from CSV; a missing hour stays missing
and is never filled in.
"""

from __future__ import annotations

import pandas as pd

HOURS_PER_BAR = 4  # the lab's candles are 4h


def load_funding(path: str) -> pd.Series:
    """
    Load hourly funding written by ``scripts/fetch_funding_history.py``.

    Args:
        path (str): CSV with columns ``hour_start_utc`` and ``rate``.

    Returns:
        pd.Series: Rate per hour (fraction of position size), indexed by UTC hour start.

    Raises:
        ValueError: If a column is missing, a timestamp is not a whole hour, or an hour
            appears twice.
    """
    df = pd.read_csv(path)
    if list(df.columns) != ["hour_start_utc", "rate"]:
        raise ValueError(f"{path}: expected columns hour_start_utc,rate")
    idx = pd.DatetimeIndex(pd.to_datetime(df["hour_start_utc"], utc=True))
    if len(idx) and ((idx.minute != 0) | (idx.second != 0)).any():
        raise ValueError(f"{path}: timestamps must be whole hours")
    if idx.has_duplicates:
        raise ValueError(f"{path}: duplicate hours")
    return pd.Series(df["rate"].astype(float).to_numpy(), index=idx).sort_index()


def per_bar(funding: pd.Series, bars: pd.DatetimeIndex) -> pd.Series:
    """
    Funding summed over each 4h bar.

    Args:
        funding (pd.Series): Hourly rates indexed by hour start.
        bars (pd.DatetimeIndex): Bar open times (UTC).

    Returns:
        pd.Series: Sum of the four hourly rates from each bar's open; NaN when any of the
        four hours has no published rate.
    """
    parts = [funding.reindex(bars + pd.Timedelta(hours=h)).to_numpy() for h in range(HOURS_PER_BAR)]
    # Reason: adding NaN gives NaN, so a bar with any missing hour is marked, not patched.
    return pd.Series(sum(parts[1:], parts[0]), index=bars)


def simulate_funded(
    df: pd.DataFrame, target: pd.Series, fee_bps_per_side: float, bar_funding: pd.Series
) -> pd.Series:
    """
    Per-bar net returns at 1x with trading fees and real funding.

    Same timing as ``lab.simulate``: a position decided at close *i* is held from the open
    of *i+1*, so it pays the funding of the bars it is actually held through.

    Args:
        df (pd.DataFrame): Candles.
        target (pd.Series): Desired position after each bar's close (long > 0, short < 0).
        fee_bps_per_side (float): Fee in basis points of the traded size.
        bar_funding (pd.Series): Output of ``per_bar`` on the same index.

    Returns:
        pd.Series: Net return per bar; NaN on bars whose funding is unknown.

    Raises:
        ValueError: If ``bar_funding`` is not on the candles' index.
    """
    if not bar_funding.index.equals(df.index):
        raise ValueError("bar_funding must use the candles' index")
    pos = target.shift(1).fillna(0.0)
    o = df["open"]
    ret = (o.shift(-1) / o - 1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    fees = turnover * fee_bps_per_side / 10_000
    # Reason: a long (pos > 0) pays positive funding and a short receives it; the sign of
    # the position does the bookkeeping.
    return pos * ret - fees - pos * bar_funding
