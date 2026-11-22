"""Daily summary and drawdown alerts for every paper account (ADR-045).

Code measures each account's day (trades closed, wins, net P&L, equity, drawdown from its
peak) and a code-built table heads the report; one Claude request writes the narrative.
Drawdown alerts are pure code: no model is asked.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from trader.perps.review_agents import BANNED, AssistantSettings, Client, ask

from .trade_review import trade_report_path
from .trades import closed_trades, equity_snapshot


class DailySummary(BaseModel):
    """The daily editor's structured answer."""

    headline: str
    summary_markdown: str
    things_to_watch: list[str]


def account_day(data_root: Path, account: str, day: str) -> dict[str, Any]:
    """
    One account's measured day.

    Args:
        data_root (Path): Data directory.
        account (str): Account name.
        day (str): UTC day ``YYYY-MM-DD``.

    Returns:
        dict[str, Any]: ``ran`` False when the account has never run; else equity, drawdown,
        the day's closed trades and their totals.
    """
    snap = equity_snapshot(data_root, account)
    if snap is None:
        return {"account": account, "ran": False}
    trades = [t for t in closed_trades(data_root, account) if t["closed_at_utc"][:10] == day]
    pnls = [t["net_pnl_usd"] for t in trades if t.get("net_pnl_usd") is not None]
    return {
        "account": account,
        "ran": True,
        **snap,
        "trades_closed": len(trades),
        "wins": sum(1 for p in pnls if p > 0),
        "losses": sum(1 for p in pnls if p <= 0),
        "net_pnl_usd": round(sum(pnls), 2),
        "trades": trades,
    }


def daily_facts(data_root: Path, accounts: Sequence[str], day: str) -> dict[str, Any]:
    """The fact pack for one day's summary across ``accounts``."""
    return {
        "money": "simulated (paper); nothing here can place a real order",
        "day_utc": day,
        "accounts": [account_day(data_root, a, day) for a in accounts],
    }


def attach_trade_analyses(facts: dict[str, Any], reports: Path) -> None:
    """Add each saved per-trade analysis (headline, grade, what to improve) to its trade."""
    for acct in facts["accounts"]:
        for t in acct.get("trades", []):
            js = trade_report_path(reports, t).with_suffix(".json")
            try:
                a = json.loads(js.read_text(encoding="utf-8")).get("analysis")
            except (OSError, ValueError):
                continue
            if a:
                t["analysis"] = {k: a.get(k) for k in ("headline", "grade", "what_to_improve")}


def _money(x: Any) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


def render_daily(facts: dict[str, Any], s: DailySummary | None) -> str:
    """
    Markdown: headline, a code-built table of every account, then the editor's text.

    Args:
        facts (dict[str, Any]): From ``daily_facts``.
        s (DailySummary | None): The summary, or None when declined.

    Returns:
        str: Report.
    """
    day = facts["day_utc"]
    lines = [
        f"# {s.headline if s else f'Daily summary for {day}'}",
        "",
        f"Every paper account · UTC day {day}",
        "",
        "| Account | Equity | Day P&L (closed) | Trades (W/L) | Drawdown from peak | Open |",
        "|---|---|---|---|---|---|",
    ]
    for a in facts["accounts"]:
        if not a["ran"]:
            lines.append(f"| {a['account']} | not running | | | | |")
            continue
        lines.append(
            f"| {a['account']} | {_money(a['equity_usd'])} | {_money(a['net_pnl_usd'])} | "
            f"{a['trades_closed']} ({a['wins']}/{a['losses']}) | {a['drawdown_pct']}% | "
            f"{a['open_positions']} |"
        )
    lines.append("")
    if s is None:
        lines += ["_The editor declined to write a summary; the facts are in the JSON file._", ""]
    else:
        body = s.summary_markdown.strip()
        if BANNED.search(body) or BANNED.search(s.headline):
            lines += [
                "> **Warning:** this text used profit-promising wording. Treat it with "
                "extra caution.",
                "",
            ]
        lines += [body, ""]
        if s.things_to_watch:
            lines += ["**Worth watching**", *[f"- {x}" for x in s.things_to_watch], ""]
    lines += [
        "---",
        "Simulated money. Written by an AI review assistant from measured facts; it can be wrong. "
        "Past results are not a forecast. Nothing changes unless you edit the settings yourself.",
    ]
    return "\n".join(lines) + "\n"


def write_daily(
    data_root: Path, accounts: Sequence[str], day: str, client: Client, settings: AssistantSettings
) -> tuple[str, Path]:
    """
    Build, ask and save one day's summary; return its headline and Markdown path.

    Args:
        data_root (Path): Data directory.
        accounts (Sequence[str]): Accounts to cover.
        day (str): UTC day.
        client (Client): Anthropic client.
        settings (AssistantSettings): Model and effort.

    Returns:
        tuple[str, Path]: Headline and ``reports/daily-<day>.md``.
    """
    reports = data_root / "reports"
    facts = daily_facts(data_root, accounts, day)
    attach_trade_analyses(facts, reports)
    s: DailySummary | None = ask(client, settings, "daily_editor", {"facts": facts}, DailySummary)
    md = reports / f"daily-{day}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_daily(facts, s), encoding="utf-8")
    md.with_suffix(".json").write_text(
        json.dumps(
            {"facts": facts, "summary": s.model_dump() if s else None},
            indent=1,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    return (s.headline if s else f"Daily summary for {day}"), md


def drawdown_alerts(
    data_root: Path, accounts: Sequence[str], levels: list[float], seen: dict[str, float]
) -> list[str]:
    """
    Alerts for accounts whose drawdown from their peak crossed a new level.

    ``seen`` maps account -> the highest level already alerted since its last peak; it is
    updated in place, and reset when the account recovers below the lowest level.

    Args:
        data_root (Path): Data directory.
        accounts (Sequence[str]): Accounts to check.
        levels (list[float]): Alert levels in % (e.g. ``[5, 10, 15]``).
        seen (dict[str, float]): Alert memory, updated in place.

    Returns:
        list[str]: One alert line per account that crossed a new level.
    """
    out: list[str] = []
    if not levels:
        return out
    for a in accounts:
        snap = equity_snapshot(data_root, a)
        if snap is None:
            continue
        dd = snap["drawdown_pct"]
        crossed = [lv for lv in sorted(levels) if dd >= lv]
        if not crossed:
            # Reason: recovered below every level, so the next fall alerts again.
            seen.pop(a, None)
            continue
        top = crossed[-1]
        if top > seen.get(a, 0.0):
            seen[a] = top
            out.append(
                f"DRAWDOWN {a}: down {dd}% from its peak ({_money(snap['peak_usd'])} -> "
                f"{_money(snap['equity_usd'])}), past the {top:g}% alert level"
            )
    return out
