"""Strategy research lab: fast tests of many ideas on real candles (ADR-026).

Research only. It never trades and is never imported by the trading pipeline. Rules:

* Decisions use bars up to *i*; positions change at the open of bar *i+1* (no look-ahead).
* Costs are charged on every position change (bps of notional per side) and, for perps,
  an hourly borrow fee while a position is open.
* Results are reported per walk-forward fold and against buy-and-hold in the same fold.
* The last ``holdout_days`` are sealed: ``evaluate`` refuses them unless ``holdout=True``.

Positions are in {-1, 0, +1} at 1x. An idea must show an edge at 1x before leverage.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

BARS_PER_YEAR = 6 * 365  # 4h bars
Signal = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class Costs:
    """Trading costs for one venue."""

    name: str
    fee_bps_per_side: float
    borrow_pct_per_hour: float = 0.0


PERPS = Costs("jupiter_perps", 7.0, 0.01)  # owner-approved UD-23 v4 values
SPOT = Costs("kraken_spot", 50.0)  # 0.40% fee + 0.10% slippage (shipped base scenario)


def load_csv(path: str) -> pd.DataFrame:
    """
    Load a 4h candle CSV written by ``scripts/fetch_coinbase_history.py``.

    Args:
        path (str): CSV path.

    Returns:
        pd.DataFrame: Indexed by UTC open time, float OHLCV columns.
    """
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df.pop("open_time_utc"), utc=True)
    return df.astype(float)


# ---------- indicators (causal: each value uses bars up to and including its own) ----------


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    """Wilder-style average true range (simple rolling mean of true range)."""
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(n).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Relative strength index with simple averages."""
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


# ---------- signals: return the desired position after each bar's close ----------


def sma_stance(fast: int, slow: int, shorts: bool) -> Signal:
    """Long above, short (or flat) below: the current perps baseline."""

    def f(df: pd.DataFrame) -> pd.Series:
        c = df["close"]
        s = (c.rolling(fast).mean() - c.rolling(slow).mean()).apply(np.sign)
        return s if shorts else s.clip(lower=0)

    return f


def tsmom(lookback: int, shorts: bool) -> Signal:
    """Time-series momentum: the sign of the trailing return."""

    def f(df: pd.DataFrame) -> pd.Series:
        s = df["close"].pct_change(lookback).apply(np.sign)
        return s if shorts else s.clip(lower=0)

    return f


def donchian(entry: int, exit_: int, shorts: bool) -> Signal:
    """Breakout: enter on a new N-bar high (low), exit on an M-bar low (high)."""

    def f(df: pd.DataFrame) -> pd.Series:
        hi = df["high"].rolling(entry).max().shift(1).to_numpy(dtype=float)
        lo = df["low"].rolling(entry).min().shift(1).to_numpy(dtype=float)
        xlo = df["low"].rolling(exit_).min().shift(1).to_numpy(dtype=float)
        xhi = df["high"].rolling(exit_).max().shift(1).to_numpy(dtype=float)
        c = df["close"].to_numpy(dtype=float)
        pos, out = 0.0, np.zeros(len(df))
        for i in range(len(df)):
            if pos == 1 and c[i] < xlo[i]:
                pos = 0.0
            elif pos == -1 and c[i] > xhi[i]:
                pos = 0.0
            if pos == 0:
                if c[i] > hi[i]:
                    pos = 1.0
                elif shorts and c[i] < lo[i]:
                    pos = -1.0
            out[i] = pos
        return pd.Series(out, index=df.index)

    return f


def squeeze_breakout(n: int, squeeze_q: float, stop_atr: float, shorts: bool) -> Signal:
    """Volatility breakout: after a quiet stretch, follow the break; trail an ATR stop."""

    def f(df: pd.DataFrame) -> pd.Series:
        a = atr(df, 14).to_numpy(dtype=float)
        width = (df["high"].rolling(n).max() - df["low"].rolling(n).min()) / df["close"]
        thresh = width.rolling(300, min_periods=100).quantile(squeeze_q).shift(1)
        quiet = (width.shift(1) <= thresh).to_numpy(dtype=bool)
        hi = df["high"].rolling(n).max().shift(1).to_numpy(dtype=float)
        lo = df["low"].rolling(n).min().shift(1).to_numpy(dtype=float)
        c = df["close"].to_numpy(dtype=float)
        pos, stop, out = 0.0, 0.0, np.zeros(len(df))
        for i in range(len(df)):
            ai = float(a[i])
            if pos == 1:
                stop = max(stop, c[i] - stop_atr * ai)
                if c[i] < stop:
                    pos = 0.0
            elif pos == -1:
                stop = min(stop, c[i] + stop_atr * ai)
                if c[i] > stop:
                    pos = 0.0
            if pos == 0 and quiet[i] and not math.isnan(ai):
                if c[i] > hi[i]:
                    pos, stop = 1.0, c[i] - stop_atr * ai
                elif shorts and c[i] < lo[i]:
                    pos, stop = -1.0, c[i] + stop_atr * ai
            out[i] = pos
        return pd.Series(out, index=df.index)

    return f


def rsi_reversion(n: int, buy_below: float, sell_above: float, trend: int) -> Signal:
    """Buy oversold dips only in an uptrend (close above its long average); long only."""

    def f(df: pd.DataFrame) -> pd.Series:
        r = rsi(df["close"], n).to_numpy(dtype=float)
        up = (df["close"] > df["close"].rolling(trend).mean()).to_numpy(dtype=bool)
        pos, out = 0.0, np.zeros(len(df))
        for i in range(len(df)):
            if pos == 1 and (r[i] > sell_above or not up[i]):
                pos = 0.0
            elif pos == 0 and up[i] and r[i] < buy_below:
                pos = 1.0
            out[i] = pos
        return pd.Series(out, index=df.index)

    return f


def with_trend_filter(sig: Signal, trend: int) -> Signal:
    """Keep longs only above, shorts only below, the long moving average."""

    def f(df: pd.DataFrame) -> pd.Series:
        s = sig(df)
        above = df["close"] > df["close"].rolling(trend).mean()
        return s.where(((s > 0) & above) | ((s < 0) & ~above), 0.0)

    return f


# ---------- evaluation ----------


@dataclass(frozen=True)
class Result:
    """Metrics for one strategy on one market and window."""

    total_return: float
    buy_hold: float
    cagr: float
    max_drawdown: float
    sortino: float
    trades: int
    win_rate: float
    exposure: float


def simulate(df: pd.DataFrame, target: pd.Series, costs: Costs) -> pd.Series:
    """
    Bar-by-bar equity curve at 1x.

    Args:
        df (pd.DataFrame): Candles.
        target (pd.Series): Desired position after each bar's close.
        costs (Costs): Venue costs.

    Returns:
        pd.Series: Per-bar net returns.
    """
    # Reason: a position decided at close i is entered at the open of i+1 and earns from
    # that open; returns are open-to-open so no bar's close is used before it exists.
    pos = target.shift(1).fillna(0.0)
    o = df["open"]
    ret = (o.shift(-1) / o - 1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    fees = turnover * costs.fee_bps_per_side / 10_000
    borrow = pos.abs() * costs.borrow_pct_per_hour / 100 * 4
    return pos * ret - fees - borrow


def metrics(df: pd.DataFrame, target: pd.Series, costs: Costs) -> Result:
    """
    Summarize a strategy over the frame's window.

    Args:
        df (pd.DataFrame): Candles for the window.
        target (pd.Series): Positions for the window.
        costs (Costs): Venue costs.

    Returns:
        Result: Metrics.
    """
    r = simulate(df, target, costs)
    eq = (1 + r).cumprod()
    years = len(r) / BARS_PER_YEAR
    dn = r[r < 0].std() * math.sqrt(BARS_PER_YEAR)
    pos = target.shift(1).fillna(0.0)
    changes = pos.diff().fillna(pos)
    entries = changes[(changes != 0) & (pos != 0)].index
    trade_rets: list[float] = []
    growth = (1 + r).to_numpy(dtype=float)
    starts = [int(i) for i in np.flatnonzero(r.index.isin(entries))]
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else len(growth) - 1
        trade_rets.append(float(np.prod(growth[a : b + 1]) - 1))
    total = float(eq.iloc[-1] - 1)
    return Result(
        total_return=total,
        buy_hold=float(df["close"].iloc[-1] / df["open"].iloc[0] - 1),
        cagr=float(eq.iloc[-1] ** (1 / years) - 1) if years > 0 and eq.iloc[-1] > 0 else -1.0,
        max_drawdown=float((1 - eq / eq.cummax()).max()),
        sortino=float(r.mean() * BARS_PER_YEAR / dn) if dn and dn > 0 else 0.0,
        trades=len(entries),
        win_rate=float(np.mean([x > 0 for x in trade_rets])) if trade_rets else 0.0,
        exposure=float((pos != 0).mean()),
    )


def split(
    df: pd.DataFrame, holdout_days: int = 180, folds: int = 3, warmup: int = 300
) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    """
    Walk-forward folds and the sealed holdout.

    Args:
        df (pd.DataFrame): Full history.
        holdout_days (int): Days sealed at the end.
        folds (int): Number of equal research folds.
        warmup (int): Bars before the first fold reserved for indicator warm-up.

    Returns:
        tuple[list[tuple[int, int]], tuple[int, int]]: Fold (start, end) bar ranges and the
        holdout range; signals are computed on all bars up to each range's end.
    """
    h = holdout_days * 6
    usable = len(df) - h - warmup
    size = usable // folds
    rng = [(warmup + k * size, warmup + (k + 1) * size) for k in range(folds)]
    return rng, (len(df) - h, len(df))


def evaluate(df: pd.DataFrame, sig: Signal, costs: Costs, holdout: bool = False) -> list[Result]:
    """
    Results per research fold, or on the sealed holdout when ``holdout`` is True.

    Args:
        df (pd.DataFrame): Full history.
        sig (Signal): Strategy.
        costs (Costs): Venue costs.
        holdout (bool): Evaluate the sealed holdout instead of the folds.

    Returns:
        list[Result]: One result per fold (or one for the holdout).
    """
    target = sig(df)
    folds, hold = split(df)
    ranges = [hold] if holdout else folds
    return [metrics(df.iloc[a:b], target.iloc[a:b], costs) for a, b in ranges]


# ---------- EXP-2026-011 hypotheses (research pass 2026-11-10) ----------


def squeeze_plus(
    n: int = 42,
    squeeze_q: float = 0.25,
    stop_atr: float = 3.0,
    vol_mult: float = 0.0,
    trend: int = 0,
    time_stop: int = 0,
    shorts_below_trend: bool = False,
) -> Signal:
    """
    Volatility-squeeze breakout with optional filters, each one testable on its own.

    Args:
        n (int): Breakout lookback in bars.
        squeeze_q (float): Quiet means range width in this lowest quantile of 300 bars.
        stop_atr (float): Trailing stop distance in ATR(14).
        vol_mult (float): If > 0, the breakout bar's volume must exceed this multiple of
            its 20-bar average.
        trend (int): If > 0, longs only above (shorts only below) this moving average.
        time_stop (int): If > 0, exit when price has not moved 1 ATR in favor within this
            many bars.
        shorts_below_trend (bool): Allow shorts, only below the trend average.

    Returns:
        Signal: Position after each close.
    """

    def f(df: pd.DataFrame) -> pd.Series:
        a = atr(df, 14).to_numpy(dtype=float)
        width = (df["high"].rolling(n).max() - df["low"].rolling(n).min()) / df["close"]
        thresh = width.rolling(300, min_periods=100).quantile(squeeze_q).shift(1)
        quiet = (width.shift(1) <= thresh).to_numpy(dtype=bool)
        hi = df["high"].rolling(n).max().shift(1).to_numpy(dtype=float)
        lo = df["low"].rolling(n).min().shift(1).to_numpy(dtype=float)
        vol_ok = (
            (df["volume"] > vol_mult * df["volume"].rolling(20).mean().shift(1))
            if vol_mult > 0
            else pd.Series(True, index=df.index)
        ).to_numpy(dtype=bool)
        ma = df["close"].rolling(trend).mean().to_numpy(dtype=float) if trend else None
        c = df["close"].to_numpy(dtype=float)
        pos, stop, entry, entry_atr, age = 0.0, 0.0, 0.0, 0.0, 0
        out = np.zeros(len(df))
        for i in range(len(df)):
            ai = float(a[i])
            if pos != 0:
                age += 1
                if pos == 1:
                    stop = max(stop, c[i] - stop_atr * ai)
                    hit = c[i] < stop
                    moved = c[i] - entry >= entry_atr
                else:
                    stop = min(stop, c[i] + stop_atr * ai)
                    hit = c[i] > stop
                    moved = entry - c[i] >= entry_atr
                if hit or (time_stop and age >= time_stop and not moved):
                    pos = 0.0
            if pos == 0 and quiet[i] and vol_ok[i] and not math.isnan(ai):
                up = ma is None or (not math.isnan(ma[i]) and c[i] > ma[i])
                down = ma is not None and not math.isnan(ma[i]) and c[i] < ma[i]
                if c[i] > hi[i] and up:
                    pos, stop = 1.0, c[i] - stop_atr * ai
                elif shorts_below_trend and c[i] < lo[i] and down:
                    pos, stop = -1.0, c[i] + stop_atr * ai
                if pos != 0:
                    entry, entry_atr, age = c[i], ai, 0
            out[i] = pos
        return pd.Series(out, index=df.index)

    return f


def donchian_ensemble(windows: tuple[int, ...] = (20, 55, 120), shorts: bool = False) -> Signal:
    """Average of several Donchian breakout positions (exit window = entry / 2)."""

    def f(df: pd.DataFrame) -> pd.Series:
        parts = [donchian(w, max(w // 2, 5), shorts)(df) for w in windows]
        return sum(parts[1:], parts[0]) / len(parts)

    return f


def vol_target(sig: Signal, annual_target: float = 0.4, lookback: int = 42) -> Signal:
    """
    Scale a signal so its expected volatility is about ``annual_target``, never above 1x.

    The scale uses realized volatility up to the decision bar and is rounded to quarter
    steps so small volatility changes do not trigger trades.
    """

    def f(df: pd.DataFrame) -> pd.Series:
        rv = df["close"].pct_change().rolling(lookback).std() * math.sqrt(BARS_PER_YEAR)
        scale = (annual_target / rv).clip(upper=1.0)
        scale = (scale * 4).round() / 4
        return (sig(df) * scale).fillna(0.0)

    return f
