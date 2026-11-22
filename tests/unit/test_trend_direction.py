"""Shared 50/200 trend direction (ADR-043), its perps signal, and the spot-perps account."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from tests.perps_support import T0
from trader.cli.main import app
from trader.cli.perps import ACCOUNTS, resolve_signal
from trader.domain.enums import TrendState
from trader.perps.math import PerpSide
from trader.perps.params import load_perps_params
from trader.perps.review_facts import ACCOUNTS as REVIEW_ACCOUNTS
from trader.perps.signals import DEFAULT_SIGNAL, make_signal
from trader.regimes.trend import (
    FAST,
    SLOW,
    _mean,
    efficiency_ratio,
    is_ranging,
    trend_from_closes,
    trend_state,
)


def _closes(n: int, growth: float) -> list[D]:
    return [D(str(100 * growth**i)) for i in range(n)]


def test_trend_state_follows_the_two_averages() -> None:
    assert (FAST, SLOW) == (50, 200)
    assert trend_state(D(2), D(1)) == TrendState.TRENDING_UP
    assert trend_state(D(1), D(2)) == TrendState.TRENDING_DOWN
    assert trend_state(D(1), D(1)) == TrendState.UNKNOWN
    assert trend_state(None, D(1)) == TrendState.UNKNOWN


def test_trend_from_closes_needs_200_closes_and_reads_both_directions() -> None:
    assert trend_from_closes(_closes(260, 1.002)) == TrendState.TRENDING_UP
    assert trend_from_closes(_closes(260, 0.998)) == TrendState.TRENDING_DOWN
    assert trend_from_closes(_closes(199, 1.002)) == TrendState.UNKNOWN  # warming up
    assert trend_from_closes([D(5)] * 260) == TrendState.UNKNOWN  # flat: no side


def _chop_then_lift() -> list[D]:
    """A long fall, 180 bars of 2% zigzag drifting slowly lower, then a 2-day lift."""
    out = _closes(260, 0.997)
    level = out[-1]
    out += [level * D(str(0.9995**i * (1.02 if i % 2 else 0.98))) for i in range(180)]
    low = level * D(str(0.9995**180))
    out += [low * D(str(1.004**i)) for i in range(1, 13)]
    return out


def test_efficiency_ratio_tells_straight_lines_from_chop() -> None:
    assert efficiency_ratio(_closes(200, 1.01)) == D(1)
    assert efficiency_ratio(_chop_then_lift()) < D("0.05")
    assert efficiency_ratio(_closes(100, 1.01)) is None  # fewer than 181 closes
    assert efficiency_ratio([D(5)] * 200) is None  # no movement at all
    assert not is_ranging(_closes(260, 0.998)) and is_ranging(_chop_then_lift())


def test_ranging_market_switches_to_the_fast_10_30_pair() -> None:
    closes = _chop_then_lift()
    # The slow pair still says down; the fast pair has turned up with the lift.
    assert _mean(closes, 50) < _mean(closes, 200)  # type: ignore[operator]
    assert _mean(closes, 10) > _mean(closes, 30)  # type: ignore[operator]
    assert trend_from_closes(closes) == TrendState.TRENDING_UP


def test_default_perps_signal_is_the_shared_rule_long_and_short() -> None:
    signal = make_signal(DEFAULT_SIGNAL, 6)
    assert DEFAULT_SIGNAL == "trend_50_200_range_10_30"
    assert signal(_closes(260, 1.002)) == PerpSide.LONG
    assert signal(_closes(260, 0.998)) == PerpSide.SHORT
    assert signal(_closes(100, 0.998)) is None
    # A long fall, then a sharp 5-day bounce: the 50-bar average is still below the
    # 200-bar one, so the rule stays short (it does not chase a short bounce).
    bounce = _closes(260, 0.997) + [D(str(100 * 0.997**259 * 1.01**i)) for i in range(1, 31)]
    assert signal(bounce) == PerpSide.SHORT


def test_spot_perps_account_is_1x_with_the_owner_values_and_listed_everywhere() -> None:
    p = load_perps_params(SHIPPED_CONFIGS, "jupiter-spot-perps.yaml")
    assert p.max_leverage == p.target_leverage == D(1)
    assert p.liquidation_buffer_daily_moves is None  # every position opens at 1x
    assert p.stop_loss_pct_of_collateral == D(6)
    assert p.max_collateral_per_position_pct == D(15)
    assert p.daily_loss_limit_pct == D(5) and p.starting_collateral_usd == D(2500)
    assert ACCOUNTS["spot-perps"][:2] == REVIEW_ACCOUNTS["spot-perps"]


def test_resolve_signal_pins_spot_perps_to_the_shared_rule() -> None:
    assert resolve_signal("main", None) == DEFAULT_SIGNAL
    assert resolve_signal("main", "tsmom_30d") == "tsmom_30d"
    assert resolve_signal("spot-perps", None) == DEFAULT_SIGNAL
    assert resolve_signal("spot-perps", DEFAULT_SIGNAL) == DEFAULT_SIGNAL
    with pytest.raises(ValueError, match="only runs"):
        resolve_signal("spot-perps", "tsmom_30d")


def test_cli_spot_perps_runs_short_in_a_downtrend_and_refuses_another_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    closes = [100 * 0.995**i for i in range(260)]
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        ms = int((T0 + i * timedelta(hours=4)).timestamp() * 1000)
        rows.append([ms, prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 1.0])
        prev = c
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", lambda symbol, tf: rows)
    run = ["perps", "paper", "run", "--once", "--account", "spot-perps"]
    r = CliRunner().invoke(app, [*run, "--signal", "tsmom_30d"])
    assert r.exit_code == 2 and "only runs" in r.output
    r = CliRunner().invoke(app, run)
    assert r.exit_code == 0, r.output
    assert (tmp_path / "state" / "perps-spot-perps.json").exists()
    assert not (tmp_path / "state" / "perps-paper.json").exists()
    r = CliRunner().invoke(app, ["perps", "paper", "status", "--account", "spot-perps"])
    assert "(trend_50_200_range_10_30, 4h)" in r.output and "short" in r.output
