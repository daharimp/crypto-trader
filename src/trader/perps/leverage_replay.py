"""Opening-leverage policies replayed on one market at constant capital (EXP-2026-015).

Research only; never imported by the trading pipeline or the paper session. It lives in the
paper-only perps package because that is the only place this vocabulary is allowed (T-46).

The position model mirrors the paper perps simulator (ADR-025, ADR-032): isolated
collateral, leverage fixed at the open, fees on size, liquidation checked against each
bar's adverse extreme with the whole collateral lost. Differences, on purpose: floats
instead of Decimal, constant collateral per trade (no compounding), and measured funding as
the holding cost (ADR-033).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BARS_PER_DAY = 6  # 4h candles
VOL_DAYS = 30  # ADR-032 window
MONTH = 30 * BARS_PER_DAY


@dataclass(frozen=True)
class Venue:
    """Costs and limits used by the replay (experiment inputs, not configuration)."""

    fee_bps: float = 7.0
    maintenance_bps: float = 20.0
    max_leverage: float = 25.0
    collateral_usd: float = 250.0
    borrow_per_bar: float = 0.0  # fraction of size charged to both sides each bar


@dataclass
class Replay:
    """Outcome of one replay."""

    pnl: np.ndarray  # dollars per bar
    funding: np.ndarray  # funding or borrow dollars paid per bar (negative = received)
    trades: list[dict[str, float]] = field(default_factory=list)
    liquidations: int = 0


def daily_move(close: pd.Series) -> pd.Series:
    """
    ADR-032's typical daily move: std of bar returns over 30 days, scaled to one day.

    Args:
        close (pd.Series): Closes, oldest first.

    Returns:
        pd.Series: Fraction per day at each bar (NaN until 30 days of returns exist).
    """
    n = VOL_DAYS * BARS_PER_DAY
    return close.pct_change().rolling(n).std() * math.sqrt(BARS_PER_DAY)


def assessed_leverage(move: pd.Series, buffer_moves: pd.Series | float, venue: Venue) -> pd.Series:
    """
    Leverage that keeps liquidation ``buffer_moves`` typical daily moves away (ADR-032).

    Args:
        move (pd.Series): Typical daily move as a fraction.
        buffer_moves (pd.Series | float): Daily moves of distance wanted.
        venue (Venue): Fee, maintenance, and the leverage ceiling.

    Returns:
        pd.Series: Leverage rounded down to 0.1, between 1 and the ceiling; NaN where the
        move is unknown or not positive (no trade opens there).
    """
    raw = 1 / (buffer_moves * move + (venue.fee_bps + venue.maintenance_bps) / 10_000)
    # Reason: the tiny epsilon keeps 12.0 from flooring to 11.9 through float error.
    lev = pd.Series(np.floor(raw * 10 + 1e-9) / 10, index=move.index)
    return lev.clip(lower=1.0, upper=venue.max_leverage).where(move > 0)


def trend_strength(close: pd.Series) -> pd.Series:
    """
    S1: size of the trailing 30-day return over a typical 30-day move.

    Args:
        close (pd.Series): Closes.

    Returns:
        pd.Series: Non-negative strength; 1 means a one-standard-deviation month.
    """
    return close.pct_change(MONTH).abs() / (daily_move(close) * math.sqrt(VOL_DAYS))


def agreement(close: pd.Series, direction: pd.Series) -> pd.Series:
    """
    S2: do the 3- and 12-month trailing returns point the same way as the trade?

    Args:
        close (pd.Series): Closes.
        direction (pd.Series): Trade direction (+1 long, -1 short, 0 flat).

    Returns:
        pd.Series: +1 both agree, -1 both disagree, 0 otherwise or unknown.
    """
    s3 = np.sign(close.pct_change(3 * MONTH))
    s12 = np.sign(close.pct_change(12 * MONTH))
    both_for = (s3 == direction) & (s12 == direction) & (direction != 0)
    both_against = (s3 == -direction) & (s12 == -direction) & (direction != 0)
    return pd.Series(np.where(both_for, 1.0, np.where(both_against, -1.0, 0.0)), index=close.index)


def buffer_for(
    strong: pd.Series, weak: pd.Series, tilt: bool, base: float = 4.0, step: float = 1.0
) -> pd.Series:
    """
    Daily moves of liquidation distance: fewer when strong (and more when weak if ``tilt``).

    Args:
        strong (pd.Series): Boolean, the signal is strong.
        weak (pd.Series): Boolean, the signal is weak.
        tilt (bool): Also widen the buffer when weak.
        base (float): The owner's buffer (UD-26).
        step (float): Experiment step around it.

    Returns:
        pd.Series: Buffer per bar.
    """
    out = pd.Series(base, index=strong.index)
    out[strong] = base - step
    if tilt:
        out[weak & ~strong] = base + step
    return out


def replay(
    df: pd.DataFrame,
    direction: pd.Series,
    lev: pd.Series,
    bar_funding: pd.Series,
    venue: Venue,
    start: int = 0,
    stop: int | None = None,
) -> Replay:
    """
    Replay one market: decide at a close, fill at the next open, check liquidation each bar.

    Args:
        df (pd.DataFrame): Candles with open, high, low, close.
        direction (pd.Series): Desired side after each close (+1, -1, 0).
        lev (pd.Series): Opening leverage assessed at each close (NaN: do not open).
        bar_funding (pd.Series): Funding per bar as a fraction of size, positive when
            longs pay shorts (NaN counts as nothing charged; the caller reports those).
        venue (Venue): Costs and limits.
        start (int): First bar of the evaluation window (the account starts flat).
        stop (int | None): One past the last bar.

    Returns:
        Replay: Dollar P&L per bar in the window, funding paid, trades, and liquidations.

    Raises:
        ValueError: If the inputs are not on the candles' index.
    """
    for s in (direction, lev, bar_funding):
        if not s.index.equals(df.index):
            raise ValueError("inputs must use the candles' index")
    stop = len(df) if stop is None else stop
    o, hi, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    want = direction.to_numpy(dtype=float)
    levs = lev.to_numpy(dtype=float)
    fund = np.nan_to_num(bar_funding.to_numpy(dtype=float))
    fee, maint, coll = venue.fee_bps / 10_000, venue.maintenance_bps / 10_000, venue.collateral_usd
    out = Replay(np.zeros(stop - start), np.zeros(stop - start))
    side = size = entry = paid = value = 0.0
    trade: dict[str, float] = {}

    def finish(result: float, liquidated: bool) -> None:
        trade.update(pnl=trade["pnl"] + result, liquidated=float(liquidated))
        out.trades.append(dict(trade))

    for i in range(start, stop):
        k = i - start
        bar = 0.0
        target = want[i - 1] if i > start else 0.0
        if side != 0.0 and side != target:
            # Close at this open: collateral plus price P&L, less the closing fee and funding.
            left = max(coll + side * size * (o[i] / entry - 1) - size * fee - paid, 0.0)
            bar += left - value
            finish(left - value, False)
            side = 0.0
        if side == 0.0 and target != 0.0 and i > start and levs[i - 1] >= 1.0:
            side, size, entry, paid = target, coll * levs[i - 1], o[i], 0.0
            # Reason: like the simulator's equity, an open position is valued as if closed
            # now, so the closing fee shows at the open and the opening fee is paid in cash.
            value = coll - size * fee
            bar -= 2 * size * fee
            trade = {"bar": float(i), "side": side, "lev": levs[i - 1], "size": size}
            trade["pnl"] = -2 * size * fee
        if side != 0.0:
            cost = side * size * fund[i] + size * venue.borrow_per_bar
            paid += cost
            out.funding[k] = cost
            adverse = lo[i] if side > 0 else hi[i]
            worst = coll + side * size * (adverse / entry - 1) - size * fee - paid
            if worst <= size * maint:
                # Reason: conservative paper rule, the whole collateral is lost.
                bar += -value
                finish(-value, True)
                out.liquidations += 1
                side = 0.0
            else:
                now = max(coll + side * size * (c[i] / entry - 1) - size * fee - paid, 0.0)
                bar += now - value
                trade["pnl"] += now - value
                value = now
        out.pnl[k] = bar
    if side != 0.0:
        finish(0.0, False)
    return out
