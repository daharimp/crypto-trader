"""Analytical benchmarks (R-20): cash, buy-and-hold BTC/ETH, and equal-weight."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trader.common.decimal_utils import round_down_to_step
from trader.data.snapshots import SnapshotBuilder
from trader.execution.costs import CostParams

EquityCurve = list[tuple[datetime, Decimal]]
BENCHMARKS = {
    "bm_cash": {},
    "bm_bh_btc": {"BTC-USD": Decimal(1)},
    "bm_bh_eth": {"ETH-USD": Decimal(1)},
    "bm_ew_btc_eth": {"BTC-USD": Decimal("0.5"), "ETH-USD": Decimal("0.5")},
}


def buy_and_hold(
    builder: SnapshotBuilder,
    weights: dict[str, Decimal],
    decision_times: list[datetime],
    capital: Decimal,
    costs: CostParams,
    steps: dict[str, Decimal],
) -> EquityCurve:
    """
    Buy at the first evaluated bar's next open (with fee and slippage) and hold.

    Args:
        builder (SnapshotBuilder): Candle access.
        weights (dict[str, Decimal]): Capital weight per instrument (empty = cash).
        decision_times (list[datetime]): Decision closes in the evaluation window.
        capital (Decimal): Starting capital.
        costs (CostParams): Cost scenario.
        steps (dict[str, Decimal]): Quantity step per instrument.

    Returns:
        EquityCurve: Equity marked at each decision close.
    """
    if not decision_times:
        return []
    first = decision_times[0]
    cash = capital
    qty: dict[str, Decimal] = {}
    for inst, w in sorted(weights.items()):
        bar = builder.bar_at_open(inst, first)
        if bar is None:
            continue
        price = min(max(bar.open * (1 + costs.slippage), bar.low), bar.high)
        alloc = capital * w
        q = round_down_to_step(alloc / (price * (1 + costs.fee_rate)), steps[inst])
        cost = q * price
        cash -= cost + cost * costs.fee_rate
        qty[inst] = q
    curve: EquityCurve = [(first, capital)]
    for t in decision_times[1:]:
        value = cash
        for inst, q in qty.items():
            last = builder.window(inst, t, 1)
            value += q * last[-1].close if last else Decimal(0)
        curve.append((t, value))
    return curve


def compute_benchmarks(
    builder: SnapshotBuilder,
    decision_times: list[datetime],
    capital: Decimal,
    costs: CostParams,
    steps: dict[str, Decimal],
) -> dict[str, EquityCurve]:
    """
    Compute all four M1 benchmarks.

    Args:
        builder (SnapshotBuilder): Candle access.
        decision_times (list[datetime]): Decision closes.
        capital (Decimal): Starting capital.
        costs (CostParams): Cost scenario.
        steps (dict[str, Decimal]): Quantity steps.

    Returns:
        dict[str, EquityCurve]: Curve per benchmark ID (benchmarks whose instruments are
        missing are omitted).
    """
    out: dict[str, EquityCurve] = {}
    for name, weights in BENCHMARKS.items():
        if all(i in builder.instruments for i in weights):
            out[name] = buy_and_hold(builder, weights, decision_times, capital, costs, steps)
    insts = builder.instruments
    if len(insts) > 2:
        # Reason: a strategy trading the whole universe must also be compared with simply
        # holding the whole universe, not only BTC and ETH.
        w = Decimal(1) / Decimal(len(insts))
        out["bm_ew_universe"] = buy_and_hold(
            builder, dict.fromkeys(insts, w), decision_times, capital, costs, steps
        )
    return out
