"""Performance metrics (365-day year, risk-free 0; handoff §7.12)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from trader.common.decimal_utils import fmt_ratio, fmt_usd
from trader.portfolio.ledger import ClosedTrade

DAYS_PER_YEAR = 365


def _f(x: float) -> Decimal:
    """
    Convert a float result to Decimal via text (reporting only).

    Args:
        x (float): Value.

    Returns:
        Decimal: Value (0 for non-finite).
    """
    return Decimal(repr(x)) if math.isfinite(x) else Decimal(0)


def daily_equity(curve: Sequence[tuple[datetime, Decimal]]) -> list[Decimal]:
    """
    Equity at 00:00 UTC marks (plus the first mark).

    Args:
        curve (Sequence[tuple[datetime, Decimal]]): Equity marks.

    Returns:
        list[Decimal]: Daily equity series.
    """
    if not curve:
        return []
    out = [curve[0][1]]
    out += [e for t, e in curve[1:] if t.hour == 0 and t.minute == 0]
    return out


def max_drawdown(values: Sequence[Decimal]) -> Decimal:
    """
    Maximum peak-to-trough drawdown as a fraction.

    Args:
        values (Sequence[Decimal]): Equity values.

    Returns:
        Decimal: Max drawdown (0..1).
    """
    peak, mdd = Decimal(0), Decimal(0)
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def compute_metrics(
    curve: Sequence[tuple[datetime, Decimal]],
    trades: Sequence[ClosedTrade] = (),
    exposure_pct: Sequence[Decimal] = (),
    fees: Decimal = Decimal(0),
    slippage: Decimal = Decimal(0),
) -> dict[str, Any]:
    """
    Compute the report metrics for one equity curve.

    Args:
        curve (Sequence[tuple[datetime, Decimal]]): Equity marks at decision closes.
        trades (Sequence[ClosedTrade]): Closed trades (strategy only).
        exposure_pct (Sequence[Decimal]): Exposure % at each mark.
        fees (Decimal): Total fees.
        slippage (Decimal): Total slippage cost.

    Returns:
        dict[str, Any]: Metrics serialized as strings.
    """
    if not curve:
        return {"total_return": fmt_ratio(Decimal(0)), "final_equity_usd": fmt_usd(Decimal(0))}
    start, end = curve[0][1], curve[-1][1]
    total = end / start - 1 if start else Decimal(0)
    days = max((curve[-1][0] - curve[0][0]).total_seconds() / 86400, 1e-9)
    cagr = (
        _f((float(end / start)) ** (DAYS_PER_YEAR / days) - 1) if start and end > 0 else Decimal(-1)
    )
    daily = daily_equity(curve)
    rets = [float(b / a - 1) for a, b in zip(daily, daily[1:], strict=False) if a]
    n = len(rets)
    mean = sum(rets) / n if n else 0.0
    var = sum((r - mean) ** 2 for r in rets) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / n) if n else 0.0
    ann = math.sqrt(DAYS_PER_YEAR)
    mdd = max_drawdown([e for _, e in curve])
    wins = [t for t in trades if t.pnl_usd > 0]
    gross_win = sum((t.pnl_usd for t in wins), Decimal(0))
    gross_loss = -sum((t.pnl_usd for t in trades if t.pnl_usd < 0), Decimal(0))
    hold_h = [(t.closed_at - t.opened_at).total_seconds() / 3600 for t in trades]
    return {
        "start_equity_usd": fmt_usd(start),
        "final_equity_usd": fmt_usd(end),
        "total_return": fmt_ratio(total),
        "cagr": fmt_ratio(cagr),
        "max_drawdown": fmt_ratio(mdd),
        "volatility": fmt_ratio(_f(sd * ann)),
        "sharpe_like": fmt_ratio(_f(mean / sd * ann) if sd else Decimal(0)),
        "sortino_like": fmt_ratio(_f(mean / downside * ann) if downside else Decimal(0)),
        "calmar": fmt_ratio(cagr / mdd if mdd else Decimal(0)),
        "closed_trades": len(trades),
        "win_rate": fmt_ratio(Decimal(len(wins)) / len(trades) if trades else Decimal(0)),
        "profit_factor": fmt_ratio(gross_win / gross_loss if gross_loss else Decimal(0)),
        "avg_holding_hours": fmt_ratio(_f(sum(hold_h) / len(hold_h)) if hold_h else Decimal(0)),
        "avg_exposure_pct": fmt_ratio(
            sum(exposure_pct, Decimal(0)) / len(exposure_pct) if exposure_pct else Decimal(0)
        ),
        "fees_usd": fmt_usd(fees),
        "slippage_cost_usd": fmt_usd(slippage),
    }
