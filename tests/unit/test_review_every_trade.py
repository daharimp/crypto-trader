"""Per-trade analysis, daily summary and drawdown alerts (ADR-045). No real API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from trader.assistant import daily as dl
from trader.assistant import trade_review as tr
from trader.assistant.trades import closed_trades, equity_snapshot
from trader.cli.main import app
from trader.perps import review_agents as ra
from trader.perps.trade_log import perps_trades

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def _ev(at: datetime, kind: str, **kw: Any) -> dict[str, Any]:
    return {"at_utc": at.isoformat(), "event": kind, **kw}


def _rows(symbol: str = "BTC/USD", tf: str = "4h") -> list[list[float]]:
    t0 = NOW - timedelta(days=5)
    out = []
    for i in range(30):
        c = 100.0 - i  # falling
        ms = int((t0 + i * timedelta(hours=4)).timestamp() * 1000)
        out.append([ms, c + 0.5, c + 1, c - 1, c, 1.0])
    return out


PERPS = [
    _ev(
        NOW - timedelta(days=3),
        "OPENED",
        market="BTC",
        side="short",
        entry="88",
        leverage="5",
        size_usd="500",
        collateral_usd="100",
        liquidation_price="118",
        fee_usd="0.3",
    ),
    _ev(NOW - timedelta(days=2), "STOP_MOVED", market="BTC", stop="96"),
    _ev(NOW - timedelta(days=2), "OPEN_REJECTED", market="BTC", reasons=["x"]),
    _ev(
        NOW - timedelta(days=1, hours=12),
        "CLOSED",
        market="BTC",
        side="short",
        exit="79",
        pnl_usd="50",
        fees_usd="0.7",
        reason="SIGNAL_CHANGED",
    ),
    _ev(
        NOW - timedelta(hours=10),
        "OPENED",
        market="ETH",
        side="long",
        entry="10",
        leverage="10",
        size_usd="1000",
        collateral_usd="100",
        liquidation_price="9.1",
    ),
    _ev(
        NOW - timedelta(hours=2),
        "LIQUIDATED",
        market="ETH",
        side="long",
        mark="9.1",
        collateral_lost_usd="100",
    ),
    _ev(
        NOW - timedelta(hours=1),
        "OPENED",
        market="SOL",
        side="long",
        entry="1",
        collateral_usd="10",
    ),
]


def test_perps_trades_pair_opens_with_closes_and_keep_context() -> None:
    trades = perps_trades(PERPS, "main")
    assert [t["market"] for t in trades] == ["BTC", "ETH"]  # SOL still open
    btc, eth = trades
    assert btc["net_pnl_usd"] == 49.0 and btc["return_on_collateral_pct"] == 49.0
    assert btc["exit_reason"] == "SIGNAL_CHANGED" and btc["hours_held"] == 36.0
    assert [e["event"] for e in btc["events_during_trade"]] == ["STOP_MOVED"]
    assert eth["net_pnl_usd"] == -100.0 and eth["exit_reason"] == "LIQUIDATED"
    assert perps_trades([], "main") == []


def _spot_state(root: Path, trades: list[dict[str, Any]], equity: str, hwm: str) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "session-paper-balanced.json").write_text(
        json.dumps(
            {
                "meta": {"equity_usd": equity},
                "ledger": {"cash": equity, "positions": {}, "trades": trades},
                "loss": {"hwm": hwm, "day_start": equity},
            }
        )
    )


def _spot_trade(opened: datetime, closed: datetime, pnl: str) -> dict[str, Any]:
    return {
        "instrument_id": "BTC-USD",
        "strategy_ids": ["sma_stance"],
        "opened_at": opened.isoformat(),
        "closed_at": closed.isoformat(),
        "quantity": "1",
        "entry_price": "95",
        "exit_price": "92",
        "pnl_usd": pnl,
    }


def test_spot_trades_and_equity_come_from_the_ledger(tmp_path: Path) -> None:
    assert closed_trades(tmp_path, "spot") == [] and equity_snapshot(tmp_path, "spot") is None
    _spot_state(
        tmp_path,
        [_spot_trade(NOW - timedelta(hours=9), NOW - timedelta(hours=3), "-3")],
        "880",
        "1000",
    )
    (t,) = closed_trades(tmp_path, "spot")
    assert t["market"] == "BTC" and t["side"] == "long" and t["return_on_cost_pct"] == -3.16
    snap = equity_snapshot(tmp_path, "spot")
    assert snap is not None and snap["drawdown_pct"] == 12.0
    with pytest.raises(ValueError):
        closed_trades(tmp_path, "nope")


def test_trade_facts_measure_excursions_for_a_short() -> None:
    btc = perps_trades(PERPS, "main")[0]
    facts = tr.build_trade_facts(btc, SHIPPED_CONFIGS, _rows, "4h", "trend_50_200")
    rows = facts["candles"]["rows"]
    assert rows and rows[0][0] < btc["opened_at_utc"] and len(rows) <= tr.MAX_BARS
    m = facts["measured"]
    assert m["best_move_for_pct"] > 0 > m["worst_move_against_pct"]
    assert m["best_on_collateral_pct"] == pytest.approx(m["best_move_for_pct"] * 5, abs=0.05)
    assert 0 < m["share_of_best_move_kept_pct"] <= 100

    def down(symbol: str, tf: str) -> list[list[float]]:
        raise OSError("offline")

    facts = tr.build_trade_facts(btc, SHIPPED_CONFIGS, down, "4h", None)
    assert "offline" in facts["candles"]["error"] and "error" in facts["measured"]


ANALYSIS = tr.TradeAnalysis(
    headline="Clean trend short",
    grade="good",
    entry_reason="trend down",
    exit_reason="trend flipped",
    stop_and_take_profit="stop never close",
    followed_rules=True,
    what_went_well=["rode the move"],
    what_to_improve=["gave back 3% before exit"],
)
SUMMARY = dl.DailySummary(headline="Quiet day", summary_markdown="Not much.", things_to_watch=[])


class FakeMessages:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers, self.calls = answers, []

    def parse(self, **kw: Any) -> SimpleNamespace:
        self.calls.append(kw)
        out = self.answers.get(kw["output_format"].__name__)
        if out == "refuse":
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)


def _client(**over: Any) -> SimpleNamespace:
    answers = {"TradeAnalysis": ANALYSIS, "DailySummary": SUMMARY, **over}
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(answers)))


def test_trade_report_renders_with_and_without_an_answer(tmp_path: Path) -> None:
    btc = perps_trades(PERPS, "main")[0]
    facts = tr.build_trade_facts(btc, SHIPPED_CONFIGS, _rows, "4h", None)
    settings = ra.load_assistant_settings(SHIPPED_CONFIGS)
    a = tr.analyze_trade(facts, _client(), settings)
    md = tr.save_trade_report(tmp_path, facts, a)
    text = md.read_text()
    assert "Clean trend short" in text and "SIGNAL_CHANGED" in text and "$49.00" in text
    assert json.loads(md.with_suffix(".json").read_text())["analysis"]["grade"] == "good"
    declined = tr.analyze_trade(facts, _client(TradeAnalysis="refuse"), settings)
    assert declined is None and "declined" in tr.render_trade(facts, None)
    bad = ANALYSIS.model_copy(update={"headline": "A risk-free win"})
    assert "Warning" in tr.render_trade(facts, bad)


def test_drawdown_alerts_fire_once_per_level_and_reset_on_recovery(tmp_path: Path) -> None:
    seen: dict[str, float] = {}
    _spot_state(tmp_path, [], "940", "1000")  # 6%
    assert len(dl.drawdown_alerts(tmp_path, ["spot", "main"], [5, 10, 15], seen)) == 1
    assert dl.drawdown_alerts(tmp_path, ["spot"], [5, 10, 15], seen) == []  # no repeat
    _spot_state(tmp_path, [], "880", "1000")  # 12%
    (line,) = dl.drawdown_alerts(tmp_path, ["spot"], [5, 10, 15], seen)
    assert "12.0%" in line and "10% alert" in line
    _spot_state(tmp_path, [], "990", "1000")  # recovered
    assert dl.drawdown_alerts(tmp_path, ["spot"], [5, 10, 15], seen) == [] and seen == {}
    assert dl.drawdown_alerts(tmp_path, ["spot"], [], seen) == []


def test_old_assistant_settings_still_load_with_new_features_off() -> None:
    raw = {
        "schema_version": "1.0.0",
        "kind": "ReviewAssistant",
        "model": "m",
        "max_tokens": 2000,
        "effort": {"default": "low"},
        "review_on_bad_day": True,
        "accounts": ["main"],
    }
    s = ra.AssistantSettings.model_validate(raw)
    assert not s.review_every_trade and not s.daily_summary and s.drawdown_alert_pct == []
    shipped = ra.load_assistant_settings(SHIPPED_CONFIGS)
    assert shipped.review_every_trade and "spot" in shipped.report_accounts


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", _rows)
    old = _spot_trade(NOW - timedelta(days=4), NOW - timedelta(days=3), "5")
    new = _spot_trade(NOW - timedelta(hours=9), NOW - timedelta(hours=3), "-3")
    _spot_state(tmp_path, [old, new], "880", "1000")
    return tmp_path


def test_watch_reviews_only_new_trades_writes_daily_once_and_alerts(data: Path) -> None:
    from trader.cli.review import _load_cursor, watch_once

    settings = ra.load_assistant_settings(SHIPPED_CONFIGS).model_copy(
        update={"review_on_bad_day": False, "report_accounts": ["spot", "main"]}
    )
    client, sent = _client(), []
    cur = _load_cursor(data / "state" / "review-assistant.json")
    watch_once(cur, client, settings, sent.append, NOW)
    names = [c["output_format"].__name__ for c in client.beta.messages.calls]
    assert names == ["TradeAnalysis", "DailySummary"]  # the 3-day-old trade is not reviewed
    assert any("spot long BTC closed $-3.00: Clean trend short" in s for s in sent)
    assert any(s.startswith("daily 2026-11-21: Quiet day") for s in sent)
    assert any(s.startswith("DRAWDOWN spot") for s in sent)
    assert (data / "reports" / "daily-2026-11-21.md").exists()
    assert list((data / "reports" / "trades" / "spot").glob("*.md"))
    sent.clear()
    watch_once(cur, client, settings, sent.append, NOW + timedelta(minutes=1))
    assert sent == [] and len(client.beta.messages.calls) == 2


def test_cli_trade_and_daily(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ra.KEY_ENV, raising=False)
    r = CliRunner().invoke(
        app, ["review", "trade", "--account", "spot", "--dry-run", "--last", "2"]
    )
    assert r.exit_code == 0 and len(json.loads(r.output)) == 2
    assert CliRunner().invoke(app, ["review", "trade", "--account", "x"]).exit_code == 2
    assert CliRunner().invoke(app, ["review", "trade", "--account", "spot"]).exit_code == 3
    r = CliRunner().invoke(app, ["review", "trade", "--account", "main"])
    assert "no closed trades" in r.output
    r = CliRunner().invoke(app, ["review", "daily", "--day", "2026-11-22", "--dry-run"])
    accts = {a["account"]: a for a in json.loads(r.output)["accounts"]}
    assert accts["spot"]["trades_closed"] == 1 and accts["main"]["ran"] is False
    assert "no matching reports" in CliRunner().invoke(app, ["review", "show", "--daily"]).output
