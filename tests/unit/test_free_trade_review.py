"""Per-trade reviews on a free OpenRouter model (ADR-049). No network: the HTTP post is faked."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SHIPPED_CONFIGS
from tests.unit.test_review_every_trade import ANALYSIS, NEW_ID, NOW, data  # noqa: F401
from trader.assistant import free_review as fr
from trader.perps import review_agents as ra

GOOD = json.dumps(ANALYSIS.model_dump())


class FakePost:
    """Returns the queued replies in order; a BaseException in the queue is raised."""

    def __init__(self, *replies: Any) -> None:
        self.replies, self.calls = list(replies), []  # type: list[Any], list[dict[str, Any]]

    def __call__(
        self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "body": body})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return {"model": "m/free-a:free", "choices": [{"message": {"content": r}}]}


def _cfg(**over: Any) -> ra.FreeTradeReviews:
    base = ra.load_assistant_settings(SHIPPED_CONFIGS).free_trade_reviews
    return base.model_copy(update=over)


def _reviewer(post: FakePost, **over: Any) -> fr.FreeReviewer:
    return fr.FreeReviewer("k", _cfg(**over), post)


def test_shipped_settings_and_defaults() -> None:
    cfg = _cfg()
    assert cfg.enabled and len(cfg.models) == 2 and cfg.daily_call_budget < 50
    assert ra.FreeTradeReviews().enabled is False  # older files stay off
    with pytest.raises(ValueError, match="at least one model"):
        ra.FreeTradeReviews(enabled=True)
    with pytest.raises(ValueError):
        ra.FreeTradeReviews(base_url="http://insecure.example")


def test_parse_answer_strips_reasoning_and_fences() -> None:
    a = fr.parse_answer(f"<think>hmm {{</think>```json\n{GOOD}\n```")
    assert a.grade == ANALYSIS.grade
    with pytest.raises(ValueError):
        fr.parse_answer("no json here")
    with pytest.raises(ValueError):
        fr.parse_answer('{"headline": "x"}')  # missing fields


def test_review_sends_fallback_models_and_effort() -> None:
    post = FakePost(GOOD)
    a, model, n = _reviewer(post).review({"trade": {}})
    assert a is not None and model == "m/free-a:free" and n == 1
    body = post.calls[0]["body"]
    assert body["models"] == _cfg().models and body["reasoning"]["effort"] == "medium"
    assert post.calls[0]["url"].endswith("/chat/completions")
    assert post.calls[0]["headers"]["Authorization"] == "Bearer k"
    assert "JSON Schema" in body["messages"][0]["content"]


def test_invalid_answer_retries_once_with_the_error_then_skips() -> None:
    post = FakePost("not json", GOOD)
    a, _, n = _reviewer(post).review({})
    assert a is not None and n == 2
    assert "not valid" in post.calls[1]["body"]["messages"][-1]["content"]
    post = FakePost("nope", "still nope")
    a, why, n = _reviewer(post).review({})
    assert a is None and n == 2 and "no valid answer" in why
    post = FakePost(OSError("429 Too Many Requests"))
    a, why, n = _reviewer(post, retries=0).review({})
    assert a is None and n == 1 and "request failed" in why


def test_missing_key_or_disabled_means_no_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fr.KEY_ENV, raising=False)
    assert fr.reviewer_from_env(_cfg()) is None
    monkeypatch.setenv(fr.KEY_ENV, "k")
    assert fr.reviewer_from_env(_cfg()) is not None
    assert fr.reviewer_from_env(_cfg(enabled=False)) is None


def test_watch_reviews_each_new_trade_once_and_saves_it(data: Path) -> None:  # noqa: F811
    from trader.cli.review import _load_cursor, watch_once

    settings = ra.load_assistant_settings(SHIPPED_CONFIGS).model_copy(
        update={"report_accounts": ["spot", "main"]}
    )
    post, sent = FakePost(GOOD), []  # type: FakePost, list[str]
    cur = _load_cursor(data / "state" / "review-assistant.json")
    # Reason: None as the Claude client proves the free path never reaches Anthropic.
    watch_once(cur, None, settings, sent.append, NOW, fr.FreeReviewer("k", _cfg(), post))
    assert len(post.calls) == 1  # only the trade closed in the last 24 h
    assert cur["free_done"] == [f"spot/{NEW_ID}"] and cur["free_calls"] == {"2026-11-22": 1}
    assert any(s.endswith("[free model]") and f"({ANALYSIS.grade})" in s for s in sent)
    (md,) = (data / "reports" / "trades" / "spot").glob("*.md")
    assert "Reviewed by: `m/free-a:free`" in md.read_text()
    saved = json.loads(md.with_suffix(".json").read_text())
    assert saved["analysis"]["grade"] and saved["facts"]["measured"]  # raw facts kept
    watch_once(
        cur,
        None,
        settings,
        sent.append,
        NOW + timedelta(minutes=1),
        fr.FreeReviewer("k", _cfg(), post),
    )
    assert len(post.calls) == 1  # never twice


def test_skipped_review_saves_facts_and_budget_stops_calls(data: Path) -> None:  # noqa: F811
    post, sent = FakePost("junk", "junk"), []  # type: FakePost, list[str]
    cur: dict[str, Any] = {"free_done": [], "free_calls": {"2026-11-22": 40}}
    rv = fr.FreeReviewer("k", _cfg(), post)
    n = fr.run_pass(
        cur, rv, data, ["spot"], NOW, lambda t: {"trade": t, "measured": {}}, sent.append
    )
    assert n == 1 and cur["free_calls"]["2026-11-22"] == 42
    (md,) = (data / "reports" / "trades" / "spot").glob("*.md")
    assert "Review skipped: no valid answer" in md.read_text()
    assert json.loads(md.with_suffix(".json").read_text())["skipped"].startswith("no valid")
    full: dict[str, Any] = {"free_done": [], "free_calls": {"2026-11-22": 44}}
    md.unlink()
    assert fr.run_pass(full, rv, data, ["spot"], NOW, lambda t: {}, sent.append) == 0
    assert len(post.calls) == 2 and full["free_done"] == []  # left for tomorrow's budget
