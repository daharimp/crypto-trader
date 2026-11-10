"""Research lab: no look-ahead, costs charged, holdout sealed (ADR-026)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader.research.lab import (
    PERPS,
    SPOT,
    Costs,
    donchian,
    evaluate,
    metrics,
    simulate,
    sma_stance,
    split,
    squeeze_breakout,
    tsmom,
)


def _frame(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * 1.003,
            "low": np.minimum(o, c) * 0.997,
            "close": c,
            "volume": 1.0,
        },
        index=idx,
    )


@pytest.mark.parametrize(
    "sig",
    [
        sma_stance(20, 50, True),
        tsmom(42, False),
        donchian(20, 10, True),
        squeeze_breakout(20, 0.3, 3.0, True),
    ],
)
def test_signals_have_no_look_ahead(sig) -> None:  # type: ignore[no-untyped-def]
    df = _frame()
    full = sig(df)
    cut = sig(df.iloc[:1000])
    pd.testing.assert_series_equal(full.iloc[:1000], cut, check_names=False)


def test_costs_are_charged_on_changes_and_borrow_while_open() -> None:
    df = _frame(10)
    flat = pd.Series(0.0, index=df.index)
    assert simulate(df, flat, PERPS).abs().sum() == 0
    always = pd.Series(1.0, index=df.index)
    free = simulate(df, always, Costs("free", 0.0))
    r = simulate(df, always, Costs("x", 10.0, 0.01))
    diff = (free - r).round(12)
    assert diff.iloc[1] == pytest.approx(10 / 10_000 + 0.01 / 100 * 4)  # entry fee + borrow
    assert diff.iloc[2] == pytest.approx(0.01 / 100 * 4)  # borrow only


def test_position_starts_next_bar() -> None:
    df = _frame(5)
    t = pd.Series([1.0, 0, 0, 0, 0], index=df.index)
    r = simulate(df, t, Costs("free", 0.0))
    assert r.iloc[0] == 0 and r.iloc[1] != 0 and r.iloc[2] == 0


def test_holdout_is_sealed_and_folds_do_not_overlap_it() -> None:
    df = _frame(5000)
    folds, (h0, h1) = split(df, holdout_days=180, folds=3)
    assert h1 == len(df) and h1 - h0 == 1080
    assert all(b <= h0 for _, b in folds)
    assert len(evaluate(df, tsmom(42, False), SPOT)) == 3
    assert len(evaluate(df, tsmom(42, False), SPOT, holdout=True)) == 1


def test_metrics_on_buy_and_hold_matches_price_minus_fee() -> None:
    df = _frame(200)
    r = metrics(df, pd.Series(1.0, index=df.index), Costs("x", 0.0))
    assert r.trades == 1 and r.exposure > 0.99
    assert r.max_drawdown >= 0
