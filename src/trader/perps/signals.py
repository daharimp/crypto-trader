"""Named signals for the paper perps session (ADR-035). Each says long, short, or flat only.

Sizing and every limit stay in the risk code. A signal reads closes up to the decision bar,
so it never looks ahead.

* ``sma_stance_20_50``: long while the 20-bar average is above the 50-bar average, else short.
* ``tsmom_30d``: long if the price is above its level 30 days ago, short if below.
* ``consensus_sma_tsmom``: takes a side only when the two rules above agree; flat when they
  disagree or either is still warming up.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .backtest import sma_stance
from .math import PerpSide

Signal = Callable[[list[Decimal]], PerpSide | None]
MOMENTUM_DAYS = 30
DEFAULT_SIGNAL = "consensus_sma_tsmom"


def tsmom(closes: list[Decimal], lookback_bars: int) -> PerpSide | None:
    """
    Time-series momentum: the direction of the return over ``lookback_bars``.

    Args:
        closes (list[Decimal]): Closes up to the decision bar.
        lookback_bars (int): Bars to look back.

    Returns:
        PerpSide | None: Long, short, or None with too little history or no change.
    """
    if lookback_bars < 1 or len(closes) <= lookback_bars:
        return None
    now, then = closes[-1], closes[-1 - lookback_bars]
    if now == then:
        return None
    return PerpSide.LONG if now > then else PerpSide.SHORT


def make_signal(name: str, bars_per_day: int) -> Signal:
    """
    Build a named signal for a timeframe.

    Args:
        name (str): One of ``SIGNAL_NAMES``.
        bars_per_day (int): Bars in a day (6 for 4h candles, 24 for 1h).

    Returns:
        Signal: The signal function.

    Raises:
        ValueError: For an unknown name.
    """
    month = MOMENTUM_DAYS * bars_per_day

    def sma(closes: list[Decimal]) -> PerpSide | None:
        return sma_stance(closes, 20, 50)

    def momentum(closes: list[Decimal]) -> PerpSide | None:
        return tsmom(closes, month)

    def consensus(closes: list[Decimal]) -> PerpSide | None:
        a, b = sma(closes), momentum(closes)
        # Reason: act only on agreement; disagreement or a missing vote means stay out.
        return a if a is not None and a == b else None

    table: dict[str, Signal] = {
        "sma_stance_20_50": sma,
        "tsmom_30d": momentum,
        "consensus_sma_tsmom": consensus,
    }
    if name not in table:
        raise ValueError(f"unknown signal {name!r}; choose one of {sorted(table)}")
    return table[name]


SIGNAL_NAMES = ("sma_stance_20_50", "tsmom_30d", "consensus_sma_tsmom")
