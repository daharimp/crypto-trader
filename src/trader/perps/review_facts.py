"""Fact pack for the review assistant (ADR-039): every number comes from code, not a model.

The assistant's roles read only this pack, so they argue from the same measured facts: the
paper account's saved state and event log, its settings file, and public 4h candles. Nothing
here writes a file, places an order, or holds a key.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trader.profiles.loader import ConfigLoadError, load_yaml

from .session import read_status

# Paper accounts the assistant can review: name -> (settings file under configs/perps/, file
# stem of data/state/<stem>.json and data/logs/<stem>-events.jsonl). Mirrors the accounts the
# paper session runs (ADR-038).
ACCOUNTS = {
    "main": ("jupiter.yaml", "perps-paper"),
    "degen": ("jupiter-degen.yaml", "perps-degen"),
    "spot-perps": ("jupiter-spot-perps.yaml", "perps-spot-perps"),
}
# Settings a proposal may name. Costs, venue limits, markets and the starting balance are
# facts about the venue or the account, not strategy settings, so they are never proposed.
ADJUSTABLE = (
    "liquidation_buffer_daily_moves",
    "max_collateral_per_position_pct",
    "stop_loss_pct_of_collateral",
    "daily_loss_limit_pct",
    "target_leverage",
    "max_open_positions",
    "max_total_size_pct_of_equity",
    "min_liquidation_distance_pct",
)
BARS_PER_DAY = 6  # 4h candles
CandleFetcher = Callable[[str, str], list[list[float]]]


def account_files(data_root: Path, account: str) -> tuple[Path, Path]:
    """
    State file and event log of a paper account.

    Args:
        data_root (Path): Data directory.
        account (str): A name from ``ACCOUNTS``.

    Returns:
        tuple[Path, Path]: ``(state, events)``.

    Raises:
        ValueError: If the account is unknown.
    """
    if account not in ACCOUNTS:
        raise ValueError(f"unknown account {account!r}; choose one of {sorted(ACCOUNTS)}")
    stem = ACCOUNTS[account][1]
    return data_root / "state" / f"{stem}.json", data_root / "logs" / f"{stem}-events.jsonl"


def read_events(path: Path) -> list[dict[str, Any]]:
    """
    Every readable event of an account's log, oldest first (bad lines are skipped).

    Args:
        path (Path): Event log (JSON lines).

    Returns:
        list[dict[str, Any]]: Events.
    """
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(e, dict) and "event" in e and "at_utc" in e:
            out.append(e)
    return out


def bad_days(events: list[dict[str, Any]]) -> list[str]:
    """UTC days (YYYY-MM-DD) on which the account journaled ``DAY_HALTED``."""
    return sorted(
        {str(e.get("day") or e["at_utc"][:10]) for e in events if e["event"] == "DAY_HALTED"}
    )


def read_settings(configs_root: Path, account: str) -> dict[str, Any]:
    """
    The account's settings as written in its file, including any the code does not know.

    Args:
        configs_root (Path): Config directory.
        account (str): A name from ``ACCOUNTS``.

    Returns:
        dict[str, Any]: ``file``, ``version`` and ``risk`` (key -> value, ref, approved_on),
        or ``error`` when the file cannot be read.
    """
    name = ACCOUNTS[account][0]
    try:
        raw = load_yaml(configs_root / "perps" / name)
    except ConfigLoadError as exc:
        return {"file": name, "error": str(exc)}
    risk = {
        k: {f: v.get(f) for f in ("value", "ref", "approved_on") if isinstance(v, dict)}
        for k, v in (raw.get("risk") or {}).items()
    }
    return {"file": name, "version": raw.get("version"), "risk": risk}


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2)


def market_facts(fetch: CandleFetcher, markets: list[str]) -> dict[str, Any]:
    """
    What each market did, from completed 4h candles (the forming one is dropped).

    Args:
        fetch (CandleFetcher): Public candle fetcher (symbol, timeframe) -> rows.
        markets (list[str]): Market names, e.g. ``["BTC", "ETH", "SOL"]``.

    Returns:
        dict[str, Any]: Per market: last close, % change over 1, 7 and 30 days, the last
        day's high and low, the typical daily move, the 30-day trend's side and the price at
        which it would flip; or ``error`` when the data is short or unavailable.
    """
    out: dict[str, Any] = {}
    month = 30 * BARS_PER_DAY
    for m in markets:
        try:
            rows = fetch(f"{m}/USD", "4h")[:-1]
        except Exception as exc:  # noqa: BLE001 - one market's outage is a fact, not a crash
            out[m] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        closes = [float(r[4]) for r in rows]
        if len(closes) <= month:
            out[m] = {"error": f"only {len(closes)} completed 4h candles; 181 needed"}
            continue
        rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - month, len(closes))]
        last, ago = closes[-1], closes[-1 - month]
        day = rows[-BARS_PER_DAY:]
        out[m] = {
            "last_close": last,
            "last_candle_open_utc": datetime.fromtimestamp(rows[-1][0] / 1000, UTC).isoformat(),
            "change_1d_pct": _pct(last, closes[-1 - BARS_PER_DAY]),
            "change_7d_pct": _pct(last, closes[-1 - 7 * BARS_PER_DAY]),
            "change_30d_pct": _pct(last, ago),
            "last_day_high": max(float(r[2]) for r in day),
            "last_day_low": min(float(r[3]) for r in day),
            "typical_daily_move_pct": round(
                statistics.stdev(rets) * math.sqrt(BARS_PER_DAY) * 100, 2
            ),
            "trend_side_30d": "long" if last > ago else "short" if last < ago else "flat",
            "trend_flips_at_price": ago,
        }
    return out


def day_summary(events: list[dict[str, Any]], day: str) -> dict[str, Any]:
    """
    What the account did on one UTC day.

    Args:
        events (list[dict[str, Any]]): The account's events.
        day (str): ``YYYY-MM-DD``.

    Returns:
        dict[str, Any]: Event counts, closed trades with dollars, refused opens by reason, the
        day's starting equity (from ``DAY_ROLLED``) and any ``DAY_HALTED`` record.
    """
    todays = [e for e in events if e["at_utc"][:10] == day]
    start = next(
        (e.get("equity_usd") for e in events if e["event"] == "DAY_ROLLED" and e.get("day") == day),
        None,
    )
    trades = [
        {
            k: e.get(k)
            for k in (
                "at_utc",
                "event",
                "market",
                "side",
                "exit",
                "mark",
                "pnl_usd",
                "fees_usd",
                "reason",
                "collateral_lost_usd",
            )
        }
        for e in todays
        if e["event"] in ("CLOSED", "LIQUIDATED")
    ]
    refused = Counter(
        r for e in todays if e["event"] == "OPEN_REJECTED" for r in e.get("reasons", [])
    )
    return {
        "day": day,
        "day_start_equity_usd": start,
        "event_counts": dict(Counter(e["event"] for e in todays)),
        "closed_trades": trades,
        "opens": [
            {
                k: e.get(k)
                for k in (
                    "at_utc",
                    "market",
                    "side",
                    "entry",
                    "leverage",
                    "size_usd",
                    "collateral_usd",
                )
            }
            for e in todays
            if e["event"] == "OPENED"
        ],
        "refused_opens_by_reason": dict(refused),
        "bad_day": next((e for e in todays if e["event"] == "DAY_HALTED"), None),
    }


def build_facts(
    account: str,
    day: str | None,
    data_root: Path,
    configs_root: Path,
    fetch: CandleFetcher,
    now: datetime,
) -> dict[str, Any]:
    """
    The whole fact pack for one review.

    Args:
        account (str): A name from ``ACCOUNTS``.
        day (str | None): UTC day to review; None means the latest bad day, else today.
        data_root (Path): Data directory.
        configs_root (Path): Config directory.
        fetch (CandleFetcher): Public candle fetcher.
        now (datetime): Current time (UTC).

    Returns:
        dict[str, Any]: JSON-serializable facts.

    Raises:
        ValueError: If the account is unknown or has never run.
    """
    state, log = account_files(data_root, account)
    status = read_status(state)
    if status is None:
        raise ValueError(f"the {account} paper account has not run on this machine yet ({state})")
    events = read_events(log)
    halted = bad_days(events)
    day = day or (halted[-1] if halted else now.date().isoformat())
    closed = [e for e in events if e["event"] in ("CLOSED", "LIQUIDATED")]
    settings = read_settings(configs_root, account)
    markets = sorted({p["market"] for p in status["positions"]} | {"BTC", "ETH", "SOL"})
    return {
        "account": account,
        "review_day_utc": day,
        "generated_at_utc": now.isoformat(),
        "money": "simulated (paper); nothing here can place a real order",
        "account_status": status,
        "day": day_summary(events, day),
        "all_bad_days": halted,
        "recent_closed_trades": closed[-20:],
        "closed_trades_total": len(closed),
        "settings": settings,
        "adjustable_settings": list(ADJUSTABLE),
        "markets": market_facts(fetch, markets),
        "rule": (
            f"{status['signal']} on {status['timeframe']} candles: long while the price is above "
            "its level 30 days ago, short while below; strategies only choose the side, the "
            "risk code sizes every position from the settings"
        ),
    }
