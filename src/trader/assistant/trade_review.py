"""Per-trade analysis (ADR-045): one Claude request per closed trade, from measured facts.

The fact pack holds the trade as journaled, the account's settings, the candles from shortly
before the entry to just after the exit, and code-measured excursions (how far the price went
for and against the trade while it was open). The analyst explains why the trade opened and
closed, how the stop and any take-profits behaved, and what could be improved. It cannot
change anything; the owner decides.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from trader.perps.review_agents import BANNED, AssistantSettings, Client, ask
from trader.perps.review_facts import ACCOUNTS as PERPS_ACCOUNTS
from trader.perps.review_facts import read_settings

from .trades import SPOT

CandleFetcher = Callable[[str, str], list[list[float]]]
BARS_BEFORE = 12
MAX_BARS = 150
BAR_HOURS = {"1h": 1, "4h": 4}


class TradeAnalysis(BaseModel):
    """The trade analyst's structured answer."""

    headline: str
    grade: Literal["good", "acceptable", "poor"]
    entry_reason: str
    exit_reason: str
    stop_and_take_profit: str
    followed_rules: bool
    what_went_well: list[str]
    what_to_improve: list[str]


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def candle_window(rows: list[list[float]], opened: str, closed: str) -> list[list[Any]]:
    """
    Candles from ``BARS_BEFORE`` bars before the entry to one bar after the exit.

    Args:
        rows (list[list[float]]): ``[[ms, o, h, l, c, v], ...]`` oldest first.
        opened (str): Entry time (ISO).
        closed (str): Exit time (ISO).

    Returns:
        list[list[Any]]: ``[[open_utc, o, h, l, c], ...]``, at most ``MAX_BARS`` (the bars
        nearest the exit are kept when the trade was longer).
    """
    o_ms = datetime.fromisoformat(opened).timestamp() * 1000
    c_ms = datetime.fromisoformat(closed).timestamp() * 1000
    first = next((i for i, r in enumerate(rows) if r[0] >= o_ms), len(rows))
    last = next((i for i, r in enumerate(rows) if r[0] > c_ms), len(rows))
    picked = rows[max(first - BARS_BEFORE, 0) : last + 1][-MAX_BARS:]
    return [[_iso(r[0]), r[1], r[2], r[3], r[4]] for r in picked]


def excursions(trade: dict[str, Any], window: list[list[Any]], bar_hours: int) -> dict[str, Any]:
    """
    How far the price moved for and against the trade while it was open (from candles).

    Args:
        trade (dict[str, Any]): A trade from ``trades.closed_trades``.
        window (list[list[Any]]): From ``candle_window``.
        bar_hours (int): Candle length in hours.

    Returns:
        dict[str, Any]: Best and worst price move in % from the entry, in the trade's favour
        (positive) and against it (negative), or ``error`` when it cannot be measured.
    """
    entry = trade.get("entry")
    o, c = trade["opened_at_utc"], trade["closed_at_utc"]
    o_t, c_t = datetime.fromisoformat(o), datetime.fromisoformat(c)
    # Reason: a bar counts when any part of it overlaps the time the trade was open.
    held = [
        b
        for b in window
        if datetime.fromisoformat(b[0]) <= c_t
        and datetime.fromisoformat(b[0]) + timedelta(hours=bar_hours) > o_t
    ]
    if not entry or not held:
        return {"error": "no candles cover the trade"}
    hi, lo = max(float(b[2]) for b in held), min(float(b[3]) for b in held)
    up, down = (hi / entry - 1) * 100, (lo / entry - 1) * 100
    if trade.get("side") == "short":
        best, worst = -down, -up
    else:
        best, worst = up, down
    out = {"best_move_for_pct": round(best, 2), "worst_move_against_pct": round(worst, 2)}
    lev = trade.get("leverage")
    if lev:
        out["best_on_collateral_pct"] = round(best * lev, 2)
        out["worst_on_collateral_pct"] = round(worst * lev, 2)
    exit_ = trade.get("exit")
    if exit_ and best > 0:
        realized = (exit_ / entry - 1) * 100 * (-1 if trade.get("side") == "short" else 1)
        out["share_of_best_move_kept_pct"] = round(realized / best * 100, 1)
    return out


def settings_for(configs_root: Path, account: str) -> dict[str, Any]:
    """The account's settings as written (perps), or a pointer to the spot profile."""
    if account in PERPS_ACCOUNTS:
        return read_settings(configs_root, account)
    return {
        "file": "configs/profiles (spot paper profile)",
        "note": "spot is long-only, no leverage",
    }


def build_trade_facts(
    trade: dict[str, Any],
    configs_root: Path,
    fetch: CandleFetcher,
    timeframe: str,
    rule: str | None,
) -> dict[str, Any]:
    """
    The fact pack for one trade.

    Args:
        trade (dict[str, Any]): A trade from ``trades.closed_trades``.
        configs_root (Path): Config directory.
        fetch (CandleFetcher): Public candle fetcher.
        timeframe (str): Candle timeframe the account trades on (``1h`` or ``4h``).
        rule (str | None): The account's signal name, when known.

    Returns:
        dict[str, Any]: JSON-serializable facts.
    """
    err: str | None = None
    try:
        rows = fetch(f"{trade['market']}/USD", timeframe)
        window = candle_window(rows, trade["opened_at_utc"], trade["closed_at_utc"])
    except Exception as exc:  # noqa: BLE001 - a candle outage is a fact, not a crash
        window, err = [], f"{type(exc).__name__}: {exc}"
    return {
        "money": "simulated (paper); nothing here can place a real order",
        "trade": trade,
        "account_rule": rule
        or ("spot paper strategy, long-only" if trade["account"] == SPOT else None),
        "settings": settings_for(configs_root, trade["account"]),
        "candles": {
            "timeframe": timeframe,
            "columns": ["open_utc", "open", "high", "low", "close"],
            "rows": window,
            "error": err,
        },
        "measured": excursions(trade, window, BAR_HOURS.get(timeframe, 4)),
    }


def analyze_trade(
    facts: dict[str, Any], client: Client, settings: AssistantSettings
) -> TradeAnalysis | None:
    """One trade analyst request; None when the model declines."""
    result: TradeAnalysis | None = ask(
        client, settings, "trade_analyst", {"facts": facts}, TradeAnalysis
    )
    return result


def render_trade(
    facts: dict[str, Any],
    a: TradeAnalysis | None,
    reviewer: str | None = None,
    skipped: str | None = None,
    extra_md: str | None = None,
) -> str:
    """
    Markdown for one trade: a code-built facts table, then the analyst's notes.

    Args:
        facts (dict[str, Any]): From ``build_trade_facts``.
        a (TradeAnalysis | None): The analysis, or None when declined or skipped.
        reviewer (str | None): Model that wrote it, shown when not the default Claude one.
        skipped (str | None): Why no review was written (free model, ADR-049).
        extra_md (str | None): More Markdown under the notes (the debate, ADR-052).

    Returns:
        str: Report.
    """
    t, m = facts["trade"], facts["measured"]
    pnl = t.get("net_pnl_usd")
    title = a.headline if a else f"{t['account']} {t['side']} {t['market']} trade"
    lines = [
        f"# {title}",
        "",
        f"Account: **{t['account']}** (paper) · {t['side']} {t['market']} · "
        f"opened {t['opened_at_utc']} · closed {t['closed_at_utc']} UTC",
        "",
        "| Entry | Exit | Held (h) | Net P&L | Exit reason | Best move for | Worst against |",
        "|---|---|---|---|---|---|---|",
        f"| {t.get('entry')} | {t.get('exit')} | {t.get('hours_held')} | "
        f"{'n/a' if pnl is None else f'${pnl:,.2f}'} | {t.get('exit_reason')} | "
        f"{m.get('best_move_for_pct', 'n/a')}% | {m.get('worst_move_against_pct', 'n/a')}% |",
        "",
    ]
    if reviewer:
        lines += [f"Reviewed by: `{reviewer}` (free model, ADR-049)", ""]
    if a is None and skipped:
        lines += [f"_Review skipped: {skipped}. The facts are in the JSON file._", ""]
    elif a is None:
        lines += [
            "_The analyst declined to review this trade; the facts are in the JSON file._",
            "",
        ]
    else:
        body = "\n".join(
            [
                f"**Grade:** {a.grade} · **Followed its rules:** "
                f"{'yes' if a.followed_rules else 'no'}",
                "",
                f"**Why it opened.** {a.entry_reason}",
                "",
                f"**Why it closed.** {a.exit_reason}",
                "",
                f"**Stop-loss and take-profit.** {a.stop_and_take_profit}",
                "",
                "**What went well**",
                *[f"- {x}" for x in a.what_went_well or ["nothing stood out"]],
                "",
                "**What to look at**",
                *[f"- {x}" for x in a.what_to_improve or ["nothing yet"]],
            ]
        )
        if BANNED.search(body) or BANNED.search(a.headline):
            lines += [
                "> **Warning:** this text used profit-promising wording. Treat it with "
                "extra caution.",
                "",
            ]
        lines += [body, ""]
    if extra_md:
        lines += [extra_md.strip(), ""]
    lines += [
        "---",
        "Simulated money. Written by an AI review assistant from measured facts; it can be wrong. "
        "One trade is a tiny sample. Nothing changes unless you edit the settings yourself.",
    ]
    return "\n".join(lines) + "\n"


def trade_report_path(reports: Path, trade: dict[str, Any]) -> Path:
    """Where a trade's Markdown report lives: ``trades/<account>/<close>-<market>-<side>.md``."""
    stamp = str(trade["closed_at_utc"])[:19].replace(":", "").replace("-", "")
    return (
        reports / "trades" / str(trade["account"]) / f"{stamp}-{trade['market']}-{trade['side']}.md"
    )


def save_trade_report(
    reports: Path,
    facts: dict[str, Any],
    a: TradeAnalysis | None,
    reviewer: str | None = None,
    skipped: str | None = None,
    extra_md: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write ``reports/trades/<account>/<close-time>-<market>-<side>.md`` and JSON; return md."""
    md = trade_report_path(reports, facts["trade"])
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_trade(facts, a, reviewer, skipped, extra_md), encoding="utf-8")
    payload: dict[str, Any] = {"facts": facts, "analysis": a.model_dump() if a else None}
    if reviewer or skipped:
        payload |= {"reviewer": reviewer, "skipped": skipped}
    if extra:
        payload |= extra
    md.with_suffix(".json").write_text(
        json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8"
    )
    return md
