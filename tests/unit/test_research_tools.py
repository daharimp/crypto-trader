"""Kraken OHLCVT import and the strategy comparison tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS, SHIPPED_PROFILE, SHIPPED_UNIVERSE, make_datasets
from trader.cli.main import app
from trader.data.providers.kraken_csv import (
    KrakenCsvError,
    read_kraken_ohlcvt,
    timeframe_from_name,
)
from trader.research.compare import CompareConfig, Comparison, render_markdown, window_bounds

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _kraken_file(tmp: Path, name: str = "XBTUSD_240.csv", n: int = 5) -> Path:
    p = tmp / name
    rows = [
        f"{int((T0 + timedelta(hours=4 * i)).timestamp())},100,101,99,100.5,12.5,40"
        for i in range(n)
    ]
    p.write_text("\n".join(rows) + "\n")
    return p


def test_kraken_ohlcvt_parse(tmp_path: Path) -> None:
    """Expected: headerless rows with unix seconds and a trades column parse as UTC candles."""
    df = read_kraken_ohlcvt(_kraken_file(tmp_path))
    assert len(df) == 5 and df["open_time_utc"].iloc[0] == T0
    assert str(df["close"].iloc[0]) == "100.5" and str(df["volume"].iloc[0]) == "12.5"


@pytest.mark.parametrize(
    ("name", "tf"), [("XBTUSD_240.csv", "4h"), ("ETHUSD_1440.csv", "1d"), ("solusd_60.csv", "1h")]
)
def test_timeframe_from_name(name: str, tf: str) -> None:
    """Edge: the interval comes from the file name."""
    assert timeframe_from_name(Path(name)) == tf


@pytest.mark.parametrize("name", ["XBTUSD_5.csv", "prices.csv"])
def test_bad_names(name: str) -> None:
    """Failure: unsupported interval or unrecognised name."""
    with pytest.raises(KrakenCsvError):
        timeframe_from_name(Path(name))


def test_bad_rows(tmp_path: Path) -> None:
    """Failure: short or non-numeric rows."""
    p = tmp_path / "XBTUSD_240.csv"
    p.write_text("1704067200,100,101\n")
    with pytest.raises(KrakenCsvError):
        read_kraken_ohlcvt(p)


def test_cli_import_kraken(tmp_path: Path) -> None:
    """CLI: import-kraken creates a kraken-venue dataset and prints its ID."""
    r = CliRunner().invoke(
        app,
        ["data", "import-kraken", "--file", str(_kraken_file(tmp_path)), "--instrument", "BTC-USD"],
    )
    assert r.exit_code == 0 and r.stdout.strip().startswith("ds-")
    bad = tmp_path / "XBTUSD_7.csv"
    bad.write_text("1,1,1,1,1,1,1\n")
    assert (
        CliRunner()
        .invoke(app, ["data", "import-kraken", "--file", str(bad), "--instrument", "BTC-USD"])
        .exit_code
        == 2
    )


def test_window_bounds() -> None:
    """Windows are consecutive, cover the range, and refuse windows shorter than a week."""
    w = window_bounds(T0, T0 + timedelta(days=60), 3)
    assert len(w) == 3 and w[0][0] == T0 and w[-1][1] == T0 + timedelta(days=60)
    assert all(a[1] == b[0] for a, b in zip(w, w[1:], strict=False))
    with pytest.raises(ValueError):
        window_bounds(T0, T0 + timedelta(days=10), 3)


def test_window_bounds_1h_and_unknown_timeframe() -> None:
    """1h windows step by the hour, still need 7 days each; unknown timeframes are refused."""
    from trader.research.compare import timeframe_step

    step = timeframe_step("1h")
    w = window_bounds(T0, T0 + timedelta(days=21, hours=1), 3, step)
    assert len(w) == 3 and w[1][0] == T0 + timedelta(hours=168)
    with pytest.raises(ValueError):
        window_bounds(T0, T0 + timedelta(days=20), 3, step)
    with pytest.raises(ValueError):
        timeframe_step("30m")


def test_compare_runs_grid_and_random_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: 2 strategies x 2 windows x 1 cost + matched random seeds; summary rows."""
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    from tests.e2e.test_eligibility_datasets import START, _daily
    from trader.common.clock import parse_utc

    ids = make_datasets(days=120, start=START, universe=SHIPPED_UNIVERSE)
    s = parse_utc(START) + timedelta(days=10)
    cfg = CompareConfig(
        profile=SHIPPED_PROFILE,
        datasets=ids,
        start=s,
        end=s + timedelta(days=100),
        strategies=["sma_trend", "tsmom"],
        cost_scenarios=["base"],
        windows=2,
        random_seeds=2,
        eligibility_datasets=_daily(),
        configs_root=SHIPPED_CONFIGS,
    )
    result = Comparison(cfg, tmp_path).run()
    assert len(result["runs"]) == 2 * (2 + 2) and all(r["ok"] for r in result["runs"])
    names = {r["strategy"] for r in result["summary"]}
    assert {"sma_trend", "tsmom", "random_entry (all seeds)"} <= names
    sma = next(r for r in result["summary"] if r["strategy"] == "sma_trend")
    assert sma["windows"] == 2 and sma["pct_random_beaten"] is not None
    rand = json.loads(json.dumps(result, default=str))["runs"][-1]
    assert rand["strategy"] == "random_entry" and "seed" in rand
    assert "| sma_trend | base | 2 |" in render_markdown(result)
