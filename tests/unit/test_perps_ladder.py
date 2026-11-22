"""Take-profit ladder on a paper perps account (ADR-045): TP1 -> breakeven, TP2 -> TP1, TP3.

Values below are TEST FIXTURES with no market meaning, except where the shipped config files
are read on purpose.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.conftest import SHIPPED_CONFIGS
from tests.perps_support import T0, fixture_file, fixture_params
from trader.perps.history import read_history
from trader.perps.math import PerpSide
from trader.perps.params import (
    PerpsConfigFile,
    PerpsConfigUnresolvedError,
    load_perps_params,
    resolve,
    settings_summary,
)
from trader.perps.session import _dump_account, _load_account, describe
from trader.perps.simulator import PaperPerpsAccount

M = {"SOL": D(100), "ETH": D(2000)}
LADDER = {
    "stop_loss_pct_of_collateral": "30",
    "take_profit_1_r": "1",
    "take_profit_1_close_pct": "25",
    "take_profit_2_r": "2",
    "take_profit_2_close_pct": "25",
    "take_profit_3_r": "3",
}
H4 = timedelta(hours=4)


def _account(side: PerpSide = PerpSide.LONG, **overrides: str) -> PaperPerpsAccount:
    a = PaperPerpsAccount.start(fixture_params(**{**LADDER, **overrides}), T0)
    assert a.open("SOL", side, M, T0).approved
    return a


def _bar(
    a: PaperPerpsAccount, n: int, low: str, high: str, close: str, open_: str | None = None
) -> None:
    """Mark SOL with one bar (long position: low is adverse, high favorable)."""
    long = a.positions["SOL"].side == PerpSide.LONG if "SOL" in a.positions else True
    adverse, favorable = (D(low), D(high)) if long else (D(high), D(low))
    a.mark(
        {**M, "SOL": adverse},
        T0 + n * H4,
        opens={"SOL": D(open_ or high)},
        favorable={"SOL": favorable},
        closes={"SOL": D(close)},
    )


# --- configuration ---------------------------------------------------------------------
def test_shipped_perps_configs_have_the_owner_ladder_on_a_30_percent_stop() -> None:
    for name in ("jupiter.yaml", "jupiter-degen.yaml"):
        p = load_perps_params(SHIPPED_CONFIGS, name)
        assert p.stop_loss_pct_of_collateral == D(30)  # UD-32
        assert p.take_profits == ((D(4), D(25)), (D(8), D(25)), (D(12), D(50)))
        assert settings_summary(p)["take_profits"][2] == {"at_r": "12", "close_pct": "50"}


def test_ladder_resolves_with_the_rest_closing_at_tp3() -> None:
    p = fixture_params(**LADDER)
    assert p.take_profits == ((D(1), D(25)), (D(2), D(25)), (D(3), D(50)))


def test_partial_ladder_is_refused() -> None:
    with pytest.raises(ValueError, match="needs all of"):
        fixture_params(**{**LADDER, "take_profit_3_r": ""})


@pytest.mark.parametrize(
    ("key", "bad", "msg"),
    [
        ("take_profit_2_r", "1", "increasing"),
        ("take_profit_1_r", "0", "increasing"),
        ("take_profit_2_close_pct", "75", "leave part"),
        ("take_profit_1_close_pct", "0", "leave part"),
    ],
)
def test_bad_ladder_values_are_refused(key: str, bad: str, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        fixture_params(**{**LADDER, key: bad})


def test_tbd_ladder_value_fails_closed() -> None:
    raw = fixture_file(**LADDER)
    raw["risk"]["take_profit_2_r"] = {"value": "TBD", "status": "unresolved", "ref": "UD-32"}
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        resolve(PerpsConfigFile.model_validate(raw))
    assert exc.value.keys == ["risk.take_profit_2_r"] and exc.value.refs == ["UD-32"]


# --- the ladder --------------------------------------------------------------------------
def test_tp_levels_are_measured_from_the_opening_stop() -> None:
    a = _account()
    p = a.positions["SOL"]
    assert p.initial_stop == a.stop_price(p)
    r = p.entry_price - p.initial_stop
    assert a.tp_price(p, 0) == p.entry_price + r
    assert a.tp_price(p, 2) == p.entry_price + 3 * r


def test_tp1_closes_a_quarter_and_moves_the_stop_to_breakeven() -> None:
    a = _account()
    p = a.positions["SOL"]
    size, tp1 = p.size_usd, a.tp_price(p, 0)
    assert tp1 is not None
    _bar(a, 1, "99", str(tp1 + D("0.5")), str(tp1))
    p = a.positions["SOL"]
    assert p.tps_hit == 1 and p.size_usd == size * D("0.75")
    stop = a.stop_price(p)
    assert stop is not None and D(100) < stop < D("100.2")  # breakeven plus fees
    tp = [e for e in a.events if e["event"] == "TAKE_PROFIT"][-1]
    assert tp["step"] == 1 and D(tp["exit"]) == tp1
    assert "take-profit 1" in describe(tp)


def test_tp2_moves_the_stop_to_tp1_and_tp3_closes_the_rest() -> None:
    a = _account()
    p = a.positions["SOL"]
    size = p.size_usd
    tp1, tp2, tp3 = (a.tp_price(p, i) for i in range(3))
    assert tp1 and tp2 and tp3
    _bar(a, 1, "99", str(tp2), str(tp2))  # one bar reaches TP1 and TP2
    p = a.positions["SOL"]
    assert p.tps_hit == 2 and p.size_usd == size * D("0.5")
    assert a.stop_price(p) == tp1
    _bar(a, 2, str(tp2), str(tp3 + 1), str(tp3))
    assert "SOL" not in a.positions and "SOL" in a.stopped_today
    closed = [e for e in a.events if e["event"] == "CLOSED"][-1]
    assert closed["reason"] == "TAKE_PROFIT_3" and D(closed["exit"]) == tp3
    assert a.cash_usd > D(1000)


def test_after_tp1_a_drop_exits_at_breakeven_not_at_the_original_stop() -> None:
    a = _account()
    tp1 = a.tp_price(a.positions["SOL"], 0)
    assert tp1 is not None
    _bar(a, 1, "99", str(tp1), str(tp1))
    _bar(a, 2, "95", str(tp1), "96")
    assert "SOL" not in a.positions
    closed = [e for e in a.events if e["event"] == "CLOSED"][-1]
    assert closed["reason"] == "STOP_LOSS" and D(100) < D(closed["exit"]) < D("100.2")
    assert a.cash_usd > D(1000)  # the TP1 profit is kept


def test_bar_that_hits_tp1_and_closes_below_breakeven_exits_at_the_close() -> None:
    a = _account()
    tp1 = a.tp_price(a.positions["SOL"], 0)
    assert tp1 is not None
    _bar(a, 1, "99", str(tp1), "99.5")
    assert "SOL" not in a.positions
    assert D([e for e in a.events if e["event"] == "CLOSED"][-1]["exit"]) == D("99.5")


def test_stop_is_checked_before_take_profit_in_the_same_bar() -> None:
    a = _account()
    tp1 = a.tp_price(a.positions["SOL"], 0)
    assert tp1 is not None
    _bar(a, 1, "85", str(tp1), "100")
    assert "SOL" not in a.positions
    assert not [e for e in a.events if e["event"] == "TAKE_PROFIT"]


def test_short_ladder_mirrors_the_long() -> None:
    a = _account(PerpSide.SHORT)
    p = a.positions["SOL"]
    tp1 = a.tp_price(p, 0)
    assert tp1 is not None and tp1 < D(100)
    _bar(a, 1, str(tp1), "101", str(tp1))
    p = a.positions["SOL"]
    stop = a.stop_price(p)
    assert p.tps_hit == 1 and stop is not None and D("99.8") < stop < D(100)


def test_without_a_ladder_nothing_changes() -> None:
    a = PaperPerpsAccount.start(fixture_params(stop_loss_pct_of_collateral="30"), T0)
    assert a.open("SOL", PerpSide.LONG, M, T0).approved
    assert a.positions["SOL"].initial_stop is None
    _bar(a, 1, "99", "200", "150")
    assert a.positions["SOL"].tps_hit == 0
    assert not [e for e in a.events if e["event"] == "TAKE_PROFIT"]


# --- persistence and history -------------------------------------------------------------
def test_ladder_state_survives_a_restart() -> None:
    a = _account()
    tp1 = a.tp_price(a.positions["SOL"], 0)
    assert tp1 is not None
    _bar(a, 1, "99", str(tp1), str(tp1))
    b = _load_account(a.params, _dump_account(a))
    p, q = a.positions["SOL"], b.positions["SOL"]
    assert (q.initial_stop, q.tps_hit, q.moved_stop) == (p.initial_stop, 1, p.moved_stop)


def test_old_state_without_ladder_keys_loads_and_gets_a_ladder() -> None:
    a = _account()
    d = _dump_account(a)
    for k in ("initial_stop", "tps_hit", "moved_stop"):
        del d["positions"]["SOL"][k]
    b = _load_account(a.params, d)
    assert b.positions["SOL"].initial_stop is None
    _bar(b, 1, "99", "112", "112")
    assert b.positions["SOL"].tps_hit >= 1


def test_history_adds_take_profits_to_the_trade(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    a = _account()
    tp1 = a.tp_price(a.positions["SOL"], 0)
    assert tp1 is not None
    _bar(a, 1, "99", str(tp1), str(tp1))
    _bar(a, 2, "95", str(tp1), "96")
    log = tmp_path / "events.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in a.events), encoding="utf-8")
    t = read_history(log)["trades"][0]
    assert t["take_profits"] == 1
    assert D(t["pnl_usd"]) == (
        a.cash_usd - D(1000) + [D(e["fee_usd"]) for e in a.events if e["event"] == "OPENED"][0]
    )
