"""Real funding as the holding cost in research replays (EXP-2026-014)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from trader.research.funding import load_funding, per_bar, simulate_funded
from trader.research.lab import Costs, simulate


def _frame(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    o = 100.0 + np.arange(n)
    return pd.DataFrame({"open": o, "high": o + 1, "low": o - 1, "close": o + 0.5}, index=idx)


def _hourly(n_hours: int, rate: float) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n_hours, freq="1h", tz="UTC")
    return pd.Series(rate, index=idx)


def _write(tmp_path: Path, text: str) -> str:
    p = tmp_path / "f.csv"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_load_funding_reads_hours_and_sorts(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "hour_start_utc,rate\n2024-01-01T01:00:00+00:00,-2e-05\n2024-01-01T00:00:00+00:00,1e-05\n",
    )
    s = load_funding(path)
    assert list(s) == [1e-05, -2e-05]
    assert s.index[0] == pd.Timestamp("2024-01-01T00:00:00Z")


@pytest.mark.parametrize(
    "text",
    [
        "time,rate\n2024-01-01T00:00:00+00:00,1e-05\n",
        "hour_start_utc,rate\n2024-01-01T00:30:00+00:00,1e-05\n",
        "hour_start_utc,rate\n2024-01-01T00:00:00+00:00,1e-05\n2024-01-01T00:00:00+00:00,2e-05\n",
    ],
)
def test_load_funding_rejects_bad_files(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        load_funding(_write(tmp_path, text))


def test_per_bar_sums_the_four_hours_of_each_bar() -> None:
    df = _frame(3)
    hourly = pd.Series(
        np.arange(12, dtype=float),
        index=pd.date_range("2024-01-01", periods=12, freq="1h", tz="UTC"),
    )
    assert list(per_bar(hourly, df.index)) == [0 + 1 + 2 + 3, 4 + 5 + 6 + 7, 8 + 9 + 10 + 11]


def test_per_bar_marks_a_bar_with_a_missing_hour_instead_of_filling_it() -> None:
    df = _frame(3)
    hourly = _hourly(12, 1e-05).drop(pd.Timestamp("2024-01-01T05:00:00Z"))
    out = per_bar(hourly, df.index)
    assert out.isna().tolist() == [False, True, False]
    assert out.iloc[0] == pytest.approx(4e-05)


def test_long_pays_and_short_receives_positive_funding() -> None:
    df = _frame()
    bar = per_bar(_hourly(48, 1e-04), df.index)
    flat_price = df.assign(open=100.0)
    long_r = simulate_funded(flat_price, pd.Series(1.0, index=df.index), 0.0, bar)
    short_r = simulate_funded(flat_price, pd.Series(-1.0, index=df.index), 0.0, bar)
    # Bar 0 holds nothing (the first decision fills at the next open).
    assert long_r.iloc[0] == 0.0
    assert long_r.iloc[1] == pytest.approx(-4e-04)
    assert short_r.iloc[1] == pytest.approx(4e-04)


def test_negative_funding_pays_the_long() -> None:
    df = _frame().assign(open=100.0)
    bar = per_bar(_hourly(48, -1e-04), df.index)
    r = simulate_funded(df, pd.Series(1.0, index=df.index), 0.0, bar)
    assert r.iloc[1] == pytest.approx(4e-04)


def test_zero_funding_matches_the_lab_simulation() -> None:
    df = _frame()
    target = pd.Series([1, 1, -1, -1, 0, 0.5, 0.5, -0.25, 1, 1, 0, 0], index=df.index, dtype=float)
    bar = per_bar(_hourly(48, 0.0), df.index)
    expected = simulate(df, target, Costs("fee_only", 7.0))
    pd.testing.assert_series_equal(simulate_funded(df, target, 7.0, bar), expected)


def test_no_look_ahead_funding_after_a_bar_does_not_change_it() -> None:
    df = _frame()
    target = pd.Series(1.0, index=df.index)
    hourly = _hourly(48, 1e-04)
    later = hourly.copy()
    later.iloc[24:] = 9e-03
    a = simulate_funded(df, target, 7.0, per_bar(hourly, df.index))
    b = simulate_funded(df, target, 7.0, per_bar(later, df.index))
    pd.testing.assert_series_equal(a.iloc[:6], b.iloc[:6])


def test_unknown_funding_gives_nan_not_zero_cost() -> None:
    df = _frame()
    hourly = _hourly(48, 1e-04).drop(pd.Timestamp("2024-01-01T09:00:00Z"))
    r = simulate_funded(df, pd.Series(1.0, index=df.index), 0.0, per_bar(hourly, df.index))
    assert np.isnan(r.iloc[2]) and not np.isnan(r.iloc[3])


def test_mismatched_index_is_refused() -> None:
    df = _frame()
    bar = per_bar(_hourly(48, 0.0), df.index[:-1])
    with pytest.raises(ValueError):
        simulate_funded(df, pd.Series(1.0, index=df.index), 0.0, bar)
