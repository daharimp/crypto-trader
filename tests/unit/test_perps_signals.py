"""Named paper perps signals (ADR-035): momentum, and the consensus of two rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trader.perps.math import PerpSide
from trader.perps.signals import DEFAULT_SIGNAL, SIGNAL_NAMES, make_signal, tsmom


def _series(*legs: tuple[int, float], start: float = 100.0) -> list[Decimal]:
    """Closes built from (bars, per-bar growth) legs."""
    out, p = [], start
    for bars, growth in legs:
        for _ in range(bars):
            p *= growth
            out.append(Decimal(str(p)))
    return out


def test_tsmom_follows_the_sign_of_the_lookback_return() -> None:
    up, down = _series((200, 1.002)), _series((200, 0.998))
    assert tsmom(up, 180) == PerpSide.LONG and tsmom(down, 180) == PerpSide.SHORT
    assert tsmom(up[:180], 180) is None  # needs lookback + 1 closes
    assert tsmom([Decimal(5)] * 200, 180) is None  # no change
    assert tsmom(up, 0) is None


def test_consensus_takes_a_side_only_when_both_rules_agree() -> None:
    consensus = make_signal("consensus_sma_tsmom", 6)
    assert consensus(_series((200, 1.002))) == PerpSide.LONG
    assert consensus(_series((200, 0.998))) == PerpSide.SHORT
    # A long fall, then a short sharp bounce: the 20/50 averages turn up while the price is
    # still below its level 30 days ago, so the rules disagree and the answer is flat.
    mixed = _series((200, 0.995), (30, 1.01))
    assert make_signal("sma_stance_20_50", 6)(mixed) == PerpSide.LONG
    assert make_signal("tsmom_30d", 6)(mixed) == PerpSide.SHORT
    assert consensus(mixed) is None
    # Warming up: the averages are ready but 30 days of history are not.
    assert consensus(_series((100, 1.002))) is None


def test_signals_do_not_look_ahead() -> None:
    closes = _series((200, 0.995), (60, 1.01), (60, 0.99))
    for name in SIGNAL_NAMES:
        sig = make_signal(name, 6)
        full = [sig(closes[: i + 1]) for i in range(len(closes))]
        # Extending the history never changes an earlier answer.
        assert full[:250] == [sig(closes[: i + 1]) for i in range(250)]


def test_timeframe_sets_the_month_length_and_unknown_names_fail() -> None:
    closes = _series((300, 1.001))
    assert make_signal("tsmom_30d", 6)(closes) == PerpSide.LONG  # 180 bars back
    assert make_signal("tsmom_30d", 24)(closes) is None  # 720 bars back: not enough history
    assert DEFAULT_SIGNAL == "tsmom_30d" and DEFAULT_SIGNAL in SIGNAL_NAMES
    with pytest.raises(ValueError, match="unknown signal"):
        make_signal("nope", 6)
