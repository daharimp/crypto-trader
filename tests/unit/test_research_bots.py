"""Research bot simulators: grid, DCA with safety orders, plain DCA (ADR-028)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trader.research.bots import (
    KRAKEN,
    PIONEX,
    Book,
    BotCosts,
    dca_bot,
    grid_bot,
    path,
    plain_dca,
)

FREE = BotCosts("free", 0.0, 0.0)


def _bars(closes: list[float], wick: float = 0.0) -> pd.DataFrame:
    c = np.array(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range("2025-01-01", periods=len(c), freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * (1 + wick),
            "low": np.minimum(o, c) * (1 - wick),
            "close": c,
            "volume": 1.0,
        },
        index=idx,
    )


def _random(n: int = 3000, seed: int = 3, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    return _bars(list(c), wick=0.003)


def test_path_visits_nearer_extreme_first() -> None:
    assert path(100, 110, 99, 105) == [100, 99, 110, 105]
    assert path(100, 101, 90, 95) == [100, 101, 90, 95]


def test_book_never_overspends_or_oversells() -> None:
    b = Book(100.0)
    b.buy(500.0, 10.0, 0.0)
    assert b.cash == 0.0 and b.coin == pytest.approx(10.0)
    b.sell(50.0, 10.0, 0.0)
    assert b.coin == 0.0 and b.cash == pytest.approx(100.0)


def test_grid_earns_one_gap_per_round_trip_without_fees() -> None:
    # Range 90..110 with 2 gaps of 10: start at 100, fall to 90 (buy), rise to 100 (sell).
    df = _bars([100, 95, 90, 95, 100])
    r = grid_bot(df, 1000.0, FREE, width=0.10, levels=2)
    # Gap 0 is worth 500 at 90 -> 5.556 coin, sold at 100: +55.56.
    assert r.end == pytest.approx(1000 + 500 / 90 * 10, rel=1e-9)
    assert r.fills == 3  # start buy for the gap above, one buy, one sell


def test_grid_stops_outside_range_and_holds_coin_below_it() -> None:
    df = _bars([100, 90, 80, 70])
    r = grid_bot(df, 1000.0, FREE, width=0.10, levels=2)
    assert r.exposure > 0.9 or r.end < 1000  # all cash turned to coin as price fell
    assert r.end < r.start


def test_fees_reduce_grid_result() -> None:
    df = _random()
    free = grid_bot(df, 2500.0, FREE, width=0.1, levels=20)
    paid = grid_bot(df, 2500.0, KRAKEN, width=0.1, levels=20)
    cheap = grid_bot(df, 2500.0, PIONEX, width=0.1, levels=20)
    assert paid.end < cheap.end < free.end
    assert paid.fees > cheap.fees > 0


def test_grid_rebuild_keeps_trading_after_breakout() -> None:
    df = _random(drift=0.001)
    fixed = grid_bot(df, 2500.0, FREE, width=0.05, levels=10)
    rolling = grid_bot(df, 2500.0, FREE, width=0.05, levels=10, rebuild_hours=168)
    assert rolling.fills > fixed.fills


def test_dca_bot_takes_profit_and_restarts() -> None:
    # Falls 2% (one safety fill), then rallies past the take-profit, then flat.
    df = _bars([100, 99, 98, 99, 100, 101, 101, 101])
    r = dca_bot(df, 1000.0, FREE, safety_orders=2, step=0.02, volume_scale=1.0, take_profit=0.01)
    assert r.end > 1000.0
    assert r.fills >= 4  # base, safety, take-profit, new base


def test_dca_bot_never_goes_below_zero_cash_in_a_crash() -> None:
    df = _bars(list(np.linspace(100, 30, 200)))
    r = dca_bot(df, 1000.0, KRAKEN)
    assert 0 < r.end < 1000.0
    assert r.max_drawdown > 0.5


def test_plain_dca_spends_everything_evenly() -> None:
    df = _bars([100.0] * 336)  # two weeks flat
    r = plain_dca(df, 1000.0, FREE)
    assert r.end == pytest.approx(1000.0)
    assert r.fills == 2
    assert r.buy_hold_end == pytest.approx(1000.0)


def test_longer_window_only_adds_fills() -> None:
    df = _random()
    a = grid_bot(df.iloc[:1000], 2500.0, KRAKEN, width=0.1)
    b = grid_bot(df.iloc[:2000], 2500.0, KRAKEN, width=0.1)
    # Reason: bars are processed in order, so extra later bars cannot remove earlier fills.
    assert b.fills >= a.fills


@pytest.mark.parametrize(
    "call",
    [
        lambda df: grid_bot(df, 1000.0, FREE, width=0.0),
        lambda df: grid_bot(df, 1000.0, FREE, width=0.1, levels=0),
        lambda df: grid_bot(df, 0.0, FREE, width=0.1),
        lambda df: grid_bot(df.iloc[:0], 1000.0, FREE, width=0.1),
        lambda df: dca_bot(df, 1000.0, FREE, step=0.0),
        lambda df: dca_bot(df, 1000.0, FREE, take_profit=-0.01),
        lambda df: plain_dca(df, 1000.0, FREE, every_hours=0),
    ],
)
def test_bad_settings_are_rejected(call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        call(_bars([100.0, 101.0, 102.0]))
