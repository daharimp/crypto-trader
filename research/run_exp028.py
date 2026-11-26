"""EXP-2026-028: the cooldown and the size range together on the ten-coin hourly account
(plan: ``research/EXP-2026-028-plan.md``).

Both rules run as built into the paper account (``risk.cooldown_after_loss_hours``,
``risk.min_collateral_per_position_pct`` with ``trader.perps.confidence``): the loop below is
the EXP-2026-024 loop, handing the account its score and calling the account's own
``apply_signal``. Every run, slice and rule was fixed in the plan before any run with both
rules on; this script only runs them and applies the rules.

Usage: python research/run_exp028.py <data_dir> <cache_dir> <out_dir> <job> [configs_dir]
Jobs: check | <slice>:<variant>[,<variant>...] | verdict
Slices: B1 B2 B3 B4 (the four slices of EXP-2026-025 and EXP-2026-026 for this account).
Variants: N (neither), C4 C12 C24 (cooldown only), R (range only), CR4 CR12 CR24 (both),
T4 T12 T24 (the flat twin of CR_h: same cooldown, fixed size equal to CR_h's average), and
``x2`` after any of them for twice the costs (``CR4x2``). A twin needs its CR run first.
Each run writes ``<out_dir>/<slice>-<variant>.json``. The balance is 100 times the
configured $2,500, as in the earlier experiments.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as base
import exp024_lib as lib
import exp026_lib as x
import numpy as np
import run_exp024 as r24
import run_exp026 as r26

from trader.perps.math import PerpSide
from trader.perps.params import PerpsParams
from trader.perps.simulator import PaperPerpsAccount

D = Decimal
Q = D("0.0001")
LOW, HIGH = D("0.5"), D("1.5")
HOURS = (4, 12, 24)
SLICES = ("B1", "B2", "B3", "B4")
FRESH = ("B3", "B4")
NO_SCORE = "PERP_CONFIDENCE_UNAVAILABLE"


class Cached:
    """A scorer that computes each (market, side, bar) once; the score does not depend on
    the account, so every run of a slice can share it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.memo: dict[tuple[str, PerpSide, datetime], Decimal] = {}

    def at(self, m: str, side: PerpSide, t: datetime, decided: datetime) -> Decimal:
        """The composite for opening ``side`` in ``m`` at the bar that opened at ``t``."""
        key = (m, side, t)
        if key not in self.memo:
            self.memo[key] = self.inner.at(m, side, t, decided)["MC"]
        return self.memo[key]


def run(
    params: PerpsParams,
    feed: lib.Feed,
    start: datetime,
    end: datetime,
    *,
    coins: tuple[str, ...] | list[str],
    scorer: Cached | None = None,
) -> base.Result:
    """
    Replay one account over ``[start, end)`` through the account's own ``apply_signal``.

    Args:
        params (PerpsParams): Account settings; ``markets`` is replaced by ``coins``.
        feed (lib.Feed): Candles and caches.
        start (datetime): First bar.
        end (datetime): Bars opening at or after this are not used.
        coins: Coins traded, in the order the account walks them.
        scorer (Cached | None): Gives the account its confidence score; needed when
            ``params`` carries a size range.

    Returns:
        base.Result: Stats, events and daily equity.
    """
    coins = tuple(coins)
    params = dataclasses.replace(params, markets={m: m for m in coins})
    sig, mov, step = feed.signals(), feed.moves(), base.STEP[feed.tf]
    times = feed.times[bisect.bisect_left(feed.times, start) : bisect.bisect_left(feed.times, end)]
    acct = PaperPerpsAccount.start(params, times[0])
    last_time = {m: feed.order[m][-1] for m in coins}
    last_close: dict[str, Decimal] = {}
    daily: dict[date, float] = {}
    peak, max_dd = acct.cash_usd, D(0)
    for n, t in enumerate(times):
        closes_at = t + step
        row = {m: feed.rows[m][t] for m in coins if t in feed.rows[m]}
        for m, r in row.items():
            last_close[m] = r[4]
        for m in [m for m in acct.positions if last_time[m] < t]:
            acct.close(m, last_close, closes_at, reason="DATA_ENDED")
        if n > 0 and acct.positions:
            marks = dict(last_close)
            favorable = {}
            for m, p in acct.positions.items():
                if m in row:
                    is_long = p.side == PerpSide.LONG
                    marks[m] = row[m][3] if is_long else row[m][2]
                    favorable[m] = row[m][2] if is_long else row[m][3]
            acct.mark(
                marks,
                closes_at,
                opens={m: r[1] for m, r in row.items()},
                favorable=favorable,
                closes=dict(last_close),
            )
        elif n > 0:
            acct.mark(dict(last_close), closes_at)
        # Reason: a coin without the next bar keeps its last close as the mark and is skipped.
        px = dict(last_close)
        tradable = []
        for m in row:
            nxt = feed.rows[m].get(closes_at)
            if nxt is not None and n < len(times) - 1:
                px[m] = nxt[1]
                tradable.append(m)
        for m in tradable:
            move = mov[m].get(t)
            if move is None:
                acct.daily_moves.pop(m, None)
            else:
                acct.daily_moves[m] = move
            target = sig[m].get(t)
            held = acct.positions.get(m)
            acct.confidence = {}
            # Reason: a score is only read by an open. It is skipped where the account
            # cannot open anyway (waiting after a stop or in a cooldown), which saves most
            # of the run time; a wrongly skipped score would show as a refused open
            # (PERP_CONFIDENCE_UNAVAILABLE), and every run is checked for none.
            if (
                scorer is not None
                and target is not None
                and (held is None or held.side != target)
                and m not in acct.stopped_today
                and closes_at >= acct.cooldown_until.get(m, closes_at)
            ):
                acct.confidence = {m: scorer.at(m, target, t, closes_at)}
            acct.apply_signal(m, target, px, closes_at)
        if tradable:
            acct.check_day_loss(px, closes_at)
        equity = acct.equity(px)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        # Reason: a bar closing at 00:00 belongs to the day that just ended.
        daily[(closes_at - timedelta(seconds=1)).date()] = float(equity)
    final = times[-1] + step
    for m in list(acct.positions):
        acct.close(m, last_close, final, reason="END_OF_REPLAY")
    daily[(final - timedelta(seconds=1)).date()] = float(acct.cash_usd)
    return base.Result(base.summarize(acct, daily, max_dd, start, end), acct.events, daily)


def variant(params: PerpsParams, name: str, out: Path, slice_name: str) -> PerpsParams:
    """The account for one variant name (see the module docstring)."""
    twice = name.endswith("x2")
    key = name[:-2] if twice else name
    p = r24.double_costs(params) if twice else params
    if key == "N":
        return p
    if key == "R":
        return dataclasses.replace(
            p, min_collateral_per_position_pct=LOW, max_collateral_per_position_pct=HIGH
        )
    kind, hours = key.rstrip("0123456789"), D(key.lstrip("CRT"))
    p = dataclasses.replace(p, cooldown_after_loss_hours=hours)
    if kind == "C":
        return p
    if kind == "CR":
        return dataclasses.replace(
            p, min_collateral_per_position_pct=LOW, max_collateral_per_position_pct=HIGH
        )
    if kind == "T":
        twin_of = out / f"{slice_name}-CR{key[1:]}{'x2' if twice else ''}.json"
        avg = D(json.loads(twin_of.read_text(encoding="utf-8"))["avg_pct"])
        return dataclasses.replace(p, max_collateral_per_position_pct=avg)
    raise SystemExit(f"unknown variant {name!r}")


def one(
    params: PerpsParams, feed: lib.Feed, sc: Cached, slice_name: str, name: str, out: Path
) -> None:
    """Run one variant on one slice and save what the verdict needs."""
    _, coins, start, end = r26.SLICES[slice_name]
    p = variant(params, name, out, slice_name)
    ranged = p.min_collateral_per_position_pct is not None
    res = run(p, feed, start, end, coins=coins, scorer=sc if ranged else None)
    opened = [e for e in res.events if e["event"] == "OPENED"]
    refused = Counter(
        r for e in res.events if e["event"] == "OPEN_REJECTED" for r in e.get("reasons", [])
    )
    if refused.get(NO_SCORE):
        raise SystemExit(f"{slice_name} {name}: {refused[NO_SCORE]} opens arrived without a score")
    sizes = [D(e["collateral_pct"]) for e in opened] if ranged else []
    avg = p.max_collateral_per_position_pct
    if sizes:
        avg = (sum(sizes, D(0)) / len(sizes)).quantize(Q)
    s0 = float(p.starting_collateral_usd)
    saved = {
        "stats": res.stats,
        "avg_pct": str(avg),
        "waits": sum(1 for e in res.events if e["event"] == "COOLDOWN_STARTED"),
        "refused": {str(k): v for k, v in refused.items()},
        "returns": x.daily_returns(res, s0).tolist(),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{slice_name}-{name}.json").write_text(json.dumps(saved), encoding="utf-8")
    s = res.stats
    print(
        f"{slice_name} {name:7} | size {avg}% | {s['cagr']:8.1f}% a year | Sharpe "
        f"{s['sharpe']:5.2f} | drop {s['dd']:4.1f}% | worst day {s['worst_day']:5.1f}% | "
        f"{s['trades_mo']:6.1f} entries a month | {saved['waits']} waits",
        flush=True,
    )


def check(data: Path, cache: Path, configs: Path | None) -> None:
    """The loop equals the three earlier loops before any run with both rules is read."""
    params = r26.account("B", "1", configs)
    _, coins, start, end = r26.SLICES["B1"]
    feed, sc = r26.load(data, cache, "B1")
    for label, p in (
        ("neither rule", params),
        ("built cooldown 4h", dataclasses.replace(params, cooldown_after_loss_hours=D(4))),
    ):
        old = lib.run(p, feed, start, end, coins=coins)
        new = run(p, feed, start, end, coins=coins)
        same = new.events == old.events and new.daily_equity == old.daily_equity
        print(
            f"B1, {label}: {len(old.events)} events against exp024_lib.run: "
            f"{'identical' if same else 'DIFFERENT'}",
            flush=True,
        )
        if not same:
            raise SystemExit("check FAILED")
    _, coins, start, end = r26.SLICES["B4"]
    feed, sc = r26.load(data, cache, "B4")
    ranged = dataclasses.replace(
        params, min_collateral_per_position_pct=LOW, max_collateral_per_position_pct=HIGH
    )
    native = r26.Native(feed, sc)
    old, _ = x.run(ranged, feed, start, end, coins=coins, scorer=native, native=True)
    new = run(ranged, feed, start, end, coins=coins, scorer=Cached(native))
    same = new.events == old.events and new.daily_equity == old.daily_equity
    print(
        f"B4, built range {LOW}% to {HIGH}%: {len(old.events)} events against "
        f"exp026_lib.run(native=True): {'identical' if same else 'DIFFERENT'}"
    )
    if not same:
        raise SystemExit("check FAILED")


def _load(out: Path, slice_name: str, name: str) -> dict[str, Any]:
    return dict(json.loads((out / f"{slice_name}-{name}.json").read_text(encoding="utf-8")))


def _diff(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float, float]:
    """Sharpe(a) - Sharpe(b) and its 90% paired block-bootstrap interval."""
    lo, hi = x.sharpe_diff_interval(np.array(a["returns"]), np.array(b["returns"]))
    return a["stats"]["sharpe"] - b["stats"]["sharpe"], lo, hi


def verdict(out: Path) -> None:
    """Print every run and apply the plan's two rules to each cooldown length."""
    names = ["N", *(f"C{h}" for h in HOURS), "R"]
    names += [f"{k}{h}" for h in HOURS for k in ("CR", "T")]
    names += ["C4x2", "Rx2", "CR4x2", "T4x2"]
    for s in SLICES:
        print(f"\n== {s}")
        print(
            f"{'run':7} | {'size':>7} | {'a year':>8} | {'Sharpe':>6} | {'drop':>6} | "
            f"{'worst day':>9} | {'ret/drop':>8} | {'entries/mo':>10} | {'waits':>5}"
        )
        for n in names:
            v = _load(out, s, n)
            st = v["stats"]
            ratio = st["cagr"] / st["dd"] if st["dd"] > 0 else 0.0
            print(
                f"{n:7} | {float(v['avg_pct']):6.2f}% | {st['cagr']:7.1f}% | {st['sharpe']:6.2f} | "
                f"{st['dd']:5.1f}% | {st['worst_day']:8.1f}% | {ratio:8.2f} | "
                f"{st['trades_mo']:10.1f} | {v['waits']:5d}"
            )
    for h in HOURS:
        print(f"\n== Cooldown {h} hours: Sharpe differences per slice [90% interval]")
        rule1, rule2 = [], []
        for s in SLICES:
            both, twin, rng = _load(out, s, f"CR{h}"), _load(out, s, f"T{h}"), _load(out, s, "R")
            alone = _load(out, s, f"C{h}")
            d1, d2, d3 = _diff(both, twin), _diff(both, rng), _diff(both, alone)
            rule1.append(d1[0])
            rule2.append(d2[0])
            print(
                f"{s}: both - flat twin {d1[0]:+.3f} [{d1[1]:+.2f}, {d1[2]:+.2f}] | "
                f"both - range only {d2[0]:+.3f} [{d2[1]:+.2f}, {d2[2]:+.2f}] | "
                f"both - cooldown only at 1% {d3[0]:+.3f} [{d3[1]:+.2f}, {d3[2]:+.2f}]"
            )
        fresh = sum(rule1[SLICES.index(s)] > 0 for s in FRESH)
        one_ok = sum(d > 0 for d in rule1) >= 3 and fresh >= 1
        two_ok = sum(d > 0 for d in rule2) >= 3 and min(rule2) >= -0.05
        print(
            f"rule 1 (range still earns its place): above the twin on "
            f"{sum(d > 0 for d in rule1)} of 4, {fresh} of 2 fresh: {'HOLDS' if one_ok else 'FAILS'}"
        )
        print(
            f"rule 2 (cooldown still helps): above range-only on {sum(d > 0 for d in rule2)} "
            f"of 4, lowest {min(rule2):+.3f}: {'HOLDS' if two_ok else 'FAILS'}"
        )
    print("\n== Twice the costs, cooldown 4 hours: Sharpe differences per slice")
    for s in SLICES:
        both, twin = _load(out, s, "CR4x2"), _load(out, s, "T4x2")
        d1, d2 = _diff(both, twin), _diff(both, _load(out, s, "Rx2"))
        d3 = _diff(both, _load(out, s, "C4x2"))
        print(
            f"{s}: both - flat twin {d1[0]:+.3f} [{d1[1]:+.2f}, {d1[2]:+.2f}] | both - range "
            f"only {d2[0]:+.3f} | both - cooldown only at 1% {d3[0]:+.3f}"
        )


def main() -> None:
    """Run one job."""
    data, cache, out, job = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    configs = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    slice_name, _, wanted = job.partition(":")
    if job == "check":
        check(data, cache, configs)
    elif job == "verdict":
        verdict(out)
    elif slice_name in SLICES and wanted:
        params = r26.account("B", "1", configs)
        feed, sc = r26.load(data, cache, slice_name)
        scorer = Cached(r26.Native(feed, sc))
        for name in wanted.split(","):
            one(params, feed, scorer, slice_name, name, out)
    else:
        raise SystemExit(f"unknown job {job!r}")


if __name__ == "__main__":
    main()
