"""Debate reviews and review memory (ADR-052). No network: the HTTP post and candles are faked."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SHIPPED_CONFIGS
from tests.unit.test_free_trade_review import FakePost
from tests.unit.test_review_every_trade import ANALYSIS, NEW_ID, NOW, data  # noqa: F401
from trader.assistant import debate as db
from trader.assistant import free_review as fr
from trader.assistant import review_memory as rm
from trader.perps import review_agents as ra

VERDICT = db.DebateVerdict(
    **ANALYSIS.model_dump(),
    process_scores=db.ProcessScores(entry=4, stop_placement=2, exit_management=3, rule_adherence=5),
    bull_points_that_held=["entry matched the trend rule"],
    bear_points_that_held=["stop sat inside one normal daily move"],
    stop_call="too_tight",
    exit_call="about_right",
    lesson="Stops inside one daily move get hit by noise.",
)
GOOD = json.dumps(VERDICT.model_dump())


def _cfg(**over: Any) -> ra.FreeTradeReviews:
    base = ra.load_assistant_settings(SHIPPED_CONFIGS).free_trade_reviews
    return base.model_copy(update=over)


def _facts(t: dict[str, Any]) -> dict[str, Any]:
    return {"trade": t, "measured": {}, "candles": {"timeframe": "4h", "rows": []}}


def test_shipped_settings_turn_the_debate_on_with_two_different_first_models() -> None:
    cfg = _cfg()
    assert cfg.debate and cfg.daily_call_budget < 50 and cfg.lookback_hours == 48
    assert cfg.models_for("bull")[0] != cfg.models_for("bear")[0]
    assert cfg.debate_calls() == 4 and cfg.single_calls() == 2
    assert ra.FreeTradeReviews().debate is False  # older files keep the single review
    assert ra.FreeTradeReviews(models=["m"]).models_for("judge") == ["m"]  # falls back


def test_quadrant_grades_process_not_outcome() -> None:
    assert db.quadrant("good", -50) == "sound process, bad luck"
    assert db.quadrant("acceptable", 10) == "sound process, good result"
    assert db.quadrant("poor", 10) == "poor process, lucky"
    assert db.quadrant("poor", None) == "poor process, deserved loss"


def test_debate_runs_bull_bear_judge_and_remembers_the_verdict(data: Path) -> None:  # noqa: F811
    post, sent = FakePost("1. rode the trend", "1. stop too close", GOOD), []  # type: ignore[var-annotated]
    cur: dict[str, Any] = {"free_done": [], "free_calls": {}}
    rv = fr.FreeReviewer("k", _cfg(), post)
    assert fr.run_pass(cur, rv, data, ["spot"], NOW, _facts, sent.append) == 1
    assert cur["free_calls"] == {NOW.date().isoformat(): 3}
    bull, bear, judge = (c["body"] for c in post.calls)
    assert bull["models"] == _cfg().bull_models and bear["models"] == _cfg().bear_models
    assert "bull advocate" in bull["messages"][0]["content"]
    assert "JSON Schema" not in bull["messages"][0]["content"]  # free text, nothing to break
    judged = json.loads(judge["messages"][1]["content"])
    assert judged["arguments"] == {"bull": "1. rode the trend", "bear": "1. stop too close"}
    assert "past_reviews" in judged and "JSON Schema" in judge["messages"][0]["content"]
    assert sent[0].endswith("[free debate]")
    (md,) = (data / "reports" / "trades" / "spot").glob("*.md")
    text = md.read_text()
    assert "How the trade was run" in text and "Sound process, bad luck" in text
    assert "stop placement 2" in text and "Bear argument" in text
    saved = json.loads(md.with_suffix(".json").read_text())
    assert saved["verdict"]["quadrant"] == "sound process, bad luck"
    assert saved["debate"]["arguments"]["bear"] == "1. stop too close"
    assert saved["past_reviews"]["scorecard"]["stop_call"] == {"checked": 0, "right": 0}
    (entry,) = rm.load_memory(data / "reports")
    assert entry["key"] == f"spot/{NEW_ID}" and entry["stop_call"] == "too_tight"
    assert entry["follow_up"] is None
    assert "Stops inside one daily move" in (data / "reports/trades/lessons.md").read_text()


def test_bad_verdict_keeps_the_arguments_and_remembers_nothing(data: Path) -> None:  # noqa: F811
    post = FakePost(OSError("429"), "bear says no", "junk", "still junk", "junk", "junk")
    cur: dict[str, Any] = {"free_done": [], "free_calls": {}}
    rv = fr.FreeReviewer("k", _cfg(), post)
    assert fr.run_pass(cur, rv, data, ["spot"], NOW, _facts, lambda s: None) == 1
    # 4 for the debate, then 2 for the single review it falls back to (failed calls count)
    assert cur["free_calls"][NOW.date().isoformat()] == 6
    (md,) = (data / "reports" / "trades" / "spot").glob("*.md")
    assert "Review skipped: no valid answer" in md.read_text()
    assert "single review: no valid answer" in md.read_text()
    assert "(no argument: request failed" in md.read_text() and "bear says no" in md.read_text()
    assert rm.load_memory(data / "reports") == []


def test_failed_debate_falls_back_to_a_single_review(data: Path) -> None:  # noqa: F811
    # The 2026-11-27 top10 DOGE case: empty bull, error-object bear, judge rejected twice.
    single = json.dumps(ANALYSIS.model_dump())
    post = FakePost("", ValueError("error reply"), OSError("400"), OSError("400"), single)
    cur: dict[str, Any] = {"free_done": [], "free_calls": {}}
    sent: list[str] = []
    rv = fr.FreeReviewer("k", _cfg(), post)
    assert fr.run_pass(cur, rv, data, ["spot"], NOW, _facts, sent.append) == 1
    assert (
        cur["free_calls"][NOW.date().isoformat()] == 5
    )  # 4 for the debate, 1 for the single review
    assert sent[0].endswith("[free model]") and "review skipped" not in sent[0]
    saved = json.loads(next((data / "reports" / "trades" / "spot").glob("*.json")).read_text())
    assert saved["skipped"] is None and saved["reviewer"] == "m/free-a:free"
    assert "(no argument: empty answer" in saved["debate"]["arguments"]["bull"]  # kept
    assert rm.load_memory(data / "reports") == []  # a single review is not a verdict


def test_failed_debate_skips_the_fallback_when_the_budget_is_spent(
    data: Path,  # noqa: F811
) -> None:
    post = FakePost("", "", "junk", "junk")
    cur: dict[str, Any] = {"free_done": [], "free_calls": {NOW.date().isoformat(): 40}}
    rv = fr.FreeReviewer("k", _cfg(), post)
    assert fr.run_pass(cur, rv, data, ["spot"], NOW, _facts, lambda s: None) == 1
    assert len(post.calls) == 4 and cur["free_calls"][NOW.date().isoformat()] == 44


def test_budget_rations_debates_so_every_trade_gets_a_review(
    data: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trades = [
        {
            "account": "main",
            "trade_id": str(i),
            "closed_at_utc": NOW.isoformat(),
            "side": "long",
            "market": "BTC",
        }
        for i in range(3)
    ]
    monkeypatch.setattr(fr, "due_trades", lambda *a: trades)
    monkeypatch.setattr(fr, "save_trade_report", lambda *a, **k: None)
    single = json.dumps(ANALYSIS.model_dump())
    # 8 left: a debate (up to 4) still leaves 2 single reviews (2 each) for the other two;
    # it used 3, so the second gets a single review (1 used), and the last fits a debate.
    post = FakePost("bull", "bear", GOOD, single, "bull", "bear", GOOD)
    sent: list[str] = []
    cur: dict[str, Any] = {"free_done": [], "free_calls": {NOW.date().isoformat(): 37}}
    rv = fr.FreeReviewer("k", _cfg(), post)
    assert fr.run_pass(cur, rv, data, ["main"], NOW, _facts, sent.append) == 3
    assert [s.rsplit("[", 1)[1] for s in sent] == ["free debate]", "free model]", "free debate]"]
    assert cur["free_calls"][NOW.date().isoformat()] == 44  # never past the budget
    # 1 left: not even a single review fits, so the trades wait for tomorrow.
    cur = {"free_done": [], "free_calls": {NOW.date().isoformat(): 44}}
    assert fr.run_pass(cur, rv, data, ["main"], NOW, _facts, sent.append) == 0
    assert cur["free_done"] == []


def _entry(**over: Any) -> dict[str, Any]:
    e = {
        "key": "main/1",
        "account": "main",
        "market": "BTC",
        "side": "short",
        "timeframe": "4h",
        "closed_at_utc": (NOW - timedelta(days=2)).isoformat(),
        "exit": 100.0,
        "exit_reason": "STOP_LOSS",
        "net_pnl_usd": -30.0,
        "grade": "acceptable",
        "quadrant": "sound process, bad luck",
        "stop_call": "too_tight",
        "exit_call": "unclear",
        "lesson": "x",
        "follow_up": None,
    }
    return e | over


def _after(closes: list[float], start: datetime) -> list[list[float]]:
    return [
        [int((start + i * timedelta(hours=4)).timestamp() * 1000), c, c + 0.5, c - 0.5, c, 1.0]
        for i, c in enumerate(closes)
    ]


def test_follow_up_marks_calls_right_or_wrong_from_the_price_after_exit() -> None:
    closed = NOW - timedelta(days=2)
    # A short stopped at 100, then the price fell to 97: the stop gave up a move that came
    # (3% the trade's way), so "too tight" was right.
    e = _entry()
    mem = [e]
    n = rm.follow_up(mem, lambda s, tf: _after([99, 98, 98, 97, 97, 97], closed), 6, NOW)
    assert n == 1 and e["follow_up"]["end_move_pct"] == 3.0
    assert e["stop_call_result"] == "right" and e["exit_call_result"] == "not checkable"
    # The same call when the price kept going against the short: wrong.
    e2 = _entry()
    rm.follow_up([e2], lambda s, tf: _after([101, 102, 103, 103, 104, 104], closed), 6, NOW)
    assert e2["stop_call_result"] == "wrong"
    # A tiny move proves nothing.
    e3 = _entry(stop_call="about_right", exit_call="too_early", exit_reason="SIGNAL_CHANGED")
    rm.follow_up([e3], lambda s, tf: _after([100.2] * 6, closed), 6, NOW)
    assert e3["stop_call_result"] == "not a stop exit" and e3["exit_call_result"] == "unclear"
    sc = rm.scorecard([e, e2, e3])
    assert sc["stop_call"] == {"checked": 2, "right": 1}


def test_follow_up_waits_for_candles_and_survives_outages() -> None:
    recent = _entry(closed_at_utc=(NOW - timedelta(hours=8)).isoformat())
    assert rm.follow_up([recent], lambda s, tf: [], 6, NOW) == 0 and recent["follow_up"] is None

    def boom(s: str, tf: str) -> list[list[float]]:
        raise OSError("down")

    old = _entry()
    assert rm.follow_up([old], boom, 6, NOW) == 0
    assert old["follow_up"] is None and "OSError" in old["follow_up_error"]
    ancient = _entry(closed_at_utc=(NOW - timedelta(days=9)).isoformat())
    rm.follow_up([ancient], lambda s, tf: [], 6, NOW)
    assert "no longer available" in ancient["follow_up"]["error"]


def test_next_review_sees_past_calls_and_lessons_render(tmp_path: Path) -> None:
    mem = [_entry(key=f"main/{i}", stop_call_result="wrong") for i in range(7)]
    mem.append(_entry(key="degen/1", account="degen"))
    past = rm.past_for_prompt(mem, "main", 5)
    assert len(past["recent"]) == 5 and past["scorecard"]["stop_call"]["checked"] == 7
    assert all(r["stop_call_result"] == "wrong" for r in past["recent"])
    assert rm.past_for_prompt(mem, "main", 0)["recent"] == []
    rm.save_memory(tmp_path, mem)
    text = (tmp_path / "trades" / "lessons.md").read_text()
    assert "## main" in text and "Stop calls right: 0 of 7" in text and "## degen" in text
    assert rm.load_memory(tmp_path)[-1]["account"] == "degen"
    (tmp_path / "trades" / "memory.json").write_text("not json")
    assert rm.load_memory(tmp_path) == []


def test_memory_is_capped_and_a_retried_trade_replaces_its_entry(tmp_path: Path) -> None:
    mem: list[dict[str, Any]] = []
    facts = _facts({"account": "main", "market": "BTC", "side": "long", "exit": 1.0})
    rec = {"grade": "good", "stop_call": "unclear", "exit_call": "unclear", "lesson": "a"}
    rm.remember(mem, "main/1", facts, rec)
    rm.remember(mem, "main/1", facts, rec | {"lesson": "b"})
    assert [e["lesson"] for e in mem] == ["b"]
    rm.save_memory(tmp_path, [_entry(key=str(i)) for i in range(rm.KEEP + 5)])
    assert len(rm.load_memory(tmp_path)) == rm.KEEP


def test_measure_after_ignores_candles_still_open() -> None:
    closed = datetime(2026, 11, 20, tzinfo=UTC)
    rows = _after([100, 101], closed)
    assert rm.measure_after(_entry(closed_at_utc=closed.isoformat()), rows, 2, closed) is None
    got = rm.measure_after(
        _entry(closed_at_utc=closed.isoformat(), side="long"), rows, 2, closed + timedelta(hours=8)
    )
    assert got is not None and got["end_move_pct"] == 1.0 and got["worst_move_pct"] == -0.5
