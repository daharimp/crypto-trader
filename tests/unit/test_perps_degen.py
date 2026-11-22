"""Second paper perps account with its own settings (ADR-038): stop, bad-day alert, CLI, UI.

Values below are TEST FIXTURES with no market meaning, except where the shipped
``configs/perps/jupiter-degen.yaml`` is read on purpose.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from tests.perps_support import T0, fixture_file, fixture_params, no_stop_params
from trader.cli.main import app
from trader.perps.math import PerpSide
from trader.perps.params import (
    PerpsConfigFile,
    PerpsConfigUnresolvedError,
    load_perps_file,
    load_perps_params,
    resolve,
    settings_summary,
)
from trader.perps.session import _dump_account, _load_account, describe
from trader.perps.simulator import PaperPerpsAccount
from trader.ui.server import Sources, serve

M = {"SOL": D(100), "ETH": D(2000)}
STOP = {"stop_loss_pct_of_collateral": "30"}


def _long_sol(**overrides: str) -> PaperPerpsAccount:
    a = PaperPerpsAccount.start(fixture_params(**overrides), T0)
    assert a.open("SOL", PerpSide.LONG, M, T0).approved
    return a


# --- configuration ---------------------------------------------------------------------
def test_shipped_degen_config_has_the_owner_values_and_main_is_unchanged() -> None:
    degen = load_perps_params(SHIPPED_CONFIGS, "jupiter-degen.yaml")
    assert degen.max_collateral_per_position_pct == D(5)
    assert degen.liquidation_buffer_daily_moves == D(3)
    assert degen.stop_loss_pct_of_collateral == D(30)
    assert degen.daily_loss_limit_pct == D(15)
    main = load_perps_params(SHIPPED_CONFIGS)
    assert main.stop_loss_pct_of_collateral == D(30)  # UD-32, ADR-044
    assert main.max_collateral_per_position_pct == D(10)
    assert main.liquidation_buffer_daily_moves == D(4)
    assert settings_summary(degen)["stop_pct_of_collateral"] == "30"
    assert settings_summary(main)["stop_pct_of_collateral"] == "30"


def test_unresolved_stop_fails_closed() -> None:
    raw = fixture_file(**STOP)
    raw["risk"]["stop_loss_pct_of_collateral"] = {
        "value": "TBD",
        "status": "unresolved",
        "ref": "UD-29",
    }
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        resolve(PerpsConfigFile.model_validate(raw))
    assert "risk.stop_loss_pct_of_collateral" in exc.value.keys and exc.value.refs == ["UD-29"]


@pytest.mark.parametrize("bad", ["0", "100", "-5"])
def test_stop_must_be_between_0_and_100(bad: str) -> None:
    with pytest.raises(ValueError, match="stop_loss_pct_of_collateral"):
        fixture_params(stop_loss_pct_of_collateral=bad)


@pytest.mark.parametrize("name", ["../live/authorization.yaml", "perps/x.yaml", "jupiter.yml"])
def test_config_file_name_must_be_a_plain_yaml_name(name: str) -> None:
    with pytest.raises(ValueError, match="plain .yaml file name"):
        load_perps_file(SHIPPED_CONFIGS, name)


# --- stop and wait-until-tomorrow -------------------------------------------------------
def test_stop_closes_at_30_percent_of_collateral_and_waits_for_the_next_day() -> None:
    a = _long_sol(**STOP)
    p = a.positions["SOL"]
    stop = a.stop_price(p)
    assert stop is not None and D(89) < stop < D(91)
    start_cash = D(1000)
    a.mark({**M, "SOL": D(85)}, T0 + timedelta(hours=4), opens={"SOL": D(99)})
    assert "SOL" not in a.positions
    closed = [e for e in a.events if e["event"] == "CLOSED"][-1]
    assert closed["reason"] == "STOP_LOSS"
    loss = start_cash - a.cash_usd
    assert abs(loss - p.collateral_usd * D("0.30")) < D("0.05")  # fees and borrow included
    a.apply_signal("SOL", PerpSide.LONG, M, T0 + timedelta(hours=8))
    assert "SOL" not in a.positions  # same UTC day: no reopen
    a.mark(M, T0 + timedelta(days=1))
    assert a.stopped_today == set()
    a.apply_signal("SOL", PerpSide.LONG, M, T0 + timedelta(days=1))
    assert "SOL" in a.positions  # next day: reopens


def test_gap_through_the_stop_fills_at_the_open() -> None:
    a = _long_sol(**STOP)
    a.mark({**M, "SOL": D(85)}, T0 + timedelta(hours=4), opens={"SOL": D(88)})
    closed = [e for e in a.events if e["event"] == "CLOSED"][-1]
    assert D(closed["exit"]) == D(88)


def test_gap_past_liquidation_is_a_liquidation_not_a_stop() -> None:
    a = _long_sol(**STOP)
    a.mark({**M, "SOL": D(60)}, T0 + timedelta(hours=4), opens={"SOL": D(60)})
    assert a.events[-1]["event"] == "LIQUIDATED" and "SOL" not in a.stopped_today


def test_without_a_stop_setting_nothing_changes() -> None:
    a = PaperPerpsAccount.start(no_stop_params(), T0)
    assert a.open("SOL", PerpSide.LONG, M, T0).approved
    assert a.stop_price(a.positions["SOL"]) is None
    a.mark({**M, "SOL": D(85)}, T0 + timedelta(hours=4), opens={"SOL": D(88)})
    assert "SOL" in a.positions


def test_short_stop_is_above_entry() -> None:
    a = PaperPerpsAccount.start(fixture_params(**STOP), T0)
    a.open("SOL", PerpSide.SHORT, M, T0)
    stop = a.stop_price(a.positions["SOL"])
    assert stop is not None and D(109) < stop < D(111)
    a.mark({**M, "SOL": D(112)}, T0 + timedelta(hours=4))
    assert "SOL" not in a.positions and "SOL" in a.stopped_today


# --- bad day ------------------------------------------------------------------------------
def test_bad_day_is_journaled_once_alerts_and_resets_next_day() -> None:
    a = _long_sol()  # fixture daily loss limit 5% of $1,000
    now = T0 + timedelta(hours=4)
    assert not a.check_day_loss(M, now)
    assert a.check_day_loss({**M, "SOL": D(90)}, now)
    assert not a.check_day_loss({**M, "SOL": D(80)}, now)  # once per day
    e = a.events[-1]
    assert e["event"] == "DAY_HALTED" and D(e["loss_pct"]) >= D(5)
    text = describe(e)
    assert text.startswith("BAD DAY") and "stop and analyze" in text
    assert not a.open("ETH", PerpSide.LONG, {**M, "SOL": D(90)}, now).approved
    a.mark({**M, "SOL": D(90)}, T0 + timedelta(days=1))
    assert a.day_halted is False


# --- saved state ----------------------------------------------------------------------------
def test_state_round_trip_keeps_the_stop_and_bad_day_flags() -> None:
    a = _long_sol(**STOP)
    a.stopped_today, a.day_halted = {"ETH"}, True
    d = json.loads(json.dumps(_dump_account(a)))
    b = _load_account(a.params, d)
    assert b.stopped_today == {"ETH"} and b.day_halted is True
    del d["stopped_today"], d["day_halted"]  # a state file written before ADR-038
    old = _load_account(a.params, d)
    assert old.stopped_today == set() and old.day_halted is False


# --- command line ---------------------------------------------------------------------------
def test_cli_validates_each_account_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    r = CliRunner().invoke(app, ["perps", "validate", "--account", "degen"])
    assert r.exit_code == 0, r.output
    assert "jupiter-degen.yaml v2" in r.output and "stop 30% of collateral" in r.output
    r = CliRunner().invoke(app, ["perps", "validate"])
    assert (
        r.exit_code == 0 and "jupiter.yaml v11" in r.output and "stop 30% of collateral" in r.output
    )
    assert CliRunner().invoke(app, ["perps", "validate", "--account", "yolo"]).exit_code == 2
    r = CliRunner().invoke(app, ["perps", "paper", "status", "--account", "degen"])
    assert r.exit_code == 0 and "no perps paper degen session" in r.output


def test_cli_degen_run_writes_its_own_state_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    closes = [100 * 0.995**i for i in range(200)]
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        ms = int((T0 + i * timedelta(hours=4)).timestamp() * 1000)
        rows.append([ms, prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 1.0])
        prev = c
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", lambda symbol, tf: rows)
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--account", "degen"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "state" / "perps-degen.json").exists()
    assert not (tmp_path / "state" / "perps-paper.json").exists()
    r = CliRunner().invoke(app, ["perps", "paper", "status", "--account", "degen"])
    assert "perps paper degen (tsmom_30d, 4h)" in r.output and "short" in r.output


# --- dashboard ------------------------------------------------------------------------------
def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


def test_dashboard_serves_the_degen_account_separately() -> None:
    degen: dict[str, Any] = {"signal": "tsmom_30d", "settings": {"collateral_pct": "5"}}
    src = Sources(lambda: {}, lambda s, t: [], fixture_params, dict, lambda: None, lambda: degen)
    httpd = serve(src, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert json.loads(_get(base + "/api/perps-paper")[1]) == {"running": False}
        assert json.loads(_get(base + "/api/perps-degen")[1]) == {"running": True, **degen}
        assert b"/api/perps-degen" in _get(base + "/views.js")[1]
        assert b'data-v="degen"' in _get(base + "/")[1]
    finally:
        httpd.shutdown()
