"""Live snapshot vs history (ADR-029): offline tests with fake fetchers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

import trader.research.snapshot as snapmod
from trader.cli.main import app
from trader.research.snapshot import (
    PAIRS,
    Snapshot,
    analogs,
    book_depth,
    episodes,
    live_state,
    momentum_pattern,
    render_markdown,
    rsi_bucket,
    take_snapshot,
)


def _frame(n: int, freq: str, drift: float, seed: int = 1, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = start * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    idx = pd.date_range("2020-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "open": o,
            "high": np.maximum(o, c) * 1.002,
            "low": np.minimum(o, c) * 0.998,
            "close": c,
            "volume": 1.0,
        },
        index=idx,
    )


def _book(mid: float = 100.0) -> tuple[np.ndarray, np.ndarray]:
    bids = np.array([[mid - 0.05, 2.0], [mid * 0.995, 10.0], [mid * 0.98, 100.0]])
    asks = np.array([[mid + 0.05, 1.0], [mid * 1.005, 5.0], [mid * 1.02, 100.0]])
    return bids, asks


def _write_history(path: Path, df: pd.DataFrame) -> None:
    out = df.copy()
    out.insert(0, "open_time_utc", out.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
    out.to_csv(path, index=False)


def test_book_depth_counts_only_levels_within_one_percent() -> None:
    bids, asks = _book()
    spread, bid_usd, ask_usd = book_depth(bids, asks)
    assert spread == pytest.approx(0.1 / 100 * 1e4)
    assert bid_usd == pytest.approx((99.95 * 2) + (99.5 * 10))  # the 98.0 level is excluded
    assert ask_usd == pytest.approx((100.05 * 1) + (100.5 * 5))


def test_book_depth_rejects_an_empty_side() -> None:
    with pytest.raises(ValueError, match="empty"):
        book_depth(np.empty((0, 2)), _book()[1])


def test_live_state_reads_a_steady_uptrend() -> None:
    h4 = _frame(400, "4h", 0.002)
    d1 = _frame(400, "1D", 0.003)
    s = live_state(h4, d1, *_book(float(h4["close"].iloc[-1])))
    assert s.m1 > 0 and s.m3 > 0 and s.m12 > 0
    assert s.above_sma200_4h
    assert momentum_pattern(s.m1, s.m3, s.m12) == "12m up, 3m up, 1m up"
    assert s.last_bar_utc == h4.index[-1].isoformat()


def test_live_state_refuses_too_little_data() -> None:
    with pytest.raises(ValueError, match="need"):
        live_state(_frame(100, "4h", 0.0), _frame(400, "1D", 0.0), *_book())


def test_rsi_buckets() -> None:
    assert [rsi_bucket(x) for x in (29.9, 50, 70.1)] == ["oversold", "neutral", "overbought"]


def test_episodes_never_overlap() -> None:
    idx = episodes(np.ones(10, dtype=bool), 3)
    assert idx.tolist() == [0, 3, 6, 9]
    assert episodes(np.zeros(5, dtype=bool), 3).size == 0


def test_analogs_report_too_few_and_are_reproducible() -> None:
    hist = _frame(5000, "4h", 0.0005)  # Reason: 12-month warm-up plus >= 5 monthly episodes.
    s = live_state(hist.iloc[-400:], _frame(400, "1D", 0.003), *_book())
    a, b = analogs(hist, s), analogs(hist, s)
    assert a == b  # fixed seed
    base = [x for x in a if x.condition.startswith("all history")]
    assert all(x.episodes >= 5 and x.range90 is not None for x in base)
    assert all(x.range90 is None for x in a if x.episodes < 5)


def test_take_snapshot_survives_one_failing_coin(tmp_path: Path) -> None:
    _write_history(tmp_path / "btc_usd_4h.csv", _frame(3000, "4h", 0.0003))

    def ohlc(pair: str, minutes: int) -> pd.DataFrame:
        if pair == PAIRS["SUI"]:
            raise OSError("network down")
        seed = list(PAIRS.values()).index(pair)
        return _frame(400, "4h" if minutes == 240 else "1D", 0.001, seed=seed)

    snap = take_snapshot(
        tmp_path, 1000.0, ohlc, lambda p: _book(), now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert set(snap.states) == {"BTC", "ETH", "SOL", "XRP"}
    assert snap.errors == {"SUI": "network down"}
    assert set(snap.analogs) == {"BTC"}  # only BTC has history
    assert set(snap.correlation) == {"BTC", "ETH", "SOL", "XRP"}
    md = render_markdown(snap)
    assert "Research only" in md and "not guaranteed" in md
    assert "SUI | live data unavailable" in md
    assert "No local history for ETH, SOL, XRP" in md
    assert "by luck alone" in md


def test_cli_writes_report_and_fails_closed_without_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = Snapshot("2026-01-01T00:00+00:00", 2500.0)
    snap.states["BTC"] = live_state(_frame(400, "4h", 0.001), _frame(400, "1D", 0.001), *_book())
    monkeypatch.setattr(snapmod, "take_snapshot", lambda d, c: snap)
    out = tmp_path / "out"
    r = CliRunner().invoke(app, ["research", "snapshot", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert (out / "snapshot.json").exists() and (out / "snapshot.md").exists()

    monkeypatch.setattr(
        snapmod, "take_snapshot", lambda d, c: Snapshot("t", c, errors={"BTC": "x"})
    )
    r = CliRunner().invoke(app, ["research", "snapshot", "--out", str(out)])
    assert r.exit_code == 3

    r = CliRunner().invoke(app, ["research", "snapshot", "--capital", "0"])
    assert r.exit_code == 2
