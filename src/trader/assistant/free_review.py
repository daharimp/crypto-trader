"""Per-trade reviews on a free OpenRouter model (ADR-049).

Each paper trade closed in the last ``lookback_hours`` gets one review from a free model,
saved next to the measured facts in ``data/reports/trades/<account>/`` (Markdown and JSON).
The hourly status push copies them to the ops repo, where the daily Claude review reads the
notes *and* the raw facts, so one weak free answer cannot decide the daily verdict.

Free models do not reliably return a clean structured answer, so code checks every answer
against ``TradeAnalysis``, asks once more with the error, and otherwise saves the facts with
"review skipped" instead of failing. A daily call budget keeps the account under the free
request cap (failed calls count too). Without ``OPENROUTER_API_KEY`` nothing runs.
Nothing here edits a setting or places an order.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from trader.perps.review_agents import COMMON, ROLES, FreeTradeReviews

from .debate import debate_payload, render_debate, run_debate, verdict_record
from .review_memory import (
    CandleFetcher,
    follow_up,
    load_memory,
    past_for_prompt,
    remember,
    save_memory,
)
from .trade_review import TradeAnalysis, save_trade_report, trade_report_path
from .trades import closed_trades

KEY_ENV = "OPENROUTER_API_KEY"
Post = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def format_rule(schema: type[BaseModel]) -> str:
    """The instruction that asks for one JSON object matching ``schema``."""
    return (
        "Reply with ONLY one JSON object that matches this JSON Schema, with no text before "
        "or after it and no Markdown fence: "
        f"{json.dumps(schema.model_json_schema(), sort_keys=True)}"
    )


FORMAT = format_rule(TradeAnalysis)


def _http_post(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https base_url)
        out: dict[str, Any] = json.loads(resp.read())
    return out


def parse_answer(text: str, schema: type[BaseModel] = TradeAnalysis) -> Any:
    """
    The JSON object inside a model's reply, checked against ``schema``.

    Args:
        text (str): Raw reply (may hold reasoning tags or a Markdown fence).
        schema (type[BaseModel]): Answer schema (``TradeAnalysis`` by default).

    Returns:
        Any: The parsed answer, an instance of ``schema``.

    Raises:
        ValueError: If there is no valid object (``ValidationError`` is a ``ValueError``).
    """
    body = _THINK.sub("", text or "")
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    return schema.model_validate(json.loads(body[start : end + 1]))


@dataclass
class FreeReviewer:
    """One free-model client: the key, the settings and an injectable HTTP post."""

    key: str
    cfg: FreeTradeReviews
    post: Post = _http_post

    def ask(
        self,
        system: str,
        payload: dict[str, Any],
        models: list[str],
        schema: type[BaseModel] | None,
    ) -> tuple[Any, str, int, str]:
        """
        One request to the free models (tried in order), checked against ``schema``.

        Args:
            system (str): System prompt (the JSON format rule is added when ``schema`` is set).
            payload (dict[str, Any]): The user message, sent as JSON.
            models (list[str]): OpenRouter models, tried in order.
            schema (type[BaseModel] | None): Answer schema; None for a plain-text answer,
                which is never retried.

        Returns:
            tuple[Any, str, int, str]: The answer (parsed, text, or None when skipped), the
            model that answered, how many requests were made, and why it was skipped.
        """
        fmt = format_rule(schema) if schema else ""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": f"{system}\n\n{fmt}".strip()},
            {"role": "user", "content": json.dumps(payload, sort_keys=True, default=str)},
        ]
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        reason, calls, model = "no request made", 0, models[0] if models else "?"
        for _ in range(1 + (self.cfg.retries if schema else 0)):
            calls += 1
            body = {
                "model": models[0],
                "models": models,
                "messages": messages,
                "max_tokens": self.cfg.max_tokens,
                "reasoning": {"effort": self.cfg.reasoning_effort, "exclude": True},
            }
            try:
                resp = self.post(
                    f"{self.cfg.base_url.rstrip('/')}/chat/completions",
                    headers,
                    body,
                    self.cfg.timeout_s,
                )
                model = str(resp.get("model") or models[0])
                text = str(resp["choices"][0]["message"].get("content") or "")
            except Exception as exc:  # noqa: BLE001 - an outage or rate limit means skip, not crash
                reason = f"request failed ({type(exc).__name__}: {str(exc)[:200]})"
                continue
            if schema is None:
                text = _THINK.sub("", text).strip()
                if text:
                    return text, model, calls, ""
                reason = f"empty answer from {model}"
                continue
            try:
                return parse_answer(text, schema), model, calls, ""
            except (ValueError, ValidationError) as exc:
                reason = f"no valid answer from {model} ({str(exc)[:200]})"
                messages += [
                    {"role": "assistant", "content": text[:4000]},
                    {
                        "role": "user",
                        "content": f"That reply was not valid: {str(exc)[:500]}. {fmt}",
                    },
                ]
        return None, model, calls, reason

    def review(self, facts: dict[str, Any]) -> tuple[TradeAnalysis | None, str, int]:
        """
        Review one trade's facts with one model (ADR-049).

        Args:
            facts (dict[str, Any]): From ``trade_review.build_trade_facts``.

        Returns:
            tuple[TradeAnalysis | None, str, int]: The answer (None when skipped), the model
            that answered or why it was skipped, and how many requests were made.
        """
        a, model, calls, why = self.ask(
            f"{COMMON}\n\n{ROLES['trade_analyst']}",
            {"facts": facts},
            self.cfg.models,
            TradeAnalysis,
        )
        return (a, model, calls) if a is not None else (None, why, calls)


def reviewer_from_env(cfg: FreeTradeReviews) -> FreeReviewer | None:
    """A reviewer when enabled and ``OPENROUTER_API_KEY`` is set; otherwise None (quiet skip)."""
    key = os.environ.get(KEY_ENV, "").strip()
    if not cfg.enabled or not key:
        return None
    return FreeReviewer(key, cfg)


def trade_key(trade: dict[str, Any]) -> str:
    """Cursor key for one trade."""
    return f"{trade['account']}/{trade.get('trade_id') or trade['closed_at_utc']}"


def due_trades(
    data_root: Path, accounts: list[str], done: set[str], now: datetime, lookback_hours: int
) -> list[dict[str, Any]]:
    """
    Trades closed in the last ``lookback_hours`` with no review yet, oldest close first.

    Args:
        data_root (Path): Data directory.
        accounts (list[str]): Accounts to look at.
        done (set[str]): Keys already reviewed or attempted.
        now (datetime): Current time (UTC).
        lookback_hours (int): How far back a close still counts.

    Returns:
        list[dict[str, Any]]: Trades to review.
    """
    since = now - timedelta(hours=lookback_hours)
    reports = data_root / "reports"
    out = []
    for account in accounts:
        try:
            trades = closed_trades(data_root, account)
        except (ValueError, OSError):
            continue
        for t in trades:
            closed = datetime.fromisoformat(str(t["closed_at_utc"]))
            if closed < since or closed > now or trade_key(t) in done:
                continue
            # Reason: a trade that already has a report (e.g. from Claude) is not reviewed twice.
            if trade_report_path(reports, t).exists():
                continue
            out.append(t)
    return sorted(out, key=lambda t: str(t["closed_at_utc"]))


def _review_one(
    reviewer: FreeReviewer,
    facts: dict[str, Any],
    debate: bool,
    memory: list[dict[str, Any]],
    key: str,
) -> tuple[TradeAnalysis | None, str, int, str | None, dict[str, Any] | None]:
    """
    One trade's review: a debate (ADR-052) or a single-model review (ADR-049).

    Returns:
        tuple: analysis (None when skipped), reviewer label or why skipped, requests made,
        extra Markdown and extra JSON for the report.
    """
    if not debate:
        a, info, n = reviewer.review(facts)
        return a, info, n, None, None
    t = facts.get("trade", {})
    pnl = t.get("net_pnl_usd")
    past = past_for_prompt(memory, str(t.get("account")), reviewer.cfg.memory_reviews)
    d = run_debate(reviewer, facts, past)
    extra: dict[str, Any] = {"debate": debate_payload(d)}
    if d.verdict is None:
        return None, d.skipped or "no verdict", d.calls, render_debate(d, pnl), extra
    record = verdict_record(d, pnl)
    remember(memory, key, facts, record)
    extra["verdict"] = record
    label = f"{d.models['judge']} (judge), bull {d.models['bull']}, bear {d.models['bear']}"
    return d.verdict, label, d.calls, render_debate(d, pnl), extra


def run_pass(
    cur: dict[str, Any],
    reviewer: FreeReviewer,
    data_root: Path,
    accounts: list[str],
    now: datetime,
    enrich: Callable[[dict[str, Any]], dict[str, Any]],
    send: Callable[[str], None],
    fetch: CandleFetcher | None = None,
) -> int:
    """
    Review every due trade within today's call budget; save each report and alert.

    With ``debate`` on, each trade gets a bull/bear/judge debate while the budget can still
    give every other due trade at least a single-model review; otherwise it gets a single
    review, and when even that does not fit it waits for tomorrow's budget (ADR-052). Then
    past verdicts old enough are checked against what the price did after the exit.

    Args:
        cur (dict[str, Any]): Watcher cursor (``free_done``, ``free_calls``; updated in place).
        reviewer (FreeReviewer): The free-model client.
        data_root (Path): Data directory.
        accounts (list[str]): Accounts to review.
        now (datetime): Current time (UTC).
        enrich (Callable): Trade -> fact pack (``build_trade_facts``).
        send (Callable[[str], None]): Alert function.
        fetch (CandleFetcher | None): Public candle fetcher for the follow-up check; None
            skips it.

    Returns:
        int: Trades handled this pass.
    """
    cfg = reviewer.cfg
    reports = data_root / "reports"
    today = now.date().isoformat()
    calls = {today: int(cur.get("free_calls", {}).get(today, 0))}
    done = set(cur.get("free_done", []))
    memory = load_memory(reports) if cfg.debate else []
    changed = False
    handled = 0
    due = due_trades(data_root, accounts, done, now, cfg.lookback_hours)
    for i, t in enumerate(due):
        left = cfg.daily_call_budget - calls[today]
        # Reason: keep room for a single review of every other due trade before spending a
        # debate on this one, so a busy day never leaves trades with no review at all.
        rest = (len(due) - i - 1) * cfg.single_calls()
        debate = cfg.debate and left - cfg.debate_calls() >= rest
        if not debate and left < cfg.single_calls():
            break
        done.add(trade_key(t))
        cur["free_done"] = sorted(done)[-500:]
        try:
            facts = enrich(t)
        except Exception as exc:  # noqa: BLE001 - one trade's facts must not stop the watcher
            send(f"{trade_key(t)}: free review skipped ({type(exc).__name__}: {exc})")
            continue
        a, info, n, extra_md, extra = _review_one(reviewer, facts, debate, memory, trade_key(t))
        changed = changed or bool(extra and "verdict" in extra)
        calls[today] += n
        cur["free_calls"] = dict(calls)
        save_trade_report(
            reports,
            facts,
            a,
            reviewer=info if a else None,
            skipped=None if a else info,
            extra_md=extra_md,
            extra=extra,
        )
        pnl = t.get("net_pnl_usd")
        money = "" if pnl is None else f" ${pnl:,.2f}"
        head = f"{a.headline} ({a.grade})" if a else "review skipped, facts saved"
        kind = "free debate" if debate else "free model"
        send(f"{t['account']} {t['side']} {t['market']} closed{money}: {head} [{kind}]")
        handled += 1
    if cfg.debate and fetch is not None:
        changed = follow_up(memory, fetch, cfg.follow_up_bars, now) > 0 or changed
    if changed:
        save_memory(reports, memory)
    return handled
