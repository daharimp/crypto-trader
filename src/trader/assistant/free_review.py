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

from pydantic import ValidationError

from trader.perps.review_agents import COMMON, ROLES, FreeTradeReviews

from .trade_review import TradeAnalysis, save_trade_report, trade_report_path
from .trades import closed_trades

KEY_ENV = "OPENROUTER_API_KEY"
Post = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_SCHEMA = json.dumps(TradeAnalysis.model_json_schema(), sort_keys=True)
FORMAT = (
    "Reply with ONLY one JSON object that matches this JSON Schema, with no text before or "
    f"after it and no Markdown fence: {_SCHEMA}"
)


def _http_post(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https base_url)
        out: dict[str, Any] = json.loads(resp.read())
    return out


def parse_answer(text: str) -> TradeAnalysis:
    """
    The JSON object inside a model's reply, checked against ``TradeAnalysis``.

    Args:
        text (str): Raw reply (may hold reasoning tags or a Markdown fence).

    Returns:
        TradeAnalysis: The parsed answer.

    Raises:
        ValueError: If there is no valid object (``ValidationError`` is a ``ValueError``).
    """
    body = _THINK.sub("", text or "")
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    return TradeAnalysis.model_validate(json.loads(body[start : end + 1]))


@dataclass
class FreeReviewer:
    """One free-model client: the key, the settings and an injectable HTTP post."""

    key: str
    cfg: FreeTradeReviews
    post: Post = _http_post

    def review(self, facts: dict[str, Any]) -> tuple[TradeAnalysis | None, str, int]:
        """
        Review one trade's facts.

        Args:
            facts (dict[str, Any]): From ``trade_review.build_trade_facts``.

        Returns:
            tuple[TradeAnalysis | None, str, int]: The answer (None when skipped), the model
            that answered or why it was skipped, and how many requests were made.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": f"{COMMON}\n\n{ROLES['trade_analyst']}\n\n{FORMAT}"},
            {"role": "user", "content": json.dumps({"facts": facts}, sort_keys=True, default=str)},
        ]
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        reason, calls = "no request made", 0
        for _ in range(1 + self.cfg.retries):
            calls += 1
            body = {
                "model": self.cfg.models[0],
                "models": self.cfg.models,
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
                model = str(resp.get("model") or self.cfg.models[0])
                text = str(resp["choices"][0]["message"].get("content") or "")
            except Exception as exc:  # noqa: BLE001 - an outage or rate limit means skip, not crash
                reason = f"request failed ({type(exc).__name__}: {str(exc)[:200]})"
                continue
            try:
                return parse_answer(text), model, calls
            except (ValueError, ValidationError) as exc:
                reason = f"no valid answer from {model} ({str(exc)[:200]})"
                messages += [
                    {"role": "assistant", "content": text[:4000]},
                    {
                        "role": "user",
                        "content": f"That reply was not valid: {str(exc)[:500]}. {FORMAT}",
                    },
                ]
        return None, reason, calls


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


def run_pass(
    cur: dict[str, Any],
    reviewer: FreeReviewer,
    data_root: Path,
    accounts: list[str],
    now: datetime,
    enrich: Callable[[dict[str, Any]], dict[str, Any]],
    send: Callable[[str], None],
) -> int:
    """
    Review every due trade within today's call budget; save each report and alert.

    Args:
        cur (dict[str, Any]): Watcher cursor (``free_done``, ``free_calls``; updated in place).
        reviewer (FreeReviewer): The free-model client.
        data_root (Path): Data directory.
        accounts (list[str]): Accounts to review.
        now (datetime): Current time (UTC).
        enrich (Callable): Trade -> fact pack (``build_trade_facts``).
        send (Callable[[str], None]): Alert function.

    Returns:
        int: Trades handled this pass.
    """
    cfg = reviewer.cfg
    today = now.date().isoformat()
    calls = {today: int(cur.get("free_calls", {}).get(today, 0))}
    done = set(cur.get("free_done", []))
    handled = 0
    for t in due_trades(data_root, accounts, done, now, cfg.lookback_hours):
        # Reason: reserve room for the retry too, so a bad answer cannot push past the cap.
        if calls[today] + 1 + cfg.retries > cfg.daily_call_budget:
            break
        done.add(trade_key(t))
        cur["free_done"] = sorted(done)[-500:]
        try:
            facts = enrich(t)
        except Exception as exc:  # noqa: BLE001 - one trade's facts must not stop the watcher
            send(f"{trade_key(t)}: free review skipped ({type(exc).__name__}: {exc})")
            continue
        a, info, n = reviewer.review(facts)
        calls[today] += n
        cur["free_calls"] = dict(calls)
        save_trade_report(
            data_root / "reports",
            facts,
            a,
            reviewer=info if a else None,
            skipped=None if a else info,
        )
        pnl = t.get("net_pnl_usd")
        money = "" if pnl is None else f" ${pnl:,.2f}"
        head = f"{a.headline} ({a.grade})" if a else "review skipped, facts saved"
        send(f"{t['account']} {t['side']} {t['market']} closed{money}: {head} [free model]")
        handled += 1
    return handled
