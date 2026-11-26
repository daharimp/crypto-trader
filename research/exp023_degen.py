"""EXP-2026-023, degen slice: does the hourly "degen" paper account earn its keep?

Research only, paper money only: nothing here places an order or changes a setting. It
replays the real paper engine through ``exp023_lib`` (read its docstring first). The degen
variant table itself is ``run_exp023.py <data> <cache> degen``; this script answers the
three questions that table cannot.

Q2  Does hourly execution earn its keep? Degen and main differ in exactly two settings
    (collateral 5% vs 10% of equity, liquidation buffer 3 vs 4 daily moves) and in the
    feed (1h vs 4h bars), so all eight combinations are replayed and the gap between the
    accounts is split into timeframe, size and stop distance. One diagnostic row keeps the
    1h bars for stops and take-profits but holds the signal between 4h closes.
Q3  How different is degen from main? Live degen (1h) against live main (4h) on the
    holdout: correlation of daily returns, how often the two books agree, and what happened
    when degen's opening stop fired and main's did not.
Q4  What would make degen a useful second experiment?

PRE-SET LIST for Q4 (fixed by the brief before any degen replay existed):
    (a) degen as is;
    (b) degen with buffer 6, and with buffer 8;
    (c) degen with stops and take-profits checked hourly but new entries only when the bar
        closes on a 4h boundary (a ``gate``). The gate can only veto entries: signal-change
        CLOSES still happen every hour in (c), so a position can be closed at 17:00 on the
        provisional hourly reading and the opposite entry then waits for the 20:00 close;
    (d) degen with collateral 10% and buffer 8 (main-like risk on hourly stops).
PRE-SET RANKING: development Sharpe only (2020-10..2023-12). Holdout is printed after the
ranking and does not change it. A Sharpe gap inside the printed 90% interval is noise.
Disclosure: the variant table prints both windows, so the holdout of (a) and (b) had been
seen when this file was written; neither the list nor the ranking rule depends on it. The
Q2 diagnostic row is not a candidate and is not ranked.

Usage: python research/exp023_degen.py <data_dir> <cache_dir>
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as lib
import numpy as np

D = Decimal
H1, H4, SEC = timedelta(hours=1), timedelta(hours=4), timedelta(seconds=1)
BUF, COLL = "liquidation_buffer_daily_moves", "max_collateral_per_position_pct"
WIN = ("dev", "hold")
R_SHARE = 0.30  # every perps account stops at 30% of collateral; that loss is 1R
OPEN_END = datetime.max.replace(tzinfo=UTC)
Runs = dict[str, lib.Result]  # window -> replay
Book = list[tuple[str | None, ...]]


@dataclass
class Trade:
    """One position from its open to its last close, rebuilt from the account's events."""

    market: str
    side: str
    opened: datetime
    entry: float
    size: float
    coll: float
    lev: float
    pnl: float  # net of every fee, take-profit parts included
    tps: int = 0
    closed: datetime = OPEN_END
    exit: float = 0.0
    reason: str = ""

    @property
    def full_stop(self) -> bool:
        """Closed at the opening stop, before any take-profit moved it."""
        return self.reason == "STOP_LOSS" and self.tps == 0

    @property
    def r(self) -> float:
        """Net result in R (1R = the loss the opening stop allows)."""
        return self.pnl / (self.coll * R_SHARE)


def trades(events: list[dict[str, Any]]) -> list[Trade]:
    """Rebuild every trade, in opening order, from ``PaperPerpsAccount.events``."""
    live: dict[str, Trade] = {}
    out: list[Trade] = []
    for e in events:
        kind, m = e["event"], e.get("market", "")
        at = datetime.fromisoformat(e["at_utc"])
        if kind == "OPENED":
            live[m] = Trade(
                m,
                e["side"],
                at,
                float(e["entry"]),
                float(e["size_usd"]),
                float(e["collateral_usd"]),
                float(e["leverage"]),
                -float(e["fee_usd"]),
            )
            out.append(live[m])
        elif kind == "TAKE_PROFIT":
            live[m].tps += 1
            live[m].pnl += float(e["pnl_usd"]) - float(e["fees_usd"])
        elif kind == "CLOSED":
            t = live.pop(m)
            t.pnl += float(e["pnl_usd"]) - float(e["fees_usd"])
            t.closed, t.exit, t.reason = at, float(e["exit"]), e["reason"]
        elif kind == "LIQUIDATED":
            t = live.pop(m)
            t.pnl -= float(e["collateral_lost_usd"])
            t.closed, t.exit, t.reason = at, float(e["mark"]), "LIQUIDATED"
    return out


def both(params: Any, feed: lib.Feed, **switches: Any) -> Runs:
    """Replay one setting over the development and the holdout window."""
    return {w: lib.run(params, feed, *lib.WINDOWS[w], **switches) for w in WIN}


def months(w: str) -> float:
    """Length of a window in months."""
    start, end = lib.WINDOWS[w]
    return (end - start).days / 365.25 * 12


def cells(runs: Runs) -> str:
    """The harness's standard numbers for both windows."""
    return " | ".join(lib.cell(runs[w].stats) for w in WIN)


MECH = (
    f"{'en/mo':>5} {'off4h':>5} {'signal':>6} {'stop':>4} {'stopTP':>6} {'TP3':>3} "
    f"{'R/entry':>7} {'R/mo':>6} {'lev':>4} {'hold':>4}"
)


def mechanics(res: lib.Result, w: str) -> str:
    """How the entries of one replay ended (see the legend printed with the table)."""
    ts = trades(res.events)
    n = len(ts)
    end = Counter(
        "stop" if t.full_stop else "stop_tp" if t.reason == "STOP_LOSS" else t.reason for t in ts
    )
    off = sum(1 for t in ts if t.opened.hour % 4)
    total_r = sum(t.r for t in ts)
    hold = float(np.median([(t.closed - t.opened) / H1 for t in ts]))

    def pct(k: int) -> float:
        return 100 * k / n

    return (
        f"{n / months(w):5.1f} {pct(off):4.0f}% {pct(end['SIGNAL_CHANGED']):5.0f}% "
        f"{pct(end['stop']):3.0f}% {pct(end['stop_tp']):5.0f}% {pct(end['TAKE_PROFIT_3']):2.0f}% "
        f"{total_r / n:+7.3f} {total_r / months(w):+6.2f} {sum(t.lev for t in ts) / n:4.1f} "
        f"{hold:4.0f}"
    )


def signal_changes(feed: lib.Feed, w: str) -> float:
    """Changes of the live signal per month, summed over the three coins."""
    start, end = lib.WINDOWS[w]
    j0, j1 = bisect.bisect_left(feed.times, start), bisect.bisect_left(feed.times, end)
    sig = feed.signals()
    n = sum(1 for m in lib.COINS for j in range(j0 + 1, j1) if sig[m][j] != sig[m][j - 1])
    return n / months(w)


def held_between_4h(feed: lib.Feed) -> dict[str, list[Any]]:
    """The cached 1h signal with each 4h-close reading carried until the next 4h close."""
    out: dict[str, list[Any]] = {}
    for m, series in feed.signals().items():
        last, col = None, []
        for t, v in zip(feed.times, series, strict=True):
            if (t + H1).hour % 4 == 0:
                last = v
            col.append(last)
        out[m] = col
    return out


def day_rets(res: lib.Result, start_usd: float = 2500.0) -> dict[date, float]:
    """Daily returns the way ``lib.summarize`` computes them."""
    out, prev = {}, start_usd
    for d, v in sorted(res.daily_equity.items()):
        out[d] = v / prev - 1
        prev = v
    return out


def paired(a: lib.Result, b: lib.Result) -> tuple[np.ndarray, np.ndarray]:
    """Daily returns of two replays on their common days."""
    x, y = day_rets(a), day_rets(b)
    days = sorted(set(x) & set(y))
    return np.array([x[d] for d in days]), np.array([y[d] for d in days])


def sharpe(x: np.ndarray) -> float:
    """Daily Sharpe on 365 days, as in the harness."""
    return float(x.mean() / x.std(ddof=1) * math.sqrt(365))


def sharpe_gap(a: lib.Result, b: lib.Result, n: int = 2000, block: int = 20) -> str:
    """Sharpe(a) - Sharpe(b) with a 90% interval (paired circular block bootstrap, 20 days)."""
    x, y = paired(a, b)
    rng = np.random.default_rng(23)
    t = len(x)
    starts = rng.integers(0, t, size=(n, t // block + 1))
    idx = ((starts[:, :, None] + np.arange(block)) % t).reshape(n, -1)[:, :t]
    xs, ys = x[idx], y[idx]
    gap = (xs.mean(1) / xs.std(1, ddof=1) - ys.mean(1) / ys.std(1, ddof=1)) * math.sqrt(365)
    lo, hi = np.percentile(gap, [5, 95])
    return f"{sharpe(x) - sharpe(y):+5.2f} [{lo:+5.2f}, {hi:+5.2f}]"


def corr(a: lib.Result, b: lib.Result) -> str:
    """Correlation of daily and of 7-day returns, and the slope of a's daily return on b's."""
    x, y = paired(a, b)
    wk = np.arange(0, len(x), 7)
    wx, wy = np.add.reduceat(np.log1p(x), wk), np.add.reduceat(np.log1p(y), wk)
    slope = float(np.cov(x, y)[0, 1] / y.var(ddof=1))
    daily, weekly = float(np.corrcoef(x, y)[0, 1]), float(np.corrcoef(wx, wy)[0, 1])
    vol = float(x.std(ddof=1) / y.std(ddof=1))
    return f"daily {daily:5.2f}   7-day {weekly:5.2f}   slope {slope:5.2f}   vol ratio {vol:5.2f}"


def books(ts: list[Trade], grid: list[datetime]) -> Book:
    """Side held in SOL, ETH, BTC at each grid time, after that time's events."""
    per = {m: [t for t in ts if t.market == m] for m in lib.COINS}
    opened = {m: [t.opened for t in per[m]] for m in lib.COINS}
    out: Book = []
    for b in grid:
        row = []
        for m in lib.COINS:
            i = bisect.bisect_right(opened[m], b) - 1
            row.append(per[m][i].side if i >= 0 and per[m][i].closed > b else None)
        out.append(tuple(row))
    return out


def overlap(a: Book, b: Book, na: str, nb: str) -> None:
    """Print how often two books agree, per 4h period and per UTC day (six periods)."""
    same = [x == y for x, y in zip(a, b, strict=True)]
    opp = [any(p and q and p != q for p, q in zip(x, y, strict=True)) for x, y in zip(a, b)]
    part = [not s and not o for s, o in zip(same, opp, strict=True)]
    flat = [not any(x) and not any(y) for x, y in zip(a, b, strict=True)]

    def share(v: list[bool]) -> float:
        return 100 * sum(v) / len(v)

    def days(v: list[bool], fn: Any) -> float:
        return 100 * sum(fn(v[i : i + 6]) for i in range(0, len(v), 6)) / (len(v) / 6)

    print(
        f"  4h periods ({len(a)}): identical books {share(same):.1f}% (of which both fully flat "
        f"{share(flat):.1f}%) | same side wherever both hold a coin, but one holds a coin the "
        f"other does not {share(part):.1f}% | opposite sides in at least one coin {share(opp):.1f}%"
    )
    print(
        f"  UTC days ({len(a) // 6}): identical books all day {days(same, all):.1f}% | never on "
        f"opposite sides that day {100 - days(opp, any):.1f}% | opposite sides at some point "
        f"{days(opp, any):.1f}%"
    )
    for k, m in enumerate(lib.COINS):
        c = Counter(
            "same side" if x[k] == y[k] and x[k] else "both flat" if x[k] == y[k] else "opposite"
            if x[k] and y[k] else f"only {na} in" if x[k] else f"only {nb} in"
            for x, y in zip(a, b, strict=True)
        )
        order = ("same side", "both flat", "opposite", f"only {na} in", f"only {nb} in")
        print(f"    {m}: " + ", ".join(f"{key} {100 * c[key] / len(a):.1f}%" for key in order))


def same_day(a: datetime, b: datetime) -> bool:
    """Same UTC day, a bar closing at 00:00 counting for the day that just ended."""
    return (a - SEC).date() == (b - SEC).date()


def stats3(v: list[float], unit: str) -> str:
    """Mean, median and share above zero of a list."""
    if not v:
        return "none"
    pos = 100 * sum(1 for x in v if x > 0) / len(v)
    mean, med = float(np.mean(v)), float(np.median(v))
    return f"mean {mean:+.2f}{unit}, median {med:+.2f}{unit}, above zero {pos:.0f}%"


def stop_study(dg: list[Trade], mn: list[Trade], feed: lib.Feed, w: str) -> None:
    """What main did, and what the price did, each time degen's opening stop fired."""
    per = {m: [t for t in mn if t.market == m] for m in lib.COINS}
    kinds: Counter[str] = Counter()
    main_end: Counter[str] = Counter()
    gap: dict[str, list[float]] = {"both": [], "only": [], "absent": []}
    to_exit, held_r, main_r, days_on = [], [], [], []
    stops = [t for t in dg if t.full_stop]
    for d in stops:
        sgn = 1 if d.side == "long" else -1
        r_px = abs(d.entry - d.exit)  # degen's 1R in price
        with_main = [
            t for t in per[d.market] if t.side == d.side and t.opened < d.closed <= t.closed
        ]
        earlier = [
            t
            for t in per[d.market]
            if t.side == d.side and t.full_stop and t.closed < d.closed
            and same_day(t.closed, d.closed)
        ]
        m = with_main[0] if with_main else None
        if (m is not None and m.full_stop and same_day(m.closed, d.closed)) or (
            m is None and earlier
        ):
            kind = "both"
        elif m is not None:
            kind = "only"
            main_end[
                "a later opening stop" if m.full_stop else "a stop after a take-profit"
                if m.reason == "STOP_LOSS" else m.reason
            ] += 1
            to_exit.append(sgn * (m.exit / d.exit - 1) * 100)
            held_r.append(sgn * (m.exit - d.entry) / r_px)
            main_r.append(m.r)
            days_on.append((m.closed - d.closed) / timedelta(days=1))
        else:
            kind = "absent"
        kinds[kind] += 1
        # Reason: after a stop the coin may reopen at the next 00:00 UTC; the open of that
        # bar against the stop price is what being out until then cost (+) or saved (-).
        midnight = (d.closed - SEC).replace(hour=0, minute=0, second=0) + timedelta(days=1)
        nxt = feed.rows[d.market].get(midnight)
        if nxt is not None:
            gap[kind].append(sgn * (float(nxt[1]) - d.exit) / r_px)
    n = len(stops)
    print(
        f"  degen opening stops (no take-profit reached yet): {n} = {n / months(w):.1f} a month"
        f" of {len(dg) / months(w):.1f} entries"
    )
    text = {
        "both": "main's opening stop on the same coin and side fired that UTC day too",
        "only": "main held the same coin and side and was NOT stopped that day (degen-only stop)",
        "absent": "main was not in that coin on that side at that moment (flat or opposite)",
    }
    for k in ("both", "only", "absent"):
        print(f"    {kinds[k]:4d} ({100 * kinds[k] / n:4.1f}%)  {text[k]}")
    print(
        "  after a degen-only stop, main's trade later ended by: "
        + ", ".join(f"{k.lower().replace('_', ' ')} {v}" for k, v in main_end.most_common())
        + f"; median {float(np.median(days_on)):.1f} days later"
    )
    print(f"    main's own net result on those trades, in main's R: {stats3(main_r, 'R')}")
    print(
        "    price from degen's stop to main's final exit, in the trade's favour: "
        + stats3(to_exit, "%")
    )
    print(
        "    the degen trade held to main's exit instead (no ladder, before costs), in degen's "
        f"R, against -1R taken: {stats3(held_r, 'R')}"
    )
    print(
        "  price at the next 00:00 UTC (degen's earliest re-entry) against the stop price, in "
        "degen's R; plus = the price came back, the stop cost that much; minus = it saved it:"
    )
    for k, label in (("only", "degen-only stops"), ("both", "both stopped"), ("absent", "main absent")):
        print(f"    {label:16}: {stats3(gap[k], 'R')}")
    print(f"    {'all degen stops':16}: {stats3(gap['only'] + gap['both'] + gap['absent'], 'R')}")
    rev = [t for t in mn if t.full_stop]
    alone = sum(
        1
        for t in rev
        if not any(
            d.market == t.market and d.side == t.side and same_day(d.closed, t.closed)
            for d in stops
        )
    )
    print(
        f"  the other way round: main opening stops {len(rev)}; degen's opening stop on that "
        f"coin and side did not fire that day in {alone} ({100 * alone / len(rev):.0f}%)"
    )


def main() -> None:
    """Print the Q2, Q3 and Q4 tables."""
    data, cache = Path(sys.argv[1]), Path(sys.argv[2])
    feeds = {tf: lib.build_feed(data, tf, cache) for tf in ("1h", "4h")}
    f1 = feeds["1h"]
    degen, main_p, spot = (lib.account(n)[0] for n in ("degen", "main", "spot-perps"))
    differ = {
        k: (v, getattr(main_p, k))
        for k, v in dataclasses.asdict(degen).items()
        if v != getattr(main_p, k) and k != "version"
    }
    hdr = f"{lib.HEADER} | {lib.HEADER}"
    print("EXP-2026-023 degen slice. Left block development 2020-10..2023-12, right block")
    print("holdout 2024-01..2026-11-21; each run starts fresh at $2,500. Columns as in")
    print("run_exp023.py: return per year, Sharpe, max drawdown, entries a month, share of")
    print("entries closed by a stop (opening stop or a stop a take-profit had moved), fees")
    print("per year as % of average equity, worst day.")
    print(f"Settings that differ between degen and main (degen, main): {differ}")

    # ---- Q2: all eight combinations of collateral, buffer and feed ---------------------
    cube: dict[tuple[int, int, str], Runs] = {}
    for coll in (5, 10):
        for buf in (3, 4):
            p = dataclasses.replace(degen, **{COLL: D(coll), BUF: D(buf)})
            for tf in ("1h", "4h"):
                cube[coll, buf, tf] = both(p, feeds[tf])
    live_degen, live_main = cube[5, 3, "1h"], cube[10, 4, "4h"]
    held = both(degen, f1, signals=held_between_4h(f1))
    tag = {(5, 3, "1h"): " = live degen", (10, 4, "4h"): " = live main", (10, 4, "1h"): " (main on 1h)"}
    rows = [(f"coll {c:2d}%, buffer {b}, {tf}{tag.get((c, b, tf), '')}", r) for (c, b, tf), r in cube.items()]
    rows.append(("diag: coll 5%, buffer 3, 1h marks, 4h signal", held))
    print("\n== Q2. Does hourly execution earn its keep?")
    print(f"{'setting':44} | {hdr}")
    for label, r in rows:
        print(f"{label:44} | {cells(r)}")
    print("\nSharpe, 1h feed minus 4h feed at the same settings [90% interval]:")
    for coll in (5, 10):
        for buf in (3, 4):
            gaps = "   ".join(
                f"{w} {sharpe_gap(cube[coll, buf, '1h'][w], cube[coll, buf, '4h'][w])}" for w in WIN
            )
            print(f"  coll {coll:2d}%, buffer {buf}: {gaps}")
    gaps = "   ".join(f"{w} {sharpe_gap(held[w], cube[5, 3, '4h'][w])}" for w in WIN)
    print(f"  diag row minus coll 5%, buffer 3, 4h: {gaps}")
    gaps = "   ".join(f"{w} {sharpe_gap(live_degen[w], held[w])}" for w in WIN)
    print(f"  live degen minus diag row (hourly decisions alone): {gaps}")
    print("\nAverage effect of each of the three differences (mean over the other two):")
    effects = (
        ("1h feed instead of 4h", 2, "1h", "4h"),
        ("buffer 4 instead of 3", 1, 4, 3),
        ("collateral 10% instead of 5%", 0, 10, 5),
    )
    keys = (("sharpe", "Sharpe", ".2f"), ("cagr", "CAGR pts", ".0f"), ("dd", "maxDD pts", ".0f"),
            ("trades_mo", "entries/mo", ".1f"), ("fee_drag", "fee/y pts", ".0f"))  # fmt: skip
    for name, axis, hi, lo in effects:
        parts = []
        for key, title, fmt in keys:
            vals = []
            for w in WIN:
                up = [r[w].stats[key] for k, r in cube.items() if k[axis] == hi]
                down = [r[w].stats[key] for k, r in cube.items() if k[axis] == lo]
                vals.append(format(sum(up) / 4 - sum(down) / 4, "+" + fmt))
            parts.append(f"{title} {vals[0]} / {vals[1]}")
        print(f"  {name:28}: " + "   ".join(parts) + "   (dev / hold)")
    print(
        "\nHow the entries ended: entries a month; share opened off the 4h grid; closed by a "
        "signal change /\nthe opening stop / a stop after a take-profit / TP3; mean net result "
        "per entry in R (1R = 30% of\ncollateral); R a month; mean leverage; median hours held."
    )
    print(f"{'setting':44} | {MECH} | {MECH}")
    for label, r in rows:
        print(f"{label:44} | " + " | ".join(mechanics(r[w], w) for w in WIN))
    for tf, how in (("1h", "read every hour (4h candles + latest hourly close)"), ("4h", "read on 4h closes")):
        n = " / ".join(f"{signal_changes(feeds[tf], w):.1f}" for w in WIN)
        print(f"signal changes a month over the three coins, {how}: {n} (dev / hold)")

    # ---- Q3: live degen against live main on the holdout -------------------------------
    spot_runs = both(spot, feeds["4h"])
    print("\n== Q3. How different is degen from main? (live settings; holdout unless marked)")
    print("Daily-return correlation, 7-day-return correlation, slope and volatility ratio of")
    print("the first account against the second:")
    pairs = (
        ("live degen (1h) vs live main (4h)", live_degen, live_main),
        ("live degen (1h) vs live spot-perps (4h)", live_degen, spot_runs),
        ("live main (4h) vs live spot-perps (4h)", live_main, spot_runs),
        ("degen settings on 4h vs live main (4h)", cube[5, 3, "4h"], live_main),
        ("live degen (1h) vs main settings on 1h", live_degen, cube[10, 4, "1h"]),
        ("live degen (1h) vs degen settings on 4h", live_degen, cube[5, 3, "4h"]),
    )
    for label, a, b in pairs:
        print(f"  {label:42} hold: {corr(a['hold'], b['hold'])}")
        print(f"  {'':42}  dev: {corr(a['dev'], b['dev'])}")
    start, end = lib.WINDOWS["hold"]
    grid = [start + k * H4 for k in range(int((end - start) / H4))]
    tr = {n: trades(r["hold"].events) for n, r in (("degen", live_degen), ("main", live_main), ("spot", spot_runs))}
    for n, r in (("degen", live_degen), ("main", live_main)):
        gap = sum(t.pnl for t in tr[n]) - (r["hold"].stats["end"] - 2500)
        print(f"  check, {n}: trade P&L rebuilt from events minus equity change = ${gap:+.2f}")
    print("Books on the 4h grid (the side each account carries into each 4h period):")
    bk = {n: books(t, grid) for n, t in tr.items()}
    for na, nb in (("degen", "main"), ("degen", "spot"), ("main", "spot")):
        print(f" {na} vs {nb}:")
        overlap(bk[na], bk[nb], na, nb)
    print("When degen's opening stop fired (holdout):")
    stop_study(tr["degen"], tr["main"], f1, "hold")

    # ---- Q4: the pre-set list, ranked on development only ------------------------------
    def on_4h_close(acct: Any, market: str, side: Any, j: int) -> bool:
        return (f1.times[j] + H1).hour % 4 == 0

    cands = {
        "(a) degen as is": live_degen,
        "(b) buffer 6": both(dataclasses.replace(degen, **{BUF: D(6)}), f1),
        "(b) buffer 8": both(dataclasses.replace(degen, **{BUF: D(8)}), f1),
        "(c) entries on 4h closes only": both(degen, f1, gate=on_4h_close),
        "(d) collateral 10%, buffer 8": both(dataclasses.replace(degen, **{COLL: D(10), BUF: D(8)}), f1),
    }
    ranked = sorted(cands, key=lambda k: -cands[k]["dev"].stats["sharpe"])
    print("\n== Q4. The pre-set list on 1h bars, ranked on development Sharpe only")
    for w, title in (("dev", "DEVELOPMENT (decides the rank)"), ("hold", "HOLDOUT (shown after ranking)")):
        print(f"{title}\n{'rank variant':33} | {lib.HEADER} | {'Sharpe minus (a) [90%]':22} | vs live main")
        for i, k in enumerate(ranked, 1):
            r = cands[k][w]
            gap = sharpe_gap(r, live_degen[w]) if k != ranked[ranked.index("(a) degen as is")] else ""
            print(f"{i}. {k:30} | {lib.cell(r.stats)} | {gap:22} | {corr(r, live_main[w])}")
    print(f"\n{'variant':33} | {MECH} | {MECH}")
    for k in ranked:
        print(f"{k:33} | " + " | ".join(mechanics(cands[k][w], w) for w in WIN))
    print(f"{'live main (4h), for reference':33} | " + " | ".join(mechanics(live_main[w], w) for w in WIN))


if __name__ == "__main__":
    main()
