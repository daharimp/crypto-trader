"""ADR-047: read-only health checks and alert de-duplication for the server watchdog."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trader.ops.health import (
    Problem,
    alerts_to_send,
    build_snapshot,
    check_containers,
    check_logs,
    check_perps,
    check_spot,
    parse_compose_ps,
)

NOW = datetime(2026, 11, 23, 0, 30, tzinfo=UTC)


def _running(*services: str) -> list[dict[str, str]]:
    return [{"Service": s, "State": "running"} for s in services]


ALL = ("paper", "perps", "perps-degen", "perps-spot-perps", "review", "dashboard")


def test_parse_compose_ps_both_shapes() -> None:
    rows = [{"Service": "paper", "State": "running"}]
    assert parse_compose_ps(json.dumps(rows)) == rows
    assert parse_compose_ps("\n".join(json.dumps(r) for r in rows)) == rows
    assert parse_compose_ps("") == []
    with pytest.raises(ValueError):
        parse_compose_ps("not json")


def test_containers_all_running_is_quiet() -> None:
    assert check_containers(_running(*ALL)) == []


def test_containers_flag_stopped_missing_and_live() -> None:
    rows = _running("paper", "perps", "perps-degen", "review", "dashboard", "live")
    rows.append({"Service": "perps-spot-perps", "State": "exited"})
    keys = {p.key: p for p in check_containers([r for r in rows if r["Service"] != "review"])}
    assert keys["container:perps-spot-perps"].severity == "alert"
    assert "not created" in keys["container:review"].message
    assert keys["container:live"].severity == "warn"


def test_logs_group_errors_by_service() -> None:
    text = (
        "crypto-trader-perps-1  | INFO cycle ok\n"
        "crypto-trader-perps-1  | ERROR fetch failed\n"
        "crypto-trader-review-1  | Traceback (most recent call last):\n"
        "crypto-trader-paper-1  | EXECUTION_ERROR is a word, not a log level\n"
    )
    found = {p.key: p for p in check_logs(text)}
    assert set(found) == {"logs:perps", "logs:review"}
    assert "fetch failed" in found["logs:perps"].message


def _spot_state(root: Path, *, stop: str | None, equity: str, hwm: str, last: datetime) -> None:
    state = {
        "meta": {"equity_usd": equity, "last_cycle_wall_utc": last.isoformat()},
        "ledger": {
            "cash": equity,
            "positions": {"BTC-USD": {"quantity": "0.01", "stop_price": stop}},
        },
        "loss": {"hwm": hwm},
        "controls": {"breaker_open": False},
    }
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "session-paper.json").write_text(json.dumps(state))


def test_spot_healthy(tmp_path: Path) -> None:
    _spot_state(tmp_path, stop="90000", equity="980", hwm="1000", last=NOW)
    problems, summaries = check_spot(tmp_path, NOW)
    assert problems == []
    assert summaries[0]["drawdown_pct"] == 2.0


def test_spot_missing_stop_stale_and_drawdown(tmp_path: Path) -> None:
    _spot_state(tmp_path, stop=None, equity="880", hwm="1000", last=NOW - timedelta(hours=10))
    sev = {p.key: p.severity for p in check_spot(tmp_path, NOW)[0]}
    assert sev["spot:paper:stop:BTC-USD"] == "critical"
    assert sev["spot:paper:stale"] == "alert"
    assert sev["spot:paper:dd"] == "alert"


def test_spot_unreadable_state(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "session-x.json").write_text("{")
    assert check_spot(tmp_path, NOW)[0][0].key == "spot:x:state"


def _perps_state(path: Path, *, equity: str, peak: str, last: datetime, positions: bool) -> None:
    pos = {"BTC": {"side": "short", "tps_hit": 1}} if positions else {}
    path.write_text(
        json.dumps(
            {
                "meta": {
                    "timeframe": "1h",
                    "start_equity_usd": "1000",
                    "equity_usd": equity,
                    "peak_equity_usd": peak,
                    "max_drawdown_pct": "3",
                    "last_cycle_utc": last.isoformat(),
                },
                "account": {"cash_usd": equity, "positions": pos},
            }
        )
    )


def test_perps_healthy_and_summary(tmp_path: Path) -> None:
    state = tmp_path / "degen.json"
    _perps_state(state, equity="1050", peak="1060", last=NOW, positions=True)
    problems, summaries = check_perps({"degen": (state, "d.yaml")}, lambda _: Decimal("30"), NOW)
    assert problems == []
    assert summaries[0]["return_pct"] == 5.0 and summaries[0]["positions"][0]["tps_hit"] == 1


def test_perps_no_stop_with_positions_is_critical(tmp_path: Path) -> None:
    state = tmp_path / "main.json"
    _perps_state(state, equity="800", peak="1000", last=NOW - timedelta(hours=3), positions=True)
    sev = {
        p.key: p.severity for p in check_perps({"main": (state, "m.yaml")}, lambda _: None, NOW)[0]
    }
    assert sev == {
        "perps:main:stop": "critical",
        "perps:main:stale": "alert",
        "perps:main:dd": "critical",
    }


def test_perps_config_error_and_missing_state(tmp_path: Path) -> None:
    def broken(_: str) -> Decimal:
        raise ValueError("TBD")

    sev = {
        p.key: p.severity for p in check_perps({"x": (tmp_path / "no.json", "x")}, broken, NOW)[0]
    }
    assert sev == {"perps:x:config": "critical", "perps:x:missing": "warn"}


def test_snapshot_ok_ignores_warnings() -> None:
    assert build_snapshot([Problem("a", "warn", "m")], [], NOW)["ok"] is True
    snap = build_snapshot([Problem("a", "alert", "m")], [], NOW, commit="abc")
    assert snap["ok"] is False and snap["commit"] == "abc"


def test_alerts_new_repeat_escalate_and_resolve() -> None:
    remind = timedelta(hours=12)
    warn = Problem("dd", "warn", "down 6%")
    msgs, state = alerts_to_send({}, [warn], NOW, remind)
    assert msgs == ["WARN: down 6%"]
    # Same problem 15 minutes later: quiet.
    msgs, state = alerts_to_send(state, [warn], NOW + timedelta(minutes=15), remind)
    assert msgs == []
    # Severity rises: alert again.
    msgs, state = alerts_to_send(state, [Problem("dd", "alert", "down 11%")], NOW, remind)
    assert msgs == ["ALERT: down 11%"]
    # Still there after the reminder interval: alert again.
    later = NOW + timedelta(hours=13)
    msgs, state = alerts_to_send(state, [Problem("dd", "alert", "down 11%")], later, remind)
    assert msgs == ["ALERT: down 11%"]
    # Cleared: one resolved line, then empty state.
    msgs, state = alerts_to_send(state, [], later, remind)
    assert msgs == ["resolved: dd"] and state == {}
