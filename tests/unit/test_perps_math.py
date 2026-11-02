"""Perps arithmetic (ADR-024)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from trader.perps.math import (
    PerpSide,
    is_liquidatable,
    leverage,
    liquidation_price,
    pnl_usd,
    remaining_collateral,
)


def test_pnl_long_and_short_are_mirror_images() -> None:
    assert pnl_usd(PerpSide.LONG, D(1000), D(100), D(110)) == D(100)
    assert pnl_usd(PerpSide.SHORT, D(1000), D(100), D(110)) == D(-100)
    assert pnl_usd(PerpSide.SHORT, D(1000), D(100), D(90)) == D(100)


def test_leverage_and_zero_collateral_fails() -> None:
    assert leverage(D(500), D(100)) == D(5)
    with pytest.raises(ValueError):
        leverage(D(500), D(0))


@pytest.mark.parametrize("side", [PerpSide.LONG, PerpSide.SHORT])
def test_liquidation_price_is_the_boundary(side: PerpSide) -> None:
    size, coll, entry, fee, mm = D(1000), D(200), D(100), D(6), D(20)
    liq = liquidation_price(side, size, coll, entry, fee, D(0), mm)
    # 5x: roughly a 20% adverse move minus fee and maintenance buffers.
    assert (D(80) < liq < D(81)) if side == PerpSide.LONG else (D(119) < liq < D(120))
    step = D("0.01") if side == PerpSide.LONG else D("-0.01")
    assert is_liquidatable(side, size, coll, entry, liq, fee, D(0), mm)
    assert not is_liquidatable(side, size, coll, entry, liq + step, fee, D(0), mm)


def test_borrow_fees_move_liquidation_closer() -> None:
    a = liquidation_price(PerpSide.LONG, D(1000), D(200), D(100), D(6), D(0), D(20))
    b = liquidation_price(PerpSide.LONG, D(1000), D(200), D(100), D(6), D(50), D(20))
    assert b > a


def test_remaining_collateral_counts_fees() -> None:
    rem = remaining_collateral(PerpSide.LONG, D(1000), D(200), D(100), D(100), D(6), D(1))
    assert rem == D(200) - D("0.6") - D(1)


def test_long_with_tiny_leverage_never_liquidates_above_zero() -> None:
    assert liquidation_price(PerpSide.LONG, D(100), D(200), D(100), D(6), D(0), D(20)) == D(0)
