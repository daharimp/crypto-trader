"""A change of settings is written into the run's own history (ADR-056).

Values are TEST FIXTURES with no market meaning.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from tests.perps_support import fixture_params
from trader.perps.account_state import settings_change, settings_record
from trader.perps.params import PerpsParams
from trader.perps.session import NOTIFY, PerpsSession, SessionStateError, describe

T0 = datetime(2026, 1, 1, tzinfo=UTC)
H4 = timedelta(hours=4)
V1 = fixture_params()
# The same account after an owner's change: a smaller size, a cooldown, and the version.
V2 = replace(V1, version=2, max_collateral_per_position_pct=D(10), cooldown_after_loss_hours=D(4))
CHANGED = {
    "max_collateral_per_position_pct": {"from": "20", "to": "10"},
    "cooldown_after_loss_hours": {"from": None, "to": "4"},
}


class Feed:
    """A falling market, one more completed 4h candle each time ``step`` is called."""

    def __init__(self) -> None:
        self.closes = [100 * 0.99**i for i in range(61)]

    def __call__(self, symbol: str, timeframe: str) -> list[list[float]]:
        rows, prev = [], self.closes[0]
        for i, c in enumerate(self.closes):
            ms = int((T0 + i * H4).timestamp() * 1000)
            rows.append([ms, prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 1.0])
            prev = c
        return rows

    def now(self) -> datetime:
        return T0 + (len(self.closes) - 1) * H4 + timedelta(minutes=2)

    def step(self) -> datetime:
        self.closes.append(self.closes[-1] * 0.99)
        return self.now()


def _session(tmp: Path, feed: Feed, params: PerpsParams, sent: list[str]) -> PerpsSession:
    return PerpsSession(params, feed, tmp / "state.json", tmp / "events.jsonl", notify=sent.append)


def _kinds(events: list[dict[str, object]]) -> list[object]:
    return [e["event"] for e in events]


# --- the record and the comparison -----------------------------------------------------------
def test_record_holds_every_setting_but_the_markets() -> None:
    record = settings_record(replace(V2, take_profits=((D(4), D(25)), (D(8), D("75.0")))))
    assert "markets" not in record and record["version"] == 2
    assert record["max_collateral_per_position_pct"] == "10"
    assert record["cooldown_after_loss_hours"] == "4"
    assert record["min_collateral_per_position_pct"] is None  # an option that is off
    assert record["take_profits"] == [["4", "25"], ["8", "75"]]
    assert json.loads(json.dumps(record)) == record  # it is saved in the state file


def test_change_lists_each_value_that_moved_and_updates_the_saved_facts() -> None:
    meta = {"config_version": 1, "settings": settings_record(V1)}
    assert settings_change(meta, V2) == {"from_version": 1, "to_version": 2, "changed": CHANGED}
    assert meta == {"config_version": 2, "settings": settings_record(V2)}
    assert settings_change(meta, V2) is None  # nothing since


def test_the_same_number_written_differently_is_not_a_change() -> None:
    meta = {"config_version": 1, "settings": settings_record(V1)}
    same = replace(V1, max_collateral_per_position_pct=D("20.00"), daily_loss_limit_pct=D("5.0"))
    assert settings_change(meta, same) is None


def test_a_raised_version_alone_and_a_value_without_one_are_both_reported() -> None:
    meta = {"config_version": 1, "settings": settings_record(V1)}
    only_version = settings_change(meta, replace(V1, version=2))
    assert only_version == {"from_version": 1, "to_version": 2, "changed": {}}
    # A value edited without raising the version breaks the rule; the history shows it.
    quiet = settings_change(meta, replace(V1, version=2, max_open_positions=2))
    assert quiet == {
        "from_version": 2,
        "to_version": 2,
        "changed": {"max_open_positions": {"from": 3, "to": 2}},
    }


def test_a_run_saved_before_the_record_only_knows_its_version() -> None:
    old = {"config_version": 1}
    assert settings_change(old, V1) is None and old["settings"] == settings_record(V1)
    older = {"config_version": 1}
    assert settings_change(older, V2) == {"from_version": 1, "to_version": 2}
    # A setting that newer code records and older code did not, still off: not a change.
    meta = {"config_version": 1, "settings": settings_record(V1)}
    del meta["settings"]["min_collateral_per_position_pct"]
    assert settings_change(meta, V1) is None


# --- the session -----------------------------------------------------------------------------
def test_a_restart_with_new_settings_journals_the_change_once(tmp_path: Path) -> None:
    feed, sent = Feed(), list[str]()
    first = _session(tmp_path, feed, V1, sent)
    assert _kinds(first.cycle(feed.now())) == ["ACCOUNT_STARTED", "OPENED", "OPENED"]
    assert first.acct is not None and first.meta["settings"] == settings_record(V1)
    posted = first.acct.positions["SOL"].collateral_usd  # 20% of the account, under v1

    changed = _session(tmp_path, feed, V2, sent)
    events = changed.cycle(feed.step())
    assert _kinds(events)[0] == "SETTINGS_CHANGED" and _kinds(events).count("SETTINGS_CHANGED") == 1
    assert events[0] == {
        "at_utc": feed.now().isoformat(),
        "event": "SETTINGS_CHANGED",
        "from_version": 1,
        "to_version": 2,
        "changed": CHANGED,
    }
    # The run continues: the position opened under v1 keeps its size.
    assert changed.acct is not None and changed.acct.positions["SOL"].collateral_usd == posted
    assert changed.meta["cycles"] == 2 and changed.meta["config_version"] == 2
    saved = json.loads((tmp_path / "state.json").read_text())["meta"]
    assert saved["settings"] == settings_record(V2) and saved["config_version"] == 2
    assert sent[-1] == (
        "settings changed, version 1 to 2: max_collateral_per_position_pct from 20 to 10; "
        "cooldown_after_loss_hours from not set to 4. The run continues; nothing is reset"
    )
    # The next bar, and a restart under the same settings, say nothing more.
    assert "SETTINGS_CHANGED" not in _kinds(changed.cycle(feed.step()))
    again = _session(tmp_path, feed, V2, sent)
    assert "SETTINGS_CHANGED" not in _kinds(again.cycle(feed.step()))
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert sum('"SETTINGS_CHANGED"' in line for line in lines) == 1


def test_unchanged_settings_and_an_older_saved_run_stay_quiet(tmp_path: Path) -> None:
    feed, sent = Feed(), list[str]()
    _session(tmp_path, feed, V1, sent).cycle(feed.now())
    # A run saved by code from before the record: the state file has no ``settings``.
    state = json.loads((tmp_path / "state.json").read_text())
    del state["meta"]["settings"]
    (tmp_path / "state.json").write_text(json.dumps(state))
    resumed = _session(tmp_path, feed, V1, sent)
    assert "SETTINGS_CHANGED" not in _kinds(resumed.cycle(feed.step()))
    assert json.loads((tmp_path / "state.json").read_text())["meta"]["settings"] == (
        settings_record(V1)
    )
    assert not any(text.startswith("settings changed") for text in sent)


def test_an_older_saved_run_under_a_new_version_reports_the_versions(tmp_path: Path) -> None:
    feed, sent = Feed(), list[str]()
    _session(tmp_path, feed, V1, sent).cycle(feed.now())
    state = json.loads((tmp_path / "state.json").read_text())
    del state["meta"]["settings"]
    (tmp_path / "state.json").write_text(json.dumps(state))
    events = _session(tmp_path, feed, V2, sent).cycle(feed.step())
    assert events[0]["event"] == "SETTINGS_CHANGED" and "changed" not in events[0]
    assert (events[0]["from_version"], events[0]["to_version"]) == (1, 2)
    assert sent[-1] == (
        "settings changed, version 1 to 2: this run did not record its earlier values. "
        "The run continues; nothing is reset"
    )


def test_a_cycle_without_a_new_bar_writes_nothing_and_the_change_is_not_lost(
    tmp_path: Path,
) -> None:
    feed, sent = Feed(), list[str]()
    _session(tmp_path, feed, V1, sent).cycle(feed.now())
    before = (tmp_path / "state.json").read_text()
    changed = _session(tmp_path, feed, V2, sent)
    # Restarted inside the same candle: no bar closed, so nothing is saved or journaled yet.
    assert changed.cycle(feed.now() + timedelta(minutes=5)) == []
    assert (tmp_path / "state.json").read_text() == before
    assert _kinds(changed.cycle(feed.step()))[0] == "SETTINGS_CHANGED"


def test_another_market_list_is_not_a_settings_change_it_needs_a_new_run(tmp_path: Path) -> None:
    feed, sent = Feed(), list[str]()
    _session(tmp_path, feed, V1, sent).cycle(feed.now())
    fewer = replace(V2, markets={"SOL": V1.markets["SOL"]})
    with pytest.raises(SessionStateError, match="different signal, timeframe, or market list"):
        _session(tmp_path, feed, fewer, sent)


def test_the_alert_text() -> None:
    assert "SETTINGS_CHANGED" in NOTIFY
    event = {"event": "SETTINGS_CHANGED", "from_version": 2, "to_version": 3, "changed": {}}
    assert describe(event) == (
        "settings changed, version 2 to 3: no value changed. The run continues; nothing is reset"
    )
    off = {**event, "changed": {"cooldown_after_loss_hours": {"from": "4", "to": None}}}
    assert "cooldown_after_loss_hours from 4 to not set" in describe(off)
