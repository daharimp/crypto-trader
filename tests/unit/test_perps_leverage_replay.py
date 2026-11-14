"""Opening-leverage replay for research (EXP-2026-015): sizing, liquidation, no look-ahead."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from tests.perps_support import T0, fixture_params
from trader.perps.leverage_replay import (
    Venue,
    agreement,
    assessed_leverage,
    buffer_for,
    daily_move,
    replay,
    trend_strength,
)
from trader.perps.math import PerpSide
from trader.perps.simulator import PaperPerpsAccount

VENUE = Venue()


def _frame(opens: list[float], lows: list[float] | None = None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(opens), freq="4h", tz="UTC")
    o = np.array(opens, dtype=float)
    c = np.r_[o[1:], o[-1]]
    lo = np.minimum(o, c) if lows is None else np.array(lows, dtype=float)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": lo, "close": c}, index=idx)


def _const(df: pd.DataFrame, x: float) -> pd.Series:
    return pd.Series(x, index=df.index)


def test_assessed_leverage_matches_the_adr_032_examples() -> None:
    move = pd.Series([0.012, 0.009, 0.06, 0.02])
    lev = assessed_leverage(move, 4.0, VENUE)
    assert list(lev) == [19.7, 25.0, 4.1, 12.0]


def test_assessed_leverage_is_unknown_without_volatility_and_never_below_one() -> None:
    lev = assessed_leverage(pd.Series([np.nan, 0.0, 0.9]), 4.0, VENUE)
    assert np.isnan(lev.iloc[0]) and np.isnan(lev.iloc[1]) and lev.iloc[2] == 1.0


def test_stronger_signal_means_a_smaller_buffer_and_more_leverage() -> None:
    strong = pd.Series([True, False, False])
    weak = pd.Series([False, True, False])
    assert list(buffer_for(strong, weak, tilt=False)) == [3.0, 4.0, 4.0]
    assert list(buffer_for(strong, weak, tilt=True)) == [3.0, 5.0, 4.0]
    lev = assessed_leverage(pd.Series(0.02, index=range(3)), buffer_for(strong, weak, True), VENUE)
    assert lev.iloc[0] > lev.iloc[2] > lev.iloc[1]


def test_daily_move_and_strength_use_only_past_closes() -> None:
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 2600))))
    changed = close.copy()
    changed.iloc[2400:] *= 3
    direction = pd.Series(1.0, index=close.index)
    for f in (daily_move, trend_strength, lambda s: agreement(s, direction)):
        pd.testing.assert_series_equal(f(close).iloc[:2400], f(changed).iloc[:2400])
    assert daily_move(close).iloc[:180].isna().all()


def test_agreement_is_plus_one_minus_one_or_zero() -> None:
    up = pd.Series(np.linspace(100, 300, 2400))
    assert agreement(up, pd.Series(1.0, index=up.index)).iloc[-1] == 1.0
    assert agreement(up, pd.Series(-1.0, index=up.index)).iloc[-1] == -1.0
    assert agreement(up, pd.Series(0.0, index=up.index)).iloc[-1] == 0.0
    assert agreement(up, pd.Series(1.0, index=up.index)).iloc[100] == 0.0


def test_profitable_long_earns_size_times_move_less_both_fees() -> None:
    df = _frame([100, 100, 110, 110])
    direction = pd.Series([1.0, 0.0, 0.0, 0.0], index=df.index)
    r = replay(df, direction, _const(df, 10.0), _const(df, 0.0), VENUE)
    size = 250 * 10
    assert r.pnl.sum() == pytest.approx(size * 0.10 - 2 * size * 0.0007)
    assert r.liquidations == 0 and len(r.trades) == 1
    assert r.trades[0]["pnl"] == pytest.approx(r.pnl.sum())
    # Nothing is held on bar 0: the decision at its close fills at the next open.
    assert r.pnl[0] == 0.0


def test_adverse_wick_liquidates_and_loses_the_whole_collateral() -> None:
    df = _frame([100, 100, 100, 100], lows=[100, 89, 100, 100])
    direction = pd.Series([1.0, 0.0, 0.0, 0.0], index=df.index)
    r = replay(df, direction, _const(df, 10.0), _const(df, 0.0), VENUE)
    assert r.liquidations == 1 and r.trades[0]["liquidated"] == 1.0
    assert r.pnl.sum() == pytest.approx(-250 - 2500 * 0.0007)


def test_lower_leverage_survives_the_same_wick_and_a_signal_reopens_after_liquidation() -> None:
    df = _frame([100, 100, 100, 100, 100], lows=[100, 89, 100, 100, 100])
    direction = _const(df, 1.0)
    assert replay(df, direction, _const(df, 5.0), _const(df, 0.0), VENUE).liquidations == 0
    r = replay(df, direction, _const(df, 10.0), _const(df, 0.0), VENUE)
    assert r.liquidations == 1 and len(r.trades) == 2


def test_long_pays_positive_funding_and_short_receives_it() -> None:
    df = _frame([100, 100, 100, 100])
    funding = _const(df, 0.001)
    long = replay(df, _const(df, 1.0), _const(df, 4.0), funding, VENUE)
    short = replay(df, _const(df, -1.0), _const(df, 4.0), funding, VENUE)
    fees = 2 * 1000 * 0.0007
    assert long.pnl.sum() == pytest.approx(-fees - 3 * 1000 * 0.001)
    assert short.pnl.sum() == pytest.approx(-fees + 3 * 1000 * 0.001)
    assert long.funding.sum() == pytest.approx(3.0) and short.funding.sum() == pytest.approx(-3.0)


def test_borrow_is_charged_to_both_sides() -> None:
    df = _frame([100, 100, 100])
    venue = Venue(borrow_per_bar=0.0004)
    for side in (1.0, -1.0):
        r = replay(df, _const(df, side), _const(df, 4.0), _const(df, 0.0), venue)
        assert r.funding.sum() == pytest.approx(2 * 1000 * 0.0004)


def test_unknown_leverage_opens_nothing() -> None:
    df = _frame([100, 110, 120])
    r = replay(df, _const(df, 1.0), _const(df, np.nan), _const(df, 0.0), VENUE)
    assert r.pnl.sum() == 0.0 and r.trades == []


def test_no_look_ahead_later_bars_do_not_change_earlier_results() -> None:
    rng = np.random.default_rng(5)
    opens = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 60))))
    df = _frame(opens)
    later = _frame(opens[:40] + [x * 2 for x in opens[40:]])
    direction = pd.Series(np.sign(rng.normal(size=60)), index=df.index)
    a = replay(df, direction, _const(df, 8.0), _const(df, 0.0), VENUE)
    b = replay(later, direction, _const(df, 8.0), _const(df, 0.0), VENUE)
    np.testing.assert_allclose(a.pnl[:39], b.pnl[:39])


def test_window_starts_flat_and_ignores_earlier_signals() -> None:
    df = _frame([100, 120, 120, 120, 132])
    r = replay(df, _const(df, 1.0), _const(df, 2.0), _const(df, 0.0), VENUE, start=2)
    assert len(r.pnl) == 3 and r.pnl[0] == 0.0
    assert r.pnl.sum() == pytest.approx(500 * 0.10 - 2 * 500 * 0.0007)


def test_mismatched_index_is_refused() -> None:
    df = _frame([100, 100, 100])
    with pytest.raises(ValueError):
        replay(df, _const(df, 1.0).iloc[:-1], _const(df, 2.0), _const(df, 0.0), VENUE)


@pytest.mark.parametrize(("exit_price", "liquidated"), [(110.0, False), (60.0, True)])
def test_one_trade_matches_the_paper_simulator(exit_price: float, liquidated: bool) -> None:
    """A single 3x long gives the same dollars as ``PaperPerpsAccount`` (fixture values)."""
    params = fixture_params(borrow_rate_pct_per_hour="0")
    acct = PaperPerpsAccount.start(params, T0)
    acct.open("SOL", PerpSide.LONG, {"SOL": Decimal(100)}, T0)
    later = T0 + timedelta(hours=4)
    acct.mark({"SOL": Decimal(str(exit_price))}, later)
    acct.close("SOL", {"SOL": Decimal(str(exit_price))}, later, reason="TEST")
    expected = float(acct.cash_usd - params.starting_collateral_usd)

    venue = Venue(fee_bps=6.0, maintenance_bps=20.0, collateral_usd=200.0)
    df = _frame([100, 100, exit_price], lows=[100, min(100.0, exit_price), exit_price])
    direction = pd.Series([1.0, 0.0, 0.0], index=df.index)
    r = replay(df, direction, _const(df, 3.0), _const(df, 0.0), venue)
    assert (r.liquidations == 1) is liquidated
    assert r.pnl.sum() == pytest.approx(expected, abs=0.02)
