"""Replay a perps paper account over historical candles (ADR-025).

Research baseline signal ``sma_stance``: long while SMA(fast) > SMA(slow), short while
below, flat during warm-up. Decisions use closes up to bar *i*; orders fill at the open of
bar *i+1* (no look-ahead). Liquidation is checked against each bar's adverse extreme (the
low for longs, the high for shorts), which is conservative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trader.features.pipeline import sma

from .math import PerpSide
from .params import PerpsParams
from .simulator import PaperPerpsAccount


@dataclass(frozen=True)
class Bar:
    """One candle."""

    open_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class PerpsBacktestResult:
    """Outcome of a replay."""

    start_equity_usd: Decimal
    end_equity_usd: Decimal
    max_drawdown_pct: Decimal
    trades: int
    liquidations: int
    rejections: dict[str, int]
    fees_paid_usd: Decimal
    events: list[dict[str, Any]]


def sma_stance(closes: list[Decimal], fast: int, slow: int) -> PerpSide | None:
    """
    Direction from two moving averages.

    Args:
        closes (list[Decimal]): Closes up to the decision bar.
        fast (int): Fast period.
        slow (int): Slow period.

    Returns:
        PerpSide | None: Long, short, or None during warm-up or when equal.
    """
    f, s = sma(closes, fast), sma(closes, slow)
    if f is None or s is None or f == s:
        return None
    return PerpSide.LONG if f > s else PerpSide.SHORT


def run_perps_backtest(
    params: PerpsParams,
    bars: dict[str, list[Bar]],
    fast: int = 20,
    slow: int = 50,
    allow_shorts: bool = True,
) -> PerpsBacktestResult:
    """
    Replay the ``sma_stance`` signal through the paper account.

    Args:
        params (PerpsParams): Resolved parameters.
        bars (dict[str, list[Bar]]): Candles per market, ascending.
        fast (int): Fast SMA period.
        slow (int): Slow SMA period.
        allow_shorts (bool): If False, short signals mean flat.

    Returns:
        PerpsBacktestResult: Summary and events.

    Raises:
        ValueError: If no timestamps are shared by every market.
    """
    if fast >= slow:
        raise ValueError("fast must be shorter than slow")
    by_time = {m: {b.open_time_utc: b for b in bs} for m, bs in bars.items()}
    times = sorted(set.intersection(*(set(d) for d in by_time.values())))
    if len(times) < 2:
        raise ValueError("markets share fewer than two timestamps")
    acct = PaperPerpsAccount.start(params, times[0])
    closes: dict[str, list[Decimal]] = {m: [] for m in bars}
    start = acct.cash_usd
    peak, max_dd = start, Decimal(0)
    pending: dict[str, PerpSide | None] = {}
    for t in times:
        row = {m: by_time[m][t] for m in bars}
        opens = {m: b.open for m, b in row.items()}
        for m, target in pending.items():
            acct.apply_signal(m, target, opens, t)
        pending = {}
        adverse = {
            m: (row[m].low if p.side == PerpSide.LONG else row[m].high)
            for m, p in acct.positions.items()
        }
        acct.mark({**{m: b.close for m, b in row.items()}, **adverse}, t)
        marks = {m: b.close for m, b in row.items()}
        eq = acct.equity(marks)
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100)
        for m, b in row.items():
            closes[m].append(b.close)
            side = sma_stance(closes[m], fast, slow)
            pending[m] = None if side == PerpSide.SHORT and not allow_shorts else side
    final = {m: by_time[m][times[-1]].close for m in bars}
    for m in list(acct.positions):
        acct.close(m, final, times[-1], reason="END_OF_BACKTEST")
    rejections: dict[str, int] = {}
    for e in acct.events:
        for r in e.get("reasons", []):
            rejections[r] = rejections.get(r, 0) + 1
    return PerpsBacktestResult(
        start_equity_usd=start,
        end_equity_usd=acct.cash_usd,
        max_drawdown_pct=max_dd.quantize(Decimal("0.01")),
        trades=sum(1 for e in acct.events if e["event"] == "OPENED"),
        liquidations=sum(1 for e in acct.events if e["event"] == "LIQUIDATED"),
        rejections=rejections,
        fees_paid_usd=acct.fees_paid_usd,
        events=acct.events,
    )
