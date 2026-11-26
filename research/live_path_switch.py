"""A running account switched to new settings, through the real bot loop (ADR-056).

Drives ``PerpsSession`` (the code the server runs) hour by hour over stored candles for the
ten-coin hourly account as it started (1% a position, no cooldown), then restarts it part
of the way through under a size range of 0.5% to 1.5% chosen by confidence and a 4-hour
cooldown, as the next settings version, on the same saved state. That is how a settings
change reaches the server: the file changes, the service restarts, the run continues. It
then checks what must hold across the change. All values are set in memory here, whatever
the settings file holds; no settings file is written.

Usage: python research/live_path_switch.py <data_dir> [days] [switch_after_days] [configs_dir]
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from live_path_range import END, HIGH, LOW, Exchange, load_series

from trader.perps.candles import PacedFetcher
from trader.perps.params import PerpsParams, load_perps_params
from trader.perps.session import PerpsSession
from trader.perps.signals import DEFAULT_SIGNAL, make_signal

D = Decimal
HOURS = D(4)


def drive(
    params: PerpsParams, feed: Exchange, tmp: Path, begin: datetime, until: datetime
) -> tuple[list[dict[str, Any]], int]:
    """Run a (re)started session once an hour, four minutes past, over ``(begin, until]``."""
    session = PerpsSession(
        params,
        PacedFetcher(feed, spacing_s=0.0),
        tmp / "state.json",
        tmp / "events.jsonl",
        signal=make_signal(DEFAULT_SIGNAL, 6),
        signal_name=DEFAULT_SIGNAL,
        timeframe="1h",
        trend_timeframe="4h",
        settle_seconds=180,
    )
    events: list[dict[str, Any]] = []
    now, cycles, asked = begin + timedelta(hours=1, minutes=4), 0, feed.calls
    while now < until + timedelta(minutes=5):
        feed.now = now
        assert session.due(now), now
        events += session.cycle(now)
        cycles += 1
        now += timedelta(hours=1)
    return events, (feed.calls - asked) // max(cycles, 1)


def positions(tmp: Path) -> dict[str, Any]:
    """The open positions in the saved state."""
    saved = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
    return dict(saved["account"]["positions"])


def check(what: str, ok: bool) -> None:
    """Print one line and stop at the first thing that does not hold."""
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        raise SystemExit(f"switch check FAILED: {what}")


def main() -> None:
    """Run the plain account and the switched one, and compare."""
    data = Path(sys.argv[1])
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    after = int(sys.argv[3]) if len(sys.argv) > 3 else days // 2
    configs = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("configs")
    start = END - timedelta(days=days)
    switch = start + timedelta(days=after)
    old = dataclasses.replace(
        load_perps_params(configs, "top10.yaml"),
        version=1,
        min_collateral_per_position_pct=None,
        max_collateral_per_position_pct=D(1),
        cooldown_after_loss_hours=None,
    )
    new = dataclasses.replace(
        old,
        version=2,
        min_collateral_per_position_pct=LOW,
        max_collateral_per_position_pct=HIGH,
        cooldown_after_loss_hours=HOURS,
    )
    series = load_series(data, list(old.markets))
    plain, _ = drive(old, Exchange(series), Path(tempfile.mkdtemp()), start, END)

    tmp, feed = Path(tempfile.mkdtemp()), Exchange(series)
    before, asked_before = drive(old, feed, tmp, start, switch)
    held = positions(tmp)
    state_before = json.loads((tmp / "state.json").read_text(encoding="utf-8"))
    first, _ = drive(new, feed, tmp, switch, switch + timedelta(hours=1))
    held_after = positions(tmp)
    rest, asked_after = drive(new, feed, tmp, switch + timedelta(hours=1), END)
    later = first + rest
    saved = json.loads((tmp / "state.json").read_text(encoding="utf-8"))

    print(
        f"{days} days to {END:%Y-%m-%d}, switched after {after} days ({switch:%Y-%m-%d %H:%M} "
        f"UTC): {len(before)} events before, {len(later)} after"
    )
    check(
        f"until the switch the run is the plain account's, event for event ({len(before)})",
        before == plain[: len(before)],
    )
    notes = [e for e in before + later if e["event"] == "SETTINGS_CHANGED"]
    want = {
        "min_collateral_per_position_pct": {"from": None, "to": "0.5"},
        "max_collateral_per_position_pct": {"from": "1", "to": "1.5"},
        "cooldown_after_loss_hours": {"from": None, "to": "4"},
    }
    check(
        "one SETTINGS_CHANGED, the first event of the first cycle after the restart, with "
        "the three changed values and versions 1 to 2",
        len(notes) == 1
        and first[0] is notes[0]
        and notes[0]["changed"] == want
        and (notes[0]["from_version"], notes[0]["to_version"]) == (1, 2),
    )
    # Reason: a position the first new cycle closed (its signal changed that hour) is gone
    # or replaced by a new one; the others are told by their opening time.
    same = [
        m for m in held if m in held_after and held[m]["opened_at"] == held_after[m]["opened_at"]
    ]
    kept = all(
        held[m][k] == held_after[m][k]
        for m in same
        for k in ("side", "size_usd", "collateral_usd", "entry_price", "initial_stop")
    )
    closed = {e["market"] for e in first if e["event"] in ("CLOSED", "LIQUIDATED")}
    check(
        f"of the {len(held)} positions open at the switch, the {len(same)} that the first new "
        f"cycle did not close keep side, size, collateral, entry and stop",
        bool(same) and kept and set(held) - set(same) == closed,
    )
    check(
        "the saved run is the same run: same start, cycles counted on, version now 2",
        saved["meta"]["started_at"] == state_before["meta"]["started_at"]
        and saved["meta"]["cycles"] == days * 24
        and saved["meta"]["config_version"] == 2
        and state_before["meta"]["config_version"] == 1,
    )
    opened_before = [e for e in before if e["event"] == "OPENED"]
    opened_after = [e for e in later if e["event"] == "OPENED"]
    sizes = [D(e["collateral_pct"]) for e in opened_after if "collateral_pct" in e]
    check(
        f"no open before the switch carries a score ({len(opened_before)}); every open after "
        f"it does, sized inside the range ({len(opened_after)}: "
        f"{min(sizes):.2f}% to {max(sizes):.2f}%)",
        not any("confidence" in e for e in opened_before)
        and len(sizes) == len(opened_after)
        and all(LOW <= s <= HIGH for s in sizes),
    )
    waits = [e for e in later if e["event"] == "COOLDOWN_STARTED"]
    early = 0
    for w in waits:
        until = datetime.fromisoformat(w["until_utc"])
        started = datetime.fromisoformat(w["at_utc"])
        early += sum(
            e["market"] == w["market"]
            # Reason: an event carries the fill time, four minutes after the candle closed.
            and started < datetime.fromisoformat(e["at_utc"]) < until
            for e in opened_after
        )
    check(
        f"cooldowns start only after the switch ({len(waits)}), and no coin opens during its own",
        not any(e["event"] == "COOLDOWN_STARTED" for e in before) and bool(waits) and early == 0,
    )
    refused = [r for e in later if e["event"] == "OPEN_REJECTED" for r in e["reasons"]]
    check(
        "no open was refused for want of a score",
        "PERP_CONFIDENCE_UNAVAILABLE" not in refused,
    )
    check(
        f"candle requests a cycle: {asked_before} before, {asked_after} after (daily candles "
        "are read once the range is on)",
        (asked_before, asked_after) == (20, 30),
    )


if __name__ == "__main__":
    main()
