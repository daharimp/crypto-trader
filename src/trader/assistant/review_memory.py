"""Review memory (ADR-052): past verdicts checked against what the price did next.

Each judged trade review leaves one entry in ``data/reports/trades/memory.json``: the
judge's process grade, two checkable calls (was the stop too tight, was the exit too early)
and a one-sentence lesson. Once ``follow_up_bars`` candles have closed after the exit, code
(not a model) measures how far the price went on in the trade's direction and against it,
and marks each call right, wrong or unclear. The next review of the same account sees the
recent entries with those marks, and ``lessons.md`` next to the trade notes gives the daily
Claude review the same scorecard. Nothing here edits a setting or places an order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CandleFetcher = Callable[[str, str], list[list[float]]]
MEMORY_FILE = "memory.json"
LESSONS_FILE = "lessons.md"
KEEP = 300
BAR_HOURS = {"1h": 1, "4h": 4}
# Reason: a move under 1% after the exit is noise on every coin these bots trade, so a call
# is only marked right or wrong when the price clearly went one way.
CLEAR_MOVE_PCT = 1.0


def memory_path(reports: Path) -> Path:
    """``reports/trades/memory.json``."""
    return reports / "trades" / MEMORY_FILE


def load_memory(reports: Path) -> list[dict[str, Any]]:
    """
    Every remembered review, oldest first; an unreadable file counts as empty.

    Args:
        reports (Path): ``data/reports``.

    Returns:
        list[dict[str, Any]]: Entries.
    """
    try:
        raw = json.loads(memory_path(reports).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def save_memory(reports: Path, entries: list[dict[str, Any]]) -> None:
    """Write the newest ``KEEP`` entries and refresh ``lessons.md``."""
    path = memory_path(reports)
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = entries[-KEEP:]
    path.write_text(json.dumps(keep, indent=1, sort_keys=True, default=str), encoding="utf-8")
    (path.parent / LESSONS_FILE).write_text(render_lessons(keep), encoding="utf-8")


def remember(
    entries: list[dict[str, Any]], key: str, facts: dict[str, Any], verdict: dict[str, Any]
) -> dict[str, Any]:
    """
    Add (or replace) the entry for one judged trade.

    Args:
        entries (list[dict[str, Any]]): Memory (changed in place).
        key (str): ``free_review.trade_key`` of the trade.
        facts (dict[str, Any]): The trade's fact pack.
        verdict (dict[str, Any]): The judge's answer (``DebateVerdict.model_dump()``).

    Returns:
        dict[str, Any]: The new entry.
    """
    t = facts.get("trade", {})
    entry = {
        "key": key,
        "account": t.get("account"),
        "market": t.get("market"),
        "side": t.get("side"),
        "timeframe": (facts.get("candles") or {}).get("timeframe", "4h"),
        "closed_at_utc": t.get("closed_at_utc"),
        "exit": t.get("exit"),
        "exit_reason": t.get("exit_reason"),
        "net_pnl_usd": t.get("net_pnl_usd"),
        "grade": verdict.get("grade"),
        "quadrant": verdict.get("quadrant"),
        "stop_call": verdict.get("stop_call"),
        "exit_call": verdict.get("exit_call"),
        "lesson": verdict.get("lesson"),
        "follow_up": None,
    }
    entries[:] = [e for e in entries if e.get("key") != key] + [entry]
    return entry


def _direction(side: Any) -> int:
    return -1 if side == "short" else 1


def measure_after(
    entry: dict[str, Any], rows: list[list[float]], bars: int, now: datetime
) -> dict[str, Any] | None:
    """
    How the price moved in the ``bars`` closed candles after the exit, or None until then.

    Args:
        entry (dict[str, Any]): A memory entry (needs ``exit``, ``side``, ``closed_at_utc``).
        rows (list[list[float]]): ``[[ms, o, h, l, c, v], ...]`` oldest first.
        bars (int): Candles to wait for.
        now (datetime): Current time (UTC); only candles closed by then count.

    Returns:
        dict[str, Any] | None: Closing move, best and worst move in the trade's direction
        (% of the exit price), or None while fewer than ``bars`` candles have closed.
    """
    exit_px = entry.get("exit")
    if not exit_px:
        return {"error": "no exit price"}
    closed = datetime.fromisoformat(str(entry["closed_at_utc"]))
    step = timedelta(hours=BAR_HOURS.get(str(entry.get("timeframe")), 4))
    after = [
        r
        for r in rows
        if datetime.fromtimestamp(r[0] / 1000, closed.tzinfo) >= closed
        and datetime.fromtimestamp(r[0] / 1000, closed.tzinfo) + step <= now
    ][:bars]
    if len(after) < bars:
        return None
    sign = _direction(entry.get("side"))
    moves_hi = [(float(r[2]) / exit_px - 1) * 100 * sign for r in after]
    moves_lo = [(float(r[3]) / exit_px - 1) * 100 * sign for r in after]
    best = max(moves_hi + moves_lo)
    worst = min(moves_hi + moves_lo)
    end = (float(after[-1][4]) / exit_px - 1) * 100 * sign
    return {
        "bars": bars,
        "end_move_pct": round(end, 2),
        "best_move_pct": round(best, 2),
        "worst_move_pct": round(worst, 2),
    }


def score_calls(entry: dict[str, Any]) -> dict[str, str]:
    """
    Mark the judge's checkable calls right, wrong or unclear from the measured follow-up.

    A stop called ``too_tight`` was right when the price came back past the exit by a clear
    margin; ``about_right`` was right when it kept going against the trade. An exit called
    ``too_early`` was right when the price kept going the trade's way; ``about_right`` when it
    did not. ``too_late`` and ``unclear`` cannot be checked from what came after.

    Args:
        entry (dict[str, Any]): A memory entry with ``follow_up``.

    Returns:
        dict[str, str]: ``stop_call_result`` and ``exit_call_result``.
    """
    f = entry.get("follow_up") or {}
    if "end_move_pct" not in f:
        return {"stop_call_result": "unclear", "exit_call_result": "unclear"}
    went_on = f["end_move_pct"] >= CLEAR_MOVE_PCT
    went_back = f["end_move_pct"] <= -CLEAR_MOVE_PCT
    out = {"stop_call_result": "not a stop exit", "exit_call_result": "unclear"}
    if entry.get("exit_reason") == "STOP_LOSS":
        # Reason: after a stop the trade's direction is the one the stop gave up on, so a
        # recovery is a positive move in the trade's direction.
        call = entry.get("stop_call")
        if call == "too_tight":
            out["stop_call_result"] = "right" if went_on else "wrong" if went_back else "unclear"
        elif call == "about_right":
            out["stop_call_result"] = "right" if went_back else "wrong" if went_on else "unclear"
        else:
            out["stop_call_result"] = "not checkable"
    call = entry.get("exit_call")
    if call == "too_early":
        out["exit_call_result"] = "right" if went_on else "wrong" if went_back else "unclear"
    elif call == "about_right":
        out["exit_call_result"] = "wrong" if went_on else "right"
    else:
        out["exit_call_result"] = "not checkable"
    return out


def follow_up(entries: list[dict[str, Any]], fetch: CandleFetcher, bars: int, now: datetime) -> int:
    """
    Measure what happened after each exit that is old enough and not measured yet.

    Args:
        entries (list[dict[str, Any]]): Memory (changed in place).
        fetch (CandleFetcher): Public candle fetcher (``"BTC/USD", "4h"``).
        bars (int): Candles to wait after the exit.
        now (datetime): Current time (UTC).

    Returns:
        int: Entries measured this pass.
    """
    done = 0
    cache: dict[tuple[str, str], list[list[float]]] = {}
    for e in entries:
        if e.get("follow_up") is not None or not e.get("closed_at_utc"):
            continue
        tf = str(e.get("timeframe") or "4h")
        closed = datetime.fromisoformat(str(e["closed_at_utc"]))
        if now < closed + timedelta(hours=BAR_HOURS.get(tf, 4) * (bars + 1)):
            continue
        k = (f"{e.get('market')}/USD", tf)
        try:
            rows = cache[k] if k in cache else cache.setdefault(k, fetch(*k))
        except Exception as exc:  # noqa: BLE001 - a candle outage means try again later
            cache[k] = []
            e["follow_up_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            continue
        got = measure_after(e, rows, bars, now)
        if got is None:
            # Reason: the fetcher returns a limited recent window; a trade older than that
            # can never be measured, so give up after three days past the wait.
            if now > closed + timedelta(days=3, hours=BAR_HOURS.get(tf, 4) * bars):
                e["follow_up"] = {"error": "candles after the exit are no longer available"}
            continue
        e["follow_up"] = got
        e.update(score_calls(e))
        done += 1
    return done


def scorecard(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """How often the judge's checked calls were right, and the grade mix by outcome."""
    out: dict[str, Any] = {}
    for call in ("stop_call_result", "exit_call_result"):
        marks = [e.get(call) for e in entries if e.get(call) in ("right", "wrong")]
        out[call.replace("_result", "")] = {
            "checked": len(marks),
            "right": sum(1 for m in marks if m == "right"),
        }
    quads: dict[str, int] = {}
    for e in entries:
        if e.get("quadrant"):
            quads[e["quadrant"]] = quads.get(e["quadrant"], 0) + 1
    out["grade_by_outcome"] = quads
    return out


def past_for_prompt(entries: list[dict[str, Any]], account: str, n: int) -> dict[str, Any]:
    """
    The memory a new review of ``account`` sees: its last ``n`` entries and the scorecard.

    Args:
        entries (list[dict[str, Any]]): Memory.
        account (str): Account of the trade being reviewed.
        n (int): How many past reviews to include.

    Returns:
        dict[str, Any]: ``recent`` (newest last) and ``scorecard`` for this account.
    """
    mine = [e for e in entries if e.get("account") == account]
    fields = (
        "market",
        "side",
        "closed_at_utc",
        "exit_reason",
        "net_pnl_usd",
        "grade",
        "stop_call",
        "stop_call_result",
        "exit_call",
        "exit_call_result",
        "follow_up",
        "lesson",
    )
    recent = [{k: e.get(k) for k in fields} for e in mine[-n:]] if n > 0 else []
    return {"recent": recent, "scorecard": scorecard(mine)}


def render_lessons(entries: list[dict[str, Any]], n: int = 20) -> str:
    """``lessons.md``: per-account scorecard and the newest lessons with their checks."""
    lines = [
        "# Trade review lessons (free-model debate reviews, ADR-052)",
        "",
        "Each line is one reviewed trade: the judge's process grade, its calls on the stop and "
        "the exit, and what the price did in the candles after the exit (measured by code). "
        "Calls marked wrong are the ones to discount. Simulated money; one trade is a tiny "
        "sample.",
        "",
    ]
    for account in sorted({str(e.get("account")) for e in entries}):
        mine = [e for e in entries if str(e.get("account")) == account]
        sc = scorecard(mine)
        st, ex = sc["stop_call"], sc["exit_call"]
        lines += [
            f"## {account}",
            "",
            f"Stop calls right: {st['right']} of {st['checked']} checked · exit calls right: "
            f"{ex['right']} of {ex['checked']} checked · grade by outcome: "
            + (", ".join(f"{k} {v}" for k, v in sorted(sc["grade_by_outcome"].items())) or "none"),
            "",
        ]
        for e in mine[-n:][::-1]:
            f = e.get("follow_up") or {}
            after = (
                f"after exit {f['end_move_pct']:+.1f}% its way over {f['bars']} bars"
                if "end_move_pct" in f
                else f.get("error", "after exit: waiting for candles")
            )
            pnl = e.get("net_pnl_usd")
            lines.append(
                f"- {e.get('closed_at_utc', '')[:16]} {e.get('side')} {e.get('market')} "
                f"{e.get('exit_reason')} {'' if pnl is None else f'${pnl:,.2f} '}· grade "
                f"{e.get('grade')} · stop {e.get('stop_call')} "
                f"({e.get('stop_call_result', 'pending')}) · exit {e.get('exit_call')} "
                f"({e.get('exit_call_result', 'pending')}) · {after}. Lesson: {e.get('lesson')}"
            )
        lines.append("")
    if not entries:
        lines.append("No debate reviews yet.")
    return "\n".join(lines) + "\n"
