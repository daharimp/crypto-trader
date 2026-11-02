"""Perps replay and CLI (ADR-024)."""

from __future__ import annotations

import math

from typer.testing import CliRunner

from tests.perps_support import bars_from_closes, fixture_params
from trader.cli.main import app
from trader.perps.backtest import run_perps_backtest


def _wave(n: int, base: float, amp: float, period: int) -> list[float]:
    return [base * (1 + amp * math.sin(2 * math.pi * i / period)) for i in range(n)]


def _bars() -> dict:  # type: ignore[type-arg]
    return {
        "SOL": bars_from_closes(_wave(400, 100, 0.2, 120)),
        "ETH": bars_from_closes(_wave(400, 2000, 0.1, 90)),
    }


def test_replay_is_deterministic_and_trades_both_sides() -> None:
    a = run_perps_backtest(fixture_params(), _bars())
    b = run_perps_backtest(fixture_params(), _bars())
    assert a == b
    sides = {e["side"] for e in a.events if e["event"] == "OPENED"}
    assert sides == {"long", "short"} and a.trades > 2
    assert a.max_drawdown_pct >= 0


def test_long_only_never_shorts() -> None:
    r = run_perps_backtest(fixture_params(), _bars(), allow_shorts=False)
    assert all(e["side"] == "long" for e in r.events if e["event"] == "OPENED")


def test_no_look_ahead() -> None:
    bars = _bars()
    full = run_perps_backtest(fixture_params(), bars)
    cut = {m: bs[:300] for m, bs in bars.items()}
    part = run_perps_backtest(fixture_params(), cut)
    t_cut = cut["SOL"][-1].open_time_utc.isoformat()
    early = lambda evs: [e for e in evs if e["at_utc"] < t_cut]  # noqa: E731
    assert early(full.events) == early(part.events)


def test_high_leverage_gets_liquidated_on_wicks() -> None:
    p = fixture_params(
        max_leverage="50",
        target_leverage="50",
        min_liquidation_distance_pct="1",
        max_total_size_pct_of_equity="5000",
    )
    bars = {"SOL": bars_from_closes(_wave(300, 100, 0.2, 60), wick=0.03)}
    assert run_perps_backtest(p, bars).liquidations > 0


def test_cli_validate_exits_3_on_shipped_config() -> None:
    res = CliRunner().invoke(app, ["perps", "validate"])
    assert res.exit_code == 3
    assert "PERPS_CONFIG_UNRESOLVED" in res.output + (res.stderr or "")
