"""Order-based simulators for retail bot styles: grid, DCA with safety orders, plain DCA.

Research only (ADR-028, EXP-2026-012). Never imported by the trading pipeline. These bots
rest limit orders, so a close-to-close signal model would miss their fills; instead each
hourly bar is walked along an assumed intrabar path (open, nearer extreme, farther extreme,
close) and every order level the path crosses fills at its own price.

Accounting is long-only and unleveraged: buys never spend more cash than is held and sells
never sell more coin than is held. Equity is cash plus coin marked at each bar's close.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BotCosts:
    """Fee per side, in basis points of fill notional."""

    name: str
    maker_bps: float  # resting limit orders
    taker_bps: float  # market orders (includes slippage)


# Reason: Kraken Pro entry tier as last known (0.25% maker, 0.40% taker + 0.10% slippage,
# matching configs/costs/base.yaml); Pionex advertises 0.05% for both. Verify both.
KRAKEN = BotCosts("kraken", 25.0, 50.0)
PIONEX = BotCosts("pionex", 5.0, 10.0)


def path(o: float, h: float, lo: float, c: float) -> list[float]:
    """
    Assumed intrabar price path: the extreme nearer the open is visited first.

    Args:
        o (float): Open.
        h (float): High.
        lo (float): Low.
        c (float): Close.

    Returns:
        list[float]: Four way-points.
    """
    return [o, lo, h, c] if (o - lo) <= (h - o) else [o, h, lo, c]


def segments(df: pd.DataFrame) -> Iterator[tuple[int, float, float]]:
    """Yield (bar index, from price, to price) for each monotone leg of each bar."""
    arr = df[["open", "high", "low", "close"]].to_numpy(dtype=float)
    for i, (o, h, lo, c) in enumerate(arr):
        pts = path(o, h, lo, c)
        for a, b in zip(pts, pts[1:], strict=False):
            if a != b:
                yield i, a, b


@dataclass
class Book:
    """Cash, coin, fees, and fill count for one simulation."""

    cash: float
    coin: float = 0.0
    fees: float = 0.0
    fills: int = 0

    def buy(self, usd: float, price: float, bps: float) -> None:
        """Spend up to ``usd`` (fee included) at ``price``."""
        usd = min(usd, self.cash)
        if usd <= 0:
            return
        fee = usd * bps / 10_000
        self.cash -= usd
        self.coin += (usd - fee) / price
        self.fees += fee
        self.fills += 1

    def sell(self, qty: float, price: float, bps: float) -> None:
        """Sell up to ``qty`` coin at ``price``."""
        qty = min(qty, self.coin)
        if qty <= 0:
            return
        gross = qty * price
        fee = gross * bps / 10_000
        self.coin -= qty
        self.cash += gross - fee
        self.fees += fee
        self.fills += 1


@dataclass(frozen=True)
class BotResult:
    """Outcome of one bot on one window, in dollars."""

    start: float
    end: float
    buy_hold_end: float
    max_drawdown: float  # fraction of peak equity
    fees: float
    fills: int
    exposure: float  # average fraction of equity in coin

    @property
    def total_return(self) -> float:
        """End over start, minus one."""
        return self.end / self.start - 1


def _check(df: pd.DataFrame, capital: float) -> None:
    """Reject an empty window or non-positive capital."""
    if df.empty or capital <= 0:
        raise ValueError("need at least one bar and positive capital")


def _result(
    df: pd.DataFrame, start: float, eq: np.ndarray, coin_val: np.ndarray, book: Book
) -> BotResult:
    peak = np.maximum.accumulate(eq)
    bh = start * float(df["close"].iloc[-1] / df["open"].iloc[0])
    return BotResult(
        start=start,
        end=float(eq[-1]),
        buy_hold_end=bh,
        max_drawdown=float(np.max(1 - eq / peak)),
        fees=book.fees,
        fills=book.fills,
        exposure=float(np.mean(coin_val / eq)),
    )


def grid_bot(
    df: pd.DataFrame,
    capital: float,
    costs: BotCosts,
    width: float,
    levels: int = 20,
    rebuild_hours: int = 0,
) -> BotResult:
    """
    Arithmetic spot grid (Pionex style).

    The range is ``price * (1 - width)`` to ``price * (1 + width)`` with ``levels`` equal
    gaps, each worth ``equity / levels``. On start the bot buys, at market, the coin for
    every gap above the price (as Pionex does). Falling through a gap's lower line buys it;
    rising through its upper line sells it, so each round trip earns one gap. Outside the
    range it stops. With ``rebuild_hours`` > 0 it sells everything at market and rebuilds
    around the current price every that many hours.

    Args:
        df (pd.DataFrame): Hourly candles for the window.
        capital (float): Starting USD.
        costs (BotCosts): Fees.
        width (float): Half-width of the range as a fraction of the start price.
        levels (int): Number of gaps.
        rebuild_hours (int): Rebuild period in bars; 0 keeps one fixed range.

    Returns:
        BotResult: Outcome.

    Raises:
        ValueError: If the window is empty or a setting is out of range.
    """
    _check(df, capital)
    if not 0 < width < 1 or levels < 1 or rebuild_hours < 0:
        raise ValueError("grid needs 0 < width < 1, levels >= 1, rebuild_hours >= 0")
    book = Book(capital)
    close = df["close"].to_numpy(dtype=float)
    lines = np.zeros(levels + 1)
    held = np.zeros(levels, dtype=bool)
    qty = np.zeros(levels)

    def build(price: float) -> None:
        nonlocal lines
        if book.coin > 0:
            book.sell(book.coin, price, costs.taker_bps)
        lines = np.linspace(price * (1 - width), price * (1 + width), levels + 1)
        per_gap = book.cash / levels
        held[:] = False
        for j in range(levels):
            qty[j] = per_gap / lines[j]
            # Reason: a gap whose lower line is at or above the price sits wholly above it.
            if lines[j] >= price * (1 - 1e-12):
                before = book.coin
                book.buy(qty[j] * price / (1 - costs.taker_bps / 10_000), price, costs.taker_bps)
                qty[j] = book.coin - before
                held[j] = True

    eq = np.zeros(len(df))
    coin_val = np.zeros(len(df))
    build(float(df["open"].iloc[0]))
    last_bar = 0
    for i, a, b in segments(df):
        while last_bar < i:
            eq[last_bar] = book.cash + book.coin * close[last_bar]
            coin_val[last_bar] = book.coin * close[last_bar]
            last_bar += 1
            if rebuild_hours and last_bar % rebuild_hours == 0:
                build(float(df["open"].iloc[last_bar]))
        lo, hi = min(a, b), max(a, b)
        # Reason: process crossings in the order the price meets them along the leg.
        order = range(levels) if b > a else range(levels - 1, -1, -1)
        for j in order:
            if b < a and not held[j] and lo <= lines[j] < hi:
                before = book.coin
                book.buy(qty[j] * lines[j], lines[j], costs.maker_bps)
                qty[j] = book.coin - before
                held[j] = qty[j] > 0
            elif b > a and held[j] and lo < lines[j + 1] <= hi:
                book.sell(qty[j], lines[j + 1], costs.maker_bps)
                held[j] = False
    while last_bar < len(df):
        eq[last_bar] = book.cash + book.coin * close[last_bar]
        coin_val[last_bar] = book.coin * close[last_bar]
        last_bar += 1
    return _result(df, capital, eq, coin_val, book)


def dca_bot(
    df: pd.DataFrame,
    capital: float,
    costs: BotCosts,
    safety_orders: int = 5,
    step: float = 0.02,
    volume_scale: float = 1.5,
    take_profit: float = 0.015,
) -> BotResult:
    """
    DCA bot with safety orders (Cryptohopper / 3Commas style).

    Buys a base order at market, rests safety orders ``step``, ``2*step``, ... below the
    base price, each ``volume_scale`` times the previous, and sells everything when price
    reaches ``take_profit`` above the average cost; then starts again. Order sizes are set
    so the base plus all safety orders use exactly the current cash, so it never borrows.

    Args:
        df (pd.DataFrame): Hourly candles for the window.
        capital (float): Starting USD.
        costs (BotCosts): Fees.
        safety_orders (int): Number of safety orders.
        step (float): Price step between safety orders.
        volume_scale (float): Size multiple from one safety order to the next.
        take_profit (float): Exit above the average entry price.

    Returns:
        BotResult: Outcome.
    """
    _check(df, capital)
    if safety_orders < 0 or not 0 < step < 1 or volume_scale <= 0 or take_profit <= 0:
        raise ValueError(
            "dca needs safety_orders >= 0, 0 < step < 1, positive scale and take-profit"
        )
    book = Book(capital)
    close = df["close"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    units = sum(volume_scale**k for k in range(safety_orders + 1))
    state: dict[str, float] = {}
    pending: list[tuple[float, float]] = []

    def start(price: float) -> None:
        unit = book.cash / units
        spent = book.cash
        book.buy(unit, price, costs.taker_bps)
        state["cost"] = spent - book.cash
        pending[:] = [
            (price * (1 - step * k), unit * volume_scale**k) for k in range(1, safety_orders + 1)
        ]

    eq = np.zeros(len(df))
    coin_val = np.zeros(len(df))
    start(float(opens[0]))
    last_bar = 0
    restart = False
    for i, a, b in segments(df):
        while last_bar < i:
            eq[last_bar] = book.cash + book.coin * close[last_bar]
            coin_val[last_bar] = book.coin * close[last_bar]
            last_bar += 1
            if restart:
                start(float(opens[last_bar]))
                restart = False
        if restart:
            continue
        if b < a:
            for level, usd in list(pending):
                if b <= level < a:
                    before = book.cash
                    book.buy(usd, level, costs.maker_bps)
                    state["cost"] += before - book.cash
                    pending.remove((level, usd))
        elif book.coin > 0:
            target = state["cost"] / book.coin * (1 + take_profit)
            if a < target <= b:
                book.sell(book.coin, target, costs.maker_bps)
                pending.clear()
                restart = True
    while last_bar < len(df):
        eq[last_bar] = book.cash + book.coin * close[last_bar]
        coin_val[last_bar] = book.coin * close[last_bar]
        last_bar += 1
    return _result(df, capital, eq, coin_val, book)


def plain_dca(
    df: pd.DataFrame, capital: float, costs: BotCosts, every_hours: int = 168
) -> BotResult:
    """
    Buy an equal dollar amount at market every ``every_hours`` bars and never sell.

    Args:
        df (pd.DataFrame): Hourly candles for the window.
        capital (float): Starting USD, spread evenly over the window.
        costs (BotCosts): Fees.
        every_hours (int): Bars between buys (168 = weekly).

    Returns:
        BotResult: Outcome.
    """
    _check(df, capital)
    if every_hours < 1:
        raise ValueError("every_hours must be >= 1")
    book = Book(capital)
    opens = df["open"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    buys = list(range(0, len(df), every_hours))
    each = capital / len(buys)
    eq = np.zeros(len(df))
    coin_val = np.zeros(len(df))
    for i in range(len(df)):
        if i in buys:
            book.buy(each, float(opens[i]), costs.taker_bps)
        coin_val[i] = book.coin * close[i]
        eq[i] = book.cash + coin_val[i]
    return _result(df, capital, eq, coin_val, book)
