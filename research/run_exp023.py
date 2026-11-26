"""EXP-2026-023: why the paper perps bots lose, and what to change (research only).

Owner (2026-11-26): "I don't like this trading bot's performance, how can I improve it now."
The live runs (started 2026-11-22) closed 9 trades by 2026-11-24, all stops and all the
same short on BTC, ETH and SOL, so the live sample cannot tell good settings from bad. This
script replays the real paper engine on 2020-2026 candles (see ``exp023_lib``) and changes
one thing at a time against the live setting of each account.

Variants:
- ``live``: configs/perps/<file> and the live signal, as deployed.
- ``plain 50/200``: the 50/200 rule without the switch to 10/30 averages while "ranging".
- ``group_cap=X``: same-side open risk capped at X% of equity (live: 3 x 3% = 9% on main).
- ``buffer=N``: liquidation buffer in daily moves (main 4, degen 3). The stop stays at 30%
  of collateral, so a bigger buffer means lower leverage and a wider price stop (stop
  distance is about 0.3 x buffer daily moves). Changes leverage: owner decision.
- ``reentry=breakout``: after a stop, wait for a new 20-bar extreme before re-entering.
- ``no ladder``: reference only (the owner asked for the ladder, UD-32).
- spot-perps: the ADR-045 ladder, a wider stop, a bigger position.

Left block development 2020-10..2023-12, right block holdout 2024-01..2026-11-21; each run
starts fresh at $2,500. Columns: return per year, Sharpe, max drawdown, entries per month,
share of entries that ended at the stop, fees per year as % of average equity, worst day.

Usage: uv run python research/run_exp023.py <data_dir> [cache_dir] [account ...]
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as lib

D = Decimal


def variants(name: str) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(label, settings changed, replay switches) for one account."""
    yield "live", {}, {}
    yield "plain 50/200", {}, {"plain": True}
    if name == "spot-perps":
        yield "ladder 4/8/12R", {"take_profits": lib.LADDER}, {}
        yield "stop 10%", {"stop_loss_pct_of_collateral": D(10)}, {}
        yield (
            "stop 10% + ladder",
            {"stop_loss_pct_of_collateral": D(10), "take_profits": lib.LADDER},
            {},
        )
        yield "collateral 25%", {"max_collateral_per_position_pct": D(25)}, {}
        yield "reentry=breakout", {}, {"breakout_reentry": True}
        return
    buf = "liquidation_buffer_daily_moves"
    for cap in ("3", "4.5", "6"):
        yield f"group_cap={cap}%", {}, {"group_cap": D(cap)}
    for b in ("6", "8", "10", "12"):
        yield f"buffer={b}", {buf: D(b)}, {}
    yield "buffer=8 + group_cap=6%", {buf: D(8)}, {"group_cap": D(6)}
    yield "reentry=breakout", {}, {"breakout_reentry": True}
    yield "buffer=8 + reentry=breakout", {buf: D(8)}, {"breakout_reentry": True}
    yield "plain 50/200 + buffer=8", {buf: D(8)}, {"plain": True}
    yield "no ladder (reference)", {"take_profits": None}, {}
    yield "buffer=8, no ladder (reference)", {buf: D(8), "take_profits": None}, {}


def main() -> None:
    """Print one table per account."""
    data = Path(sys.argv[1])
    rest = sys.argv[2:]
    cache = Path(rest.pop(0)) if rest and rest[0] not in lib.ACCOUNTS else None
    feeds: dict[str, lib.Feed] = {}
    for name in rest or list(lib.ACCOUNTS):
        base, tf = lib.account(name)
        feed = feeds.setdefault(tf, lib.build_feed(data, tf, cache))
        plain = feed.signals("plain-50-200", lib.plain_50_200)
        print(f"\n== {name} ({lib.ACCOUNTS[name][0]}, {tf} bars)")
        print(f"{'variant':32} | {lib.HEADER} | {lib.HEADER}")
        for label, changed, switches in variants(name):
            params = dataclasses.replace(base, **changed)
            opts = dict(switches)
            signals = plain if opts.pop("plain", False) else None
            cells = [
                lib.cell(lib.run(params, feed, *lib.WINDOWS[w], signals=signals, **opts).stats)
                for w in ("dev", "hold")
            ]
            print(f"{label:32} | {cells[0]} | {cells[1]}", flush=True)


if __name__ == "__main__":
    main()
