"""EXP-2026-023 follow-up: the three backtests the adaptive-research report asked for.

The research report of 2026-11-26 (project files, adaptive-research/) proposed, in order:
1. volatility-width stops with constant-risk sizing and leverage as an output capped near 5x;
2. one open-risk cap for same-direction BTC/ETH/SOL positions (about 2-3% of equity);
3. re-running the ladder-versus-hard-stop comparison (EXP-2026-022) at volatility-width
   stops, and a multi-speed trend blend against the 10/30 range switch.

How they map onto the paper engine (no new engine code is needed for 1 and 3):
- The engine's stop is already a multiple of volatility: leverage is 1 / (buffer x daily
  move), and the stop is 30% of collateral, so the price stop sits about 0.3 x buffer daily
  moves from entry. Buffer 4 (live main) is a 1.2 daily-move stop; buffer 8 is 2.4; buffer
  10 is 3.0. The loss at the stop stays collateral x 30% of equity whatever the buffer, so
  raising the buffer IS "wider volatility stop at constant risk per trade".
- "Leverage capped near 5x" is ``target_leverage`` (live 25).
- The open-risk cap is the harness's ``group_cap``.
- The blend is tested as a direction vote, because the engine's signals say long, short or
  flat and the risk code sizes: three EMA pairs on 4h closes, (16, 64), (32, 128) and
  (64, 256), one vote each, majority decides. One setting, taken from the report, not tuned.

Fixed list for ``main`` (written before any of these was run):
  A. leverage cap 5x at buffer 4, 8 and 10
  B. ladder versus no ladder at buffer 4, 8 and 12 (no ladder is a reference: UD-32)
  C. EMA vote signal at buffer 4 and 8, against the live signal
  D. the report's package: buffer 8, leverage cap 5x, group cap 3% (1% risk a position when
     all three coins line up) and the same with group cap 6% (2% a position)
and for ``spot-perps`` (1x): C only.

Usage: python research/exp023_followup.py <data_dir> <cache_dir>
"""

from __future__ import annotations

import dataclasses
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as lib

from trader.perps.math import PerpSide

D = Decimal
BUF = "liquidation_buffer_daily_moves"
PAIRS = ((16, 64), (32, 128), (64, 256))
WARMUP = 300  # bars before the slowest average is trusted


def ema_vote() -> lib.SignalFn:
    """Majority vote of three EMA pairs; keeps running averages between bars (4h feed only)."""
    spans = sorted({s for pair in PAIRS for s in pair})
    state: dict[int, float] = {}
    seen = 0

    def fn(closes: list[Decimal]) -> PerpSide | None:
        nonlocal seen
        x = float(closes[-1])
        for s in spans:
            a = 2 / (s + 1)
            state[s] = x if s not in state else a * x + (1 - a) * state[s]
        seen += 1
        if seen < WARMUP:
            return None
        votes = sum((state[f] > state[s]) - (state[f] < state[s]) for f, s in PAIRS)
        return PerpSide.LONG if votes > 0 else PerpSide.SHORT if votes < 0 else None

    return fn


def table(
    name: str, feed: lib.Feed, rows: list[tuple[str, dict[str, Any], dict[str, Any]]]
) -> None:
    """Print development | validation for each variant."""
    base, _ = lib.account(name)
    vote = feed.signals("followup-ema-vote-v1", ema_vote)
    print(f"\n== {name}")
    print(f"{'variant':44} | {lib.HEADER} | {lib.HEADER}")
    for label, changed, switches in rows:
        params = dataclasses.replace(base, **changed)
        opts = dict(switches)
        signals = vote if opts.pop("vote", False) else None
        cells = [
            lib.cell(lib.run(params, feed, *lib.WINDOWS[w], signals=signals, **opts).stats)
            for w in ("dev", "hold")
        ]
        print(f"{label:44} | {cells[0]} | {cells[1]}", flush=True)


def main() -> None:
    """Run the fixed list."""
    feed = lib.build_feed(Path(sys.argv[1]), "4h", Path(sys.argv[2]))
    cap5 = {"target_leverage": D(5)}
    none = {"take_profits": None}
    rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("live", {}, {}),
        ("A. leverage cap 5x", cap5, {}),
        ("A. leverage cap 5x + buffer=8", {**cap5, BUF: D(8)}, {}),
        ("A. leverage cap 5x + buffer=10", {**cap5, BUF: D(10)}, {}),
        ("B. buffer=4 ladder (= live)", {}, {}),
        ("B. buffer=4 no ladder", none, {}),
        ("B. buffer=8 ladder", {BUF: D(8)}, {}),
        ("B. buffer=8 no ladder", {BUF: D(8), **none}, {}),
        ("B. buffer=12 ladder", {BUF: D(12)}, {}),
        ("B. buffer=12 no ladder", {BUF: D(12), **none}, {}),
        ("C. EMA vote", {}, {"vote": True}),
        ("C. EMA vote + buffer=8", {BUF: D(8)}, {"vote": True}),
        ("C. live signal + buffer=8", {BUF: D(8)}, {}),
        ("D. buffer=8, cap 5x, group cap 3%", {**cap5, BUF: D(8)}, {"group_cap": D(3)}),
        ("D. buffer=8, cap 5x, group cap 6%", {**cap5, BUF: D(8)}, {"group_cap": D(6)}),
    ]
    table("main", feed, rows)
    table("spot-perps", feed, [("live", {}, {}), ("C. EMA vote", {}, {"vote": True})])


if __name__ == "__main__":
    main()
