"""Hourly sweep with the trend from 4h candles (ADR-040), and the dashboard's All view.

Values are TEST FIXTURES with no market meaning, except the shipped configs read on purpose.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from trader.cli.main import app
from trader.perps.backtest import Bar
from trader.perps.params import load_perps_params
from trader.perps.session import PerpsSession, SessionStateError
from trader.perps.signals import make_signal

NOW = datetime(2026, 11, 16, 6, 2, tzinfo=UTC)
STEP = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}


def _feed(symbol: str, tf: str) -> list[list[float]]:
    """720 rows like Kraken's free feed (the last one forming), on a steady decline."""
    step, n = STEP[tf], 720
    start = NOW.replace(minute=0) - step * (n - 1)
    if tf == "4h":
        start = start.replace(hour=start.hour // 4 * 4)
    out, prev = [], None
    for i in range(n):
        c = 100 * (1 + 0.25 * (n - 1 - i) / n) * (1 + 0.003 * (-1) ** i)
        prev = prev or c
        out.append(
            [
                int((start + i * step).timestamp() * 1000),
                prev,
                max(prev, c) * 1.002,
                min(prev, c) * 0.998,
                c,
                1.0,
            ]
        )
        prev = c
    return out


def _session(tmp: Path, trend: str | None, **kw: object) -> PerpsSession:
    return PerpsSession(
        load_perps_params(SHIPPED_CONFIGS, "jupiter-degen.yaml"),
        _feed,
        tmp / "state.json",
        tmp / "events.jsonl",
        signal=make_signal("tsmom_30d", 6 if trend else 24),
        signal_name="tsmom_30d",
        timeframe="1h",
        trend_timeframe=trend,
        **kw,  # type: ignore[arg-type]
    )


def test_hourly_sweep_trades_only_with_the_4h_trend(tmp_path: Path) -> None:
    plain = _session(tmp_path / "a", None)
    kinds = [e["event"] for e in plain.cycle(NOW)]
    assert "OPENED" not in kinds  # 720 1h candles are one short of a 30-day trend
    hybrid = _session(tmp_path / "b", "4h")
    events = hybrid.cycle(NOW)
    opened = [e for e in events if e["event"] == "OPENED"]
    assert len(opened) == 3 and all(e["side"] == "short" for e in opened)
    assert hybrid.meta["trend_timeframe"] == "4h" and hybrid.meta["timeframe"] == "1h"
    assert all(m in hybrid.acct.daily_moves for m in ("BTC", "ETH", "SOL"))  # type: ignore[union-attr]


def test_trend_timeframe_must_be_longer(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="longer timeframe"):
        _session(tmp_path, "1h")
    with pytest.raises(ValueError, match="longer timeframe"):
        _session(tmp_path, "15m")


def test_saved_state_with_another_trend_setting_is_refused(tmp_path: Path) -> None:
    _session(tmp_path, "4h").cycle(NOW)
    with pytest.raises(SessionStateError, match="different signal, timeframe"):
        _session(tmp_path, None)


def test_trend_view_uses_completed_candles_and_adds_the_latest_price_once(tmp_path: Path) -> None:
    s = _session(tmp_path, "4h")
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [Bar(t0 + i * STEP["4h"], *(Decimal(i + 1),) * 4) for i in range(3)]  # closes 1, 2, 3
    inside, _ = s._trend_view(candles, t0 + timedelta(hours=10), Decimal(9))
    assert inside == [Decimal(1), Decimal(2), Decimal(9)]  # third candle still forming
    boundary, move = s._trend_view(candles, t0 + timedelta(hours=12), Decimal(3))
    assert (
        boundary == [Decimal(1), Decimal(2), Decimal(3)] and move is None
    )  # too short for 30 days


def test_cli_hourly_degen_run_records_the_trend_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", _feed)
    r = CliRunner().invoke(
        app, ["perps", "paper", "run", "--once", "--account", "degen", "--timeframe", "1h"]
    )
    assert r.exit_code == 0, r.output
    meta = json.loads((tmp_path / "state" / "perps-degen.json").read_text())["meta"]
    assert (meta["timeframe"], meta["trend_timeframe"]) == ("1h", "4h")
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--account", "degen"])
    assert r.exit_code == 2  # a 4h restart cannot silently continue an hourly account


def test_compose_runs_degen_hourly_and_main_unchanged() -> None:
    text = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert '"--account", "degen", "--timeframe", "1h"' in text
    assert 'command: ["perps", "paper", "run"]\n' in text


def test_dashboard_has_an_all_accounts_view() -> None:
    static = Path(__file__).resolve().parents[2] / "src" / "trader" / "ui" / "static"
    assert 'data-v="all"' in (static / "index.html").read_text()
    js = (static / "views.js").read_text()
    assert "function allModel" in js and "positionCards" in js
