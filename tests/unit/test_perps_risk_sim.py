"""Perps risk checks and the paper account (ADR-025)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from tests.perps_support import T0, fixture_params
from trader.perps.math import PerpSide
from trader.perps.risk import AccountView, check_open, size_open
from trader.perps.simulator import PaperPerpsAccount

M = {"SOL": D(100), "ETH": D(2000)}


def _view(**kw: object) -> AccountView:
    base = dict(
        free_cash_usd=D(1000),
        equity_usd=D(1000),
        day_start_equity_usd=D(1000),
        open_markets=frozenset(),
        gross_size_usd=D(0),
        halted=False,
    )
    base.update(kw)
    return AccountView(**base)  # type: ignore[arg-type]


def test_sizing_uses_cap_and_target_leverage() -> None:
    p = fixture_params()
    pr = size_open(p, _view(), "SOL", PerpSide.LONG, D(100))
    assert pr.collateral_usd == D("200.00") and pr.size_usd == D("600.00")
    assert check_open(p, _view(), pr).approved


def test_liquidation_too_close_rejected() -> None:
    p = fixture_params(target_leverage="5", max_leverage="5", min_liquidation_distance_pct="25")
    pr = size_open(p, _view(), "SOL", PerpSide.SHORT, D(100))
    d = check_open(p, _view(), pr)
    assert not d.approved and "PERP_LIQUIDATION_TOO_CLOSE" in d.reasons


def test_every_failed_rule_is_listed() -> None:
    p = fixture_params()
    v = _view(halted=True, equity_usd=D(900), open_markets=frozenset({"SOL", "ETH", "X"}))
    d = check_open(p, v, size_open(p, v, "SOL", PerpSide.LONG, D(100)))
    assert {
        "PERP_KILL_SWITCH_ENGAGED",
        "PERP_POSITION_ALREADY_OPEN",
        "PERP_MAX_OPEN_POSITIONS",
        "PERP_DAILY_LOSS_LIMIT",
    } <= set(d.reasons)


def test_unknown_market_and_no_cash() -> None:
    p = fixture_params()
    v = _view(free_cash_usd=D(0))
    d = check_open(p, v, size_open(p, v, "DOGE", PerpSide.LONG, D(1)))
    assert not d.approved and "PERP_NO_COLLATERAL_AVAILABLE" in d.reasons


def test_total_size_cap() -> None:
    p = fixture_params(max_total_size_pct_of_equity="100")
    v = _view(gross_size_usd=D(600), open_markets=frozenset({"ETH"}))
    d = check_open(p, v, size_open(p, v, "SOL", PerpSide.LONG, D(100)))
    assert "PERP_TOTAL_SIZE_ABOVE_CAP" in d.reasons


def test_long_round_trip_accounting() -> None:
    a = PaperPerpsAccount.start(fixture_params(borrow_rate_pct_per_hour="0"), T0)
    assert a.open("SOL", PerpSide.LONG, M, T0).approved
    assert a.cash_usd == D(1000) - D(200) - D("0.36")
    a.close("SOL", {**M, "SOL": D(110)}, T0 + timedelta(hours=4), "TEST")
    # +10% on 600 = +60; fees 0.36 + 0.36.
    assert a.cash_usd == D(1000) + D(60) - D("0.72")
    assert a.realized_pnl_usd == D(60) - D("0.72")


def test_short_profits_when_price_falls() -> None:
    a = PaperPerpsAccount.start(fixture_params(borrow_rate_pct_per_hour="0"), T0)
    a.open("SOL", PerpSide.SHORT, M, T0)
    a.close("SOL", {**M, "SOL": D(90)}, T0, "TEST")
    assert a.cash_usd > D(1000)


def test_borrow_fees_accrue_hourly() -> None:
    a = PaperPerpsAccount.start(fixture_params(borrow_rate_pct_per_hour="0.01"), T0)
    a.open("SOL", PerpSide.LONG, M, T0)
    a.mark(M, T0 + timedelta(hours=10))
    assert a.positions["SOL"].borrow_fees_usd == D("0.60")  # 600 * 0.01% * 10h


def test_liquidation_loses_collateral_and_is_journaled() -> None:
    a = PaperPerpsAccount.start(fixture_params(), T0)
    a.open("SOL", PerpSide.LONG, M, T0)
    a.mark({**M, "SOL": D(60)}, T0 + timedelta(hours=4))
    assert "SOL" not in a.positions
    assert a.events[-1]["event"] == "LIQUIDATED"
    assert a.equity(M) == a.cash_usd


def test_signal_reversal_closes_then_opens() -> None:
    a = PaperPerpsAccount.start(fixture_params(), T0)
    a.apply_signal("SOL", PerpSide.LONG, M, T0)
    a.apply_signal("SOL", PerpSide.SHORT, M, T0 + timedelta(hours=4))
    assert a.positions["SOL"].side == PerpSide.SHORT
    a.apply_signal("SOL", None, M, T0 + timedelta(hours=8))
    assert "SOL" not in a.positions
    kinds = [e["event"] for e in a.events]
    assert kinds.count("OPENED") == 2 and kinds.count("CLOSED") == 2


def test_rejected_open_changes_nothing() -> None:
    a = PaperPerpsAccount.start(fixture_params(), T0)
    a.halted = True
    assert not a.open("SOL", PerpSide.LONG, M, T0).approved
    assert a.cash_usd == D(1000) and not a.positions
