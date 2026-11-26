"""Read-only health check of the paper bots for the server watchdog (ADR-047).

Every check reads saved files or text handed in by the watchdog script (``docker compose ps``
and recent logs); nothing here can place an order, change a setting or restart a service.
A check that cannot read its input reports a problem instead of passing silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Reason: these are the services `docker compose up -d` should keep running; `live` and the
# cli/builder profiles are intentionally absent (live is never started by automation).
EXPECTED_SERVICES = (
    "paper",
    "perps",
    "perps-degen",
    "perps-spot-perps",
    "perps-top10",
    "review",
    "dashboard",
)
# Reason: same 5/10/15% steps as the review assistant's drawdown alerts (ADR-046).
DRAWDOWN_STEPS = ((15.0, "critical"), (10.0, "alert"), (5.0, "warn"))
SEVERITY_RANK = {"warn": 1, "alert": 2, "critical": 3}
SPOT_STALE_AFTER = timedelta(hours=9)  # two missed 4h cycles plus slack
ERROR_LINE = re.compile(r"Traceback|\bERROR\b|\bCRITICAL\b|Exception:")
TIMEFRAMES = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}


@dataclass(frozen=True)
class Problem:
    """One thing the owner should know about."""

    key: str
    severity: str
    message: str


def _drawdown(key: str, label: str, pct: float) -> Problem | None:
    for limit, severity in DRAWDOWN_STEPS:
        if pct >= limit:
            return Problem(key, severity, f"{label} is {pct:.1f}% below its peak")
    return None


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def parse_compose_ps(text: str) -> list[dict[str, Any]]:
    """
    Parse ``docker compose ps --format json`` output (a JSON array or one object per line).

    Args:
        text (str): Command output.

    Returns:
        list[dict[str, Any]]: One dict per container.

    Raises:
        ValueError: If the text is not valid JSON in either shape.
    """
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        rows = json.loads(text)
        return [r for r in rows if isinstance(r, dict)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def check_containers(rows: list[dict[str, Any]]) -> list[Problem]:
    """
    Flag expected services that are not running, and a running ``live`` service.

    Args:
        rows (list[dict[str, Any]]): Parsed ``docker compose ps`` rows.

    Returns:
        list[Problem]: Problems found.
    """
    state = {str(r.get("Service")): str(r.get("State", "")).lower() for r in rows}
    out = [
        Problem(f"container:{svc}", "alert", f"{svc} is {state.get(svc) or 'not created'}")
        for svc in EXPECTED_SERVICES
        if state.get(svc) != "running"
    ]
    if state.get("live") == "running":
        out.append(Problem("container:live", "warn", "the live (real money) service is running"))
    return out


def check_logs(text: str) -> list[Problem]:
    """
    Flag services whose recent ``docker compose logs`` lines contain errors.

    Args:
        text (str): ``docker compose logs --no-color --since ...`` output.

    Returns:
        list[Problem]: One problem per service with error lines.
    """
    hits: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not ERROR_LINE.search(line):
            continue
        # Reason: compose prefixes each line with "<container>  | "; strip the replica suffix.
        name, _, msg = line.partition("|")
        svc = re.sub(r"-\d+$", "", name.strip()).removeprefix("crypto-trader-") or "unknown"
        hits.setdefault(svc, []).append(msg.strip()[:160])
    return [
        Problem(f"logs:{svc}", "alert", f"{svc}: {len(lines)} error line(s), last: {lines[-1]}")
        for svc, lines in sorted(hits.items())
    ]


def check_spot(root: Path, now: datetime) -> tuple[list[Problem], list[dict[str, Any]]]:
    """
    Check every saved spot session: freshness, stops, breaker and drawdown.

    Args:
        root (Path): Data directory.
        now (datetime): Current time (aware).

    Returns:
        tuple[list[Problem], list[dict[str, Any]]]: Problems and one summary per session.
    """
    problems: list[Problem] = []
    summaries: list[dict[str, Any]] = []
    for f in sorted((root / "state").glob("session-*.json")):
        name = f.stem.removeprefix("session-")
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            meta, led = d["meta"], d["ledger"]
            equity = float(meta.get("equity_usd", led["cash"]))
            hwm = float(d.get("loss", {}).get("hwm") or equity)
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(Problem(f"spot:{name}:state", "alert", f"{name}: unreadable state"))
            continue
        last = _ts(meta.get("last_cycle_wall_utc"))
        if last is None or now - last > SPOT_STALE_AFTER:
            problems.append(
                Problem(f"spot:{name}:stale", "alert", f"{name}: no cycle since {last}")
            )
        for inst, p in led.get("positions", {}).items():
            if p.get("stop_price") is None:
                problems.append(
                    Problem(f"spot:{name}:stop:{inst}", "critical", f"{name}: {inst} has no stop")
                )
        if d.get("controls", {}).get("breaker_open"):
            problems.append(Problem(f"spot:{name}:breaker", "alert", f"{name}: breaker is open"))
        dd = (hwm - equity) / hwm * 100 if hwm > 0 else 0.0
        if (p_dd := _drawdown(f"spot:{name}:dd", name, dd)) is not None:
            problems.append(p_dd)
        summaries.append(
            {
                "account": name,
                "equity_usd": round(equity, 2),
                "drawdown_pct": round(dd, 2),
                "positions": len(led.get("positions", {})),
                "last_cycle_utc": str(last) if last else None,
            }
        )
    return problems, summaries


def check_perps(
    accounts: dict[str, tuple[Path, str]],
    stop_pct: Callable[[str], Any],
    now: datetime,
) -> tuple[list[Problem], list[dict[str, Any]]]:
    """
    Check every paper perps account: freshness, stop configured, and drawdown.

    Args:
        accounts (dict[str, tuple[Path, str]]): Account name to (state file, config file).
        stop_pct (Callable[[str], Any]): Returns an account config's stop-loss % of
            collateral; raises if the config does not resolve.
        now (datetime): Current time (aware).

    Returns:
        tuple[list[Problem], list[dict[str, Any]]]: Problems and one summary per account.
    """
    problems: list[Problem] = []
    summaries: list[dict[str, Any]] = []
    for name, (state, config) in accounts.items():
        try:
            stop = stop_pct(config)
        except Exception as exc:  # noqa: BLE001 - any config failure is a problem to report
            stop = None
            problems.append(
                Problem(f"perps:{name}:config", "critical", f"perps {name}: config error {exc}")
            )
        if not state.exists():
            problems.append(Problem(f"perps:{name}:missing", "warn", f"perps {name}: no state"))
            continue
        try:
            d = json.loads(state.read_text(encoding="utf-8"))
            meta, acct = d["meta"], d["account"]
            equity = float(meta.get("equity_usd", acct["cash_usd"]))
            peak = float(meta.get("peak_equity_usd") or equity)
            start = float(meta["start_equity_usd"])
            positions = acct.get("positions", {})
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(Problem(f"perps:{name}:state", "alert", f"perps {name}: bad state"))
            continue
        if positions and stop is None:
            problems.append(
                Problem(f"perps:{name}:stop", "critical", f"perps {name}: open positions, no stop")
            )
        step = TIMEFRAMES.get(str(meta.get("timeframe")), timedelta(hours=4))
        last = _ts(meta.get("last_cycle_utc"))
        if last is None or now - last > step * 2 + timedelta(minutes=30):
            problems.append(
                Problem(f"perps:{name}:stale", "alert", f"perps {name}: no cycle since {last}")
            )
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        if (p_dd := _drawdown(f"perps:{name}:dd", f"perps {name}", dd)) is not None:
            problems.append(p_dd)
        summaries.append(
            {
                "account": f"perps-{name}",
                "equity_usd": round(equity, 2),
                "return_pct": round((equity / start - 1) * 100, 2) if start else None,
                "drawdown_pct": round(dd, 2),
                "max_drawdown_pct": float(meta.get("max_drawdown_pct", 0)),
                "positions": [
                    {"market": m, "side": p.get("side"), "tps_hit": p.get("tps_hit", 0)}
                    for m, p in positions.items()
                ],
                "stop_pct_of_collateral": None if stop is None else str(stop),
                "last_cycle_utc": str(last) if last else None,
            }
        )
    return problems, summaries


def build_snapshot(
    problems: list[Problem], summaries: list[dict[str, Any]], now: datetime, **extra: Any
) -> dict[str, Any]:
    """
    Assemble the JSON snapshot the watchdog saves and pushes.

    Args:
        problems (list[Problem]): All problems found.
        summaries (list[dict[str, Any]]): Account summaries.
        now (datetime): Generation time.
        **extra (Any): Extra top-level fields (e.g. ``commit``, ``containers``).

    Returns:
        dict[str, Any]: Snapshot with ``ok`` True when no alert or critical problem exists.
    """
    worst = max((SEVERITY_RANK[p.severity] for p in problems), default=0)
    return {
        "generated_utc": now.isoformat(),
        "ok": worst < SEVERITY_RANK["alert"],
        "problems": [asdict(p) for p in problems],
        "accounts": summaries,
        **extra,
    }


def alerts_to_send(
    previous: dict[str, Any], problems: list[Problem], now: datetime, remind: timedelta
) -> tuple[list[str], dict[str, Any]]:
    """
    Decide which alerts to send so a lasting problem does not alert every 15 minutes.

    A problem alerts when it is new, when its severity rises, and again every ``remind``
    while it lasts. A problem that clears sends one "resolved" line.

    Args:
        previous (dict[str, Any]): Saved state ``{key: {severity, sent_utc}}``.
        problems (list[Problem]): Problems found now.
        now (datetime): Current time.
        remind (timedelta): Reminder interval for a lasting problem.

    Returns:
        tuple[list[str], dict[str, Any]]: Messages to send and the new saved state.
    """
    messages: list[str] = []
    state: dict[str, Any] = {}
    for p in problems:
        old = previous.get(p.key)
        sent = _ts(old.get("sent_utc")) if old else None
        rose = old is not None and SEVERITY_RANK[p.severity] > SEVERITY_RANK.get(
            str(old.get("severity")), 0
        )
        if old is None or rose or sent is None or now - sent >= remind:
            messages.append(f"{p.severity.upper()}: {p.message}")
            sent = now
        state[p.key] = {"severity": p.severity, "sent_utc": sent.isoformat()}
    messages += [f"resolved: {k}" for k in sorted(set(previous) - set(state))]
    return messages, state
