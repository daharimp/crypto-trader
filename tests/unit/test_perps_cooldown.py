"""A market rests after a losing trade (ADR-053): optional, off unless the file sets it.

Values below are TEST FIXTURES with no market meaning, except where the shipped config files
are read on purpose.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SHIPPED_CONFIGS
from tests.perps_support import T0, fixture_file, fixture_params, no_stop_params
from trader.perps.math import PerpSide
from trader.perps.params import (
    COOLDOWN_KEY,
    PerpsConfigFile,
    PerpsConfigUnresolvedError,
    load_perps_params,
    resolve,
    settings_summary,
)
from trader.perps.session import NOTIFY, PerpsSession, _dump_account, _load_account
from trader.perps.simulator import PaperPerpsAccount

LONG = PerpSide.LONG
M = {"SOL": D(100), "ETH": D(2000)}
H = timedelta(hours=1)
SHIPPED = ("jupiter.yaml", "jupiter-degen.yaml", "jupiter-spot-perps.yaml", "top10.yaml")
LADDER = {
    "stop_loss_pct_of_collateral": "30",
    "take_profit_1_r": "1",
    "take_profit_1_close_pct": "25",
    "take_profit_2_r": "2",
    "take_profit_2_close_pct": "25",
    "take_profit_3_r": "3",
}


def _account(hours: str = "12", **overrides: str) -> PaperPerpsAccount:
    """An account with a SOL long opened at 100 at T0; ``hours=""`` leaves the setting out."""
    a = PaperPerpsAccount.start(fixture_params(**{COOLDOWN_KEY: hours, **overrides}), T0)
    assert a.open("SOL", LONG, M, T0).approved
    return a


def _kinds(a: PaperPerpsAccount) -> list[str]:
    return [e["event"] for e in a.events]


def _exit(a: PaperPerpsAccount, price: str, at: datetime, bar: datetime | None = None) -> None:
    """The signal goes flat: SOL closes at ``price``."""
    a.apply_signal("SOL", None, {**M, "SOL": D(price)}, at, bar)


# --- the setting -----------------------------------------------------------------------------
def test_cooldown_is_off_unless_a_file_sets_it() -> None:
    assert fixture_params().cooldown_after_loss_hours is None
    assert settings_summary(fixture_params())["cooldown_after_loss_hours"] is None
    for name in SHIPPED:
        # Reason: no account has an owner-approved length yet; none may get one by default.
        assert load_perps_params(SHIPPED_CONFIGS, name).cooldown_after_loss_hours is None


@pytest.mark.parametrize("hours", ["0.5", "4", "12", "168"])
def test_an_approved_length_resolves(hours: str) -> None:
    p = fixture_params(**{COOLDOWN_KEY: hours})
    assert p.cooldown_after_loss_hours == D(hours)
    assert settings_summary(p)["cooldown_after_loss_hours"] == hours


@pytest.mark.parametrize(("bad", "why"), [("0", "positive"), ("-4", "positive"), ("169", "most")])
def test_a_length_outside_its_bounds_is_refused(bad: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        fixture_params(**{COOLDOWN_KEY: bad})


def test_a_tbd_length_fails_closed() -> None:
    f = fixture_file()
    f["risk"][COOLDOWN_KEY] = {"value": "TBD", "status": "unresolved", "ref": "UD-34"}
    with pytest.raises(PerpsConfigUnresolvedError) as exc:
        resolve(PerpsConfigFile.model_validate(f))
    assert exc.value.keys == [f"risk.{COOLDOWN_KEY}"] and exc.value.refs == ["UD-34"]


def test_a_misspelled_risk_setting_is_refused() -> None:
    # Reason: before ADR-053 an unknown key was ignored, so a typo switched a protection off.
    with pytest.raises(ValueError, match="unknown risk settings.*cooldown_after_loss_hour'"):
        fixture_params(cooldown_after_loss_hour="12")


# --- the account -----------------------------------------------------------------------------
def test_a_losing_trade_rests_its_market_until_the_wait_ends() -> None:
    a = _account("12")
    _exit(a, "95", T0 + H)
    assert a.cooldown_until == {"SOL": T0 + 13 * H}
    assert _kinds(a)[-2:] == ["CLOSED", "COOLDOWN_STARTED"]
    assert a.events[-1]["market"] == "SOL"
    assert a.events[-1]["until_utc"] == (T0 + 13 * H).isoformat()
    before = len(a.events)
    for hour in (2, 6, 12):
        a.apply_signal("SOL", LONG, M, T0 + hour * H)
    # Reason: a refused open says nothing (no OPEN_REJECTED each hour); the start was journaled.
    assert "SOL" not in a.positions and len(a.events) == before
    a.apply_signal("SOL", LONG, M, T0 + 13 * H)  # the wait ends exactly here
    assert a.positions["SOL"].opened_at == T0 + 13 * H and a.cooldown_until == {}


def test_other_markets_trade_while_one_rests() -> None:
    a = _account("12")
    _exit(a, "95", T0 + H)
    a.apply_signal("ETH", LONG, M, T0 + 2 * H)
    assert set(a.positions) == {"ETH"}


def test_a_winning_trade_starts_no_wait() -> None:
    a = _account("12")
    _exit(a, "110", T0 + H)
    a.apply_signal("SOL", LONG, M, T0 + 2 * H)
    assert a.cooldown_until == {} and "COOLDOWN_STARTED" not in _kinds(a)
    assert a.positions["SOL"].opened_at == T0 + 2 * H


def test_a_gain_smaller_than_the_fees_counts_as_a_loss() -> None:
    a = _account("12")
    p = a.positions["SOL"]
    fees = p.size_usd * 12 / 10_000  # fixture: 6 bps to open and 6 to close
    gain = p.size_usd * D("0.0005")
    assert 0 < gain < fees
    _exit(a, "100.05", T0)
    assert a.cooldown_until == {"SOL": T0 + 12 * H}


def test_a_trade_that_ends_exactly_even_starts_no_wait() -> None:
    a = _account("12")
    assert a.positions["SOL"].realized_usd == D("-0.36")  # the opening fee on $600
    _exit(a, "100.12", T0)  # +0.72 before fees, 0.36 to open and 0.36 to close
    assert a.realized_pnl_usd == 0 and a.cooldown_until == {}


def test_the_wait_is_counted_from_the_candle_not_from_the_fill() -> None:
    bar, fill = T0 + 4 * H, T0 + 4 * H + timedelta(minutes=3)
    a = _account("4")
    _exit(a, "95", fill, bar)
    assert a.cooldown_until == {"SOL": bar + 4 * H}
    assert a.events[-2]["at_utc"] == fill.isoformat()  # the close keeps the fill's time
    a.apply_signal("SOL", LONG, M, bar + 3 * H + timedelta(minutes=3), bar + 3 * H)
    assert "SOL" not in a.positions
    # Reason: by the fill's clock this decision would still be 3 minutes early every hour.
    a.apply_signal("SOL", LONG, M, bar + 4 * H + timedelta(minutes=2), bar + 4 * H)
    assert "SOL" in a.positions


def test_a_stop_late_in_the_day_no_longer_reopens_after_midnight() -> None:
    def stopped_at_22(hours: str) -> PaperPerpsAccount:
        a = _account(hours, stop_loss_pct_of_collateral="30")
        a.mark({**M, "SOL": D(85)}, T0 + 22 * H, opens={"SOL": D(99)}, closes={"SOL": D(86)})
        assert _kinds(a)[2] == "CLOSED" and a.events[2]["reason"] == "STOP_LOSS"
        a.mark(M, T0 + 24 * H)  # the day rolls; the same-day rule (ADR-038) lets go
        assert a.stopped_today == set()
        a.apply_signal("SOL", LONG, M, T0 + 26 * H)
        return a

    assert "SOL" in stopped_at_22("").positions  # without the setting: straight back in
    resting = stopped_at_22("12")
    assert "SOL" not in resting.positions and resting.cooldown_until == {"SOL": T0 + 34 * H}
    resting.apply_signal("SOL", LONG, M, T0 + 34 * H)
    assert "SOL" in resting.positions


def test_take_profits_count_toward_the_whole_trade() -> None:
    a = PaperPerpsAccount.start(fixture_params(**{COOLDOWN_KEY: "12", **LADDER}), T0)
    assert a.open("SOL", LONG, M, T0).approved
    # TP1 at 110 closes a quarter and moves the stop to breakeven; the next bar falls to it.
    a.mark({**M, "SOL": D(105)}, T0 + 4 * H, favorable={"SOL": D(111)}, closes={"SOL": D(108)})
    assert a.positions["SOL"].realized_usd > 0
    a.mark({**M, "SOL": D(99)}, T0 + 8 * H, opens={"SOL": D(107)}, closes={"SOL": D(99)})
    kinds = _kinds(a)
    assert kinds.count("TAKE_PROFIT") == 1 and kinds[-1] == "CLOSED"
    # Reason: the last piece alone paid a fee for no gain; the trade as a whole made money.
    assert a.cooldown_until == {}


def test_a_liquidation_starts_the_wait() -> None:
    a = PaperPerpsAccount.start(no_stop_params(**{COOLDOWN_KEY: "12"}), T0)
    assert a.open("SOL", LONG, M, T0).approved
    a.mark({**M, "SOL": D(50)}, T0 + 4 * H)
    assert _kinds(a)[-2:] == ["LIQUIDATED", "COOLDOWN_STARTED"]
    assert a.cooldown_until == {"SOL": T0 + 16 * H}


def test_without_the_setting_nothing_changes() -> None:
    a = _account("")
    _exit(a, "95", T0 + H)
    a.apply_signal("SOL", LONG, M, T0 + 2 * H)
    assert _kinds(a) == ["ACCOUNT_STARTED", "OPENED", "CLOSED", "OPENED"]
    assert a.cooldown_until == {}


# --- saved state -----------------------------------------------------------------------------
def test_the_wait_and_the_running_result_survive_a_restart() -> None:
    a = _account("12")
    _exit(a, "95", T0 + H)
    a.apply_signal("ETH", LONG, M, T0 + H)
    b = _load_account(a.params, _dump_account(a))
    assert b.cooldown_until == {"SOL": T0 + 13 * H}
    assert b.positions["ETH"].realized_usd == a.positions["ETH"].realized_usd < 0
    b.apply_signal("SOL", LONG, M, T0 + 2 * H)
    assert "SOL" not in b.positions


def test_state_saved_before_the_setting_existed_still_loads() -> None:
    a = _account("12")
    old = _dump_account(a)
    del old["cooldown_until"], old["positions"]["SOL"]["realized_usd"]
    b = _load_account(a.params, old)
    assert b.cooldown_until == {} and b.positions["SOL"].realized_usd == 0


def test_switching_the_setting_off_ends_saved_waits() -> None:
    a = _account("12")
    _exit(a, "95", T0 + H)
    b = _load_account(fixture_params(), _dump_account(a))
    b.apply_signal("SOL", LONG, M, T0 + 2 * H)
    assert b.cooldown_until == {} and "SOL" in b.positions


# --- the session -----------------------------------------------------------------------------
H4 = timedelta(hours=4)
# Completed closes at the decision -> side. Long for two bars, flat for one, then long again.
SCRIPT = {21: LONG, 22: LONG}


def _signal(closes: list[D]) -> PerpSide | None:
    return SCRIPT.get(len(closes), LONG if len(closes) >= 24 else None)


class _Feed:
    """4h candles that fall half a percent a bar from the twenty-first on."""

    def __init__(self) -> None:
        self.closes = [100.0] * 22

    def __call__(self, symbol: str, timeframe: str) -> list[list[float]]:
        rows, prev = [], self.closes[0]
        for i, c in enumerate(self.closes):
            ms = int((T0 + i * H4).timestamp() * 1000)
            rows.append([ms, prev, max(prev, c) * 1.001, min(prev, c) * 0.999, c, 1.0])
            prev = c
        return rows

    def step(self) -> datetime:
        """Add one bar; returns the wall time two minutes into the next candle."""
        self.closes.append(self.closes[-1] * 0.995)
        return self.bar_close() + timedelta(minutes=2)

    def bar_close(self) -> datetime:
        return T0 + (len(self.closes) - 1) * H4


def _session(tmp: Path, feed: _Feed, hours: str) -> PerpsSession:
    return PerpsSession(
        fixture_params(**{COOLDOWN_KEY: hours}),
        feed,
        tmp / "state.json",
        tmp / "events.jsonl",
        signal=_signal,
        signal_name="scripted",
    )


def _run(tmp: Path, hours: str, restart: bool = False) -> list[tuple[datetime, str, Any]]:
    """Drive five bars after the first cycle; returns (bar close, event, market) per event."""
    feed = _Feed()
    s = _session(tmp, feed, hours)
    seen = [(feed.bar_close(), e["event"], e.get("market")) for e in s.cycle(T0 + 21 * H4 + H)]
    for n in range(5):
        now = feed.step()
        if n == 1:
            # Reason: the cycle that closes the trade runs late (say after an outage), so a
            # wait counted from the fill would end later than one counted from the candle.
            now += timedelta(minutes=30)
        if restart and n == 3:
            s = _session(tmp, feed, hours)
        seen += [(feed.bar_close(), e["event"], e.get("market")) for e in s.cycle(now)]
    return seen


def _opened(seen: list[tuple[datetime, str, Any]], market: str) -> list[datetime]:
    return [at for at, kind, m in seen if kind == "OPENED" and m == market]


def test_session_reopens_the_next_bar_without_the_setting(tmp_path: Path) -> None:
    seen = _run(tmp_path, "")
    closed = next(at for at, kind, _ in seen if kind == "CLOSED")
    assert closed == T0 + 23 * H4
    assert _opened(seen, "SOL") == [T0 + 21 * H4, closed + H4]
    assert all(kind != "COOLDOWN_STARTED" for _, kind, _ in seen)


@pytest.mark.parametrize("restart", [False, True])
def test_session_waits_in_candle_time_and_through_a_restart(tmp_path: Path, restart: bool) -> None:
    seen = _run(tmp_path, "12", restart)
    closed = T0 + 23 * H4
    assert [m for at, kind, m in seen if kind == "COOLDOWN_STARTED"] == ["SOL", "ETH"]
    # Reason: the closing cycle ran 30 minutes after its candle; a wait counted from that fill
    # would still be running at the 12-hour decision and cost a whole extra bar.
    assert _opened(seen, "SOL") == [T0 + 21 * H4, closed + 3 * H4]
    assert _opened(seen, "ETH") == [T0 + 21 * H4, closed + 3 * H4]


def test_a_started_wait_is_journaled_but_is_not_a_phone_alert(tmp_path: Path) -> None:
    assert "COOLDOWN_STARTED" not in NOTIFY
    _run(tmp_path, "12")
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum('"COOLDOWN_STARTED"' in line for line in lines) == 2
