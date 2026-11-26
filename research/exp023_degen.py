"""EXP-2026-023, degen slice: does the hourly "degen" paper account earn its keep?

Research only, paper money only: nothing here places an order or changes a setting. It
replays the real paper engine through ``exp023_lib`` (read its docstring first). The degen
variant table itself is ``run_exp023.py <data> <cache> degen``; this script answers the
three questions that table cannot.

Q2  Does hourly execution earn its keep? Degen and main differ in exactly two settings
    (collateral 5% vs 10% of equity, liquidation buffer 3 vs 4 daily moves) and in the
    feed (1h vs 4h bars), so all eight combinations are replayed and the gap between the
    accounts is split into timeframe, size and stop distance. Diagnostic rows (not
    candidates): 1h bars for stops and take-profits with the signal held between 4h
    closes, and the plain 50/200 signal on both feeds.
Q3  How different is degen from main? Live degen (1h) against live main (4h) on the
    holdout: correlation of daily returns, how often the books agree, and what happened
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
ranking and does not change it. A Sharpe gap whose 90% interval spans zero is noise.
Disclosure: the variant table prints both windows, so the holdout of (a) and (b) had been
seen when this file was written; neither the list nor the ranking rule depends on it. The
Q2 diagnostic rows and the "signal held between 4h closes" rows under Q4 were added after
the eight-combination table had shown where the hourly loss comes from (both windows
seen); they explain the result, are not ranked and are not part of the pre-set list.

Usage: python research/exp023_degen.py <data_dir> <cache_dir>
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import sys
from collections import Counter, defaultdict
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
ENDS = {"SIGNAL_CHANGED": "signal", "TAKE_PROFIT_3": "tp3", "STOP_LOSS": "stop"}
Runs = dict[str, lib.Result]  # window -> replay
Book = list[tuple[str | None, ...]]


@dataclass
class Trade:
    """One position from its open to its last close, rebuilt from the account's events."""

    market: str
    side: str
    opened: datetime
    entry: float
    coll: float
    lev: float
    pnl: float  # net of every fee, take-profit parts included
    tps: int = 0
    closed: datetime = datetime.max.replace(tzinfo=UTC)
    exit: float = 0.0
    end: str = ""  # signal, stop (the opening stop), stop_tp (a moved stop), tp3, other

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
            num = [float(e[k]) for k in ("entry", "collateral_usd", "leverage")]
            live[m] = Trade(m, e["side"], at, *num, pnl=-float(e["fee_usd"]))
            out.append(live[m])
        elif kind == "TAKE_PROFIT":
            live[m].tps += 1
            live[m].pnl += float(e["pnl_usd"]) - float(e["fees_usd"])
        elif kind == "CLOSED":
            t = live.pop(m)
            t.pnl += float(e["pnl_usd"]) - float(e["fees_usd"])
            t.closed, t.exit, t.end = at, float(e["exit"]), ENDS.get(e["reason"], "other")
            if t.end == "stop" and t.tps:
                t.end = "stop_tp"
        elif kind == "LIQUIDATED":
            t = live.pop(m)
            t.pnl -= float(e["collateral_lost_usd"])
            t.closed, t.exit, t.end = at, float(e["mark"]), "other"
    return out


def both(params: Any, feed: lib.Feed, **switches: Any) -> Runs:
    """Replay one setting over the development and the holdout window."""
    return {w: lib.run(params, feed, *lib.WINDOWS[w], **switches) for w in WIN}


def months(w: str) -> float:
    """Length of a window in months."""
    start, end = lib.WINDOWS[w]
    return (end - start).days / 365.25 * 12


MECH = (
    f"{'en/mo':>5} {'off4h':>5} {'signal':>6} {'stop':>4} {'stopTP':>6} {'TP3':>3} "
    f"{'R/entry':>7} {'R/mo':>6} {'lev':>4} {'hold':>4}"
)


def mechanics(runs: Runs) -> str:
    """How the entries of a setting ended, both windows (legend printed with the table)."""
    out = []
    for w in WIN:
        ts = trades(runs[w].events)
        n = len(ts)
        end = Counter(t.end for t in ts)
        off = sum(1 for t in ts if t.opened.hour % 4)
        total_r = sum(t.r for t in ts)
        hold = float(np.median([(t.closed - t.opened) / H1 for t in ts]))
        out.append(
            f"{n / months(w):5.1f} {100 * off / n:4.0f}% {100 * end['signal'] / n:5.0f}% "
            f"{100 * end['stop'] / n:3.0f}% {100 * end['stop_tp'] / n:5.0f}% "
            f"{100 * end['tp3'] / n:2.0f}% {total_r / n:+7.3f} {total_r / months(w):+6.2f} "
            f"{sum(t.lev for t in ts) / n:4.1f} {hold:4.0f}"
        )
    return " | ".join(out)


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


def sharpe_gap(a: Runs, b: Runs, n: int = 2000, block: int = 20) -> str:
    """Sharpe(a) - Sharpe(b) per window with a 90% interval (paired 20-day block bootstrap)."""
    out = []
    for w in WIN:
        x, y = paired(a[w], b[w])
        rng = np.random.default_rng(23)
        t = len(x)
        starts = rng.integers(0, t, size=(n, t // block + 1))
        idx = ((starts[:, :, None] + np.arange(block)) % t).reshape(n, -1)[:, :t]
        boot = [(v[idx].mean(1) / v[idx].std(1, ddof=1)) * math.sqrt(365) for v in (x, y)]
        lo, hi = np.percentile(boot[0] - boot[1], [5, 95])
        point = (x.mean() / x.std(ddof=1) - y.mean() / y.std(ddof=1)) * math.sqrt(365)
        out.append(f"{point:+5.2f} [{lo:+5.2f}, {hi:+5.2f}]")
    return " | ".join(out)


def corr(a: lib.Result, b: lib.Result) -> str:
    """Correlation of daily and of 7-day returns, slope of a on b, ratio of volatilities."""
    x, y = paired(a, b)
    wk = np.arange(0, len(x), 7)
    wx, wy = np.add.reduceat(np.log1p(x), wk), np.add.reduceat(np.log1p(y), wk)
    slope = float(np.cov(x, y)[0, 1] / y.var(ddof=1))
    daily, weekly = float(np.corrcoef(x, y)[0, 1]), float(np.corrcoef(wx, wy)[0, 1])
    vol = float(x.std(ddof=1) / y.std(ddof=1))
    return f"daily {daily:4.2f}  7-day {weekly:4.2f}  slope {slope:4.2f}  vol ratio {vol:4.2f}"


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
    """Print how often two hourly books agree (index 0 is 00:00 UTC of the first day)."""

    def cell(p: str | None, q: str | None) -> str:
        if p == q:
            return "same side" if p else "both flat"
        return "opposite sides" if p and q else f"only {na} in" if p else f"only {nb} in"

    n, days = len(a), len(a) // 24
    # Reason: a 4h account's stops are journaled at the 4h close, so in/out is compared
    # only at 4h closes; opposite sides cannot come from that lag and are counted hourly.
    same = [a[i] == b[i] for i in range(0, n, 4)]
    opp = [any(p and q and p != q for p, q in zip(a[i], b[i], strict=True)) for i in range(n)]
    same_days = sum(all(same[i : i + 6]) for i in range(0, len(same), 6))
    opp_days = sum(any(opp[i : i + 24]) for i in range(0, n, 24))
    kinds = Counter(cell(a[i][k], b[i][k]) for i in range(0, n, 4) for k in range(3))
    per = ", ".join(f"{k} {100 * v / (3 * len(same)):.1f}%" for k, v in kinds.most_common())
    print(
        f"  {na} vs {nb}: identical books at {100 * sum(same) / len(same):.1f}% of 4h closes and "
        f"at all six closes on {100 * same_days / days:.1f}% of UTC days; opposite sides in some "
        f"coin at {sum(opp[0::4])} of {len(same)} 4h closes, in {100 * sum(opp) / n:.1f}% of all "
        f"hours, at some hour on {100 * opp_days / days:.1f}% of days"
    )
    print(f"    coin by coin at 4h closes: {per}")


def day(t: datetime) -> date:
    """UTC day of an event; a bar closing at 00:00 counts for the day that just ended."""
    return (t - SEC).date()


def stats3(v: list[float], unit: str) -> str:
    """Mean, median and share above zero of a list."""
    pos = 100 * sum(1 for x in v if x > 0) / max(len(v), 1)
    return f"mean {np.mean(v):+.2f}{unit}, median {np.median(v):+.2f}{unit}, above zero {pos:.0f}%"


def stop_study(dg: list[Trade], mn: list[Trade], feed: lib.Feed, w: str) -> None:
    """What main did, and what the price did, each time degen's opening stop fired."""
    main_end: Counter[str] = Counter()
    gap: dict[str, list[float]] = {"both": [], "only": [], "absent": []}
    held_r, main_r, days_on = [], [], []
    stops = [t for t in dg if t.end == "stop"]
    for d in stops:
        sgn = 1 if d.side == "long" else -1
        r_px = abs(d.entry - d.exit)  # degen's 1R in price
        mine = [t for t in mn if t.market == d.market and t.side == d.side]
        m = next((t for t in mine if t.opened < d.closed <= t.closed), None)
        if any(t.end == "stop" and day(t.closed) == day(d.closed) for t in mine):
            kind = "both"
        elif m is not None:
            kind = "only"
            main_end["a later opening stop" if m.end == "stop" else m.end] += 1
            held_r.append(sgn * (m.exit - d.entry) / r_px)
            main_r.append(m.r)
            days_on.append((m.closed - d.closed) / timedelta(days=1))
        else:
            kind = "absent"
        # Reason: after a stop the coin may reopen at the next 00:00 UTC; the open of that
        # bar against the stop price is what being out until then cost (+) or saved (-).
        midnight = (d.closed - SEC).replace(hour=0, minute=0, second=0) + timedelta(days=1)
        gap[kind].append(sgn * (float(feed.rows[d.market][midnight][1]) - d.exit) / r_px)
    n = len(stops)
    print(
        f"  degen opening stops (before any take-profit): {n} = {n / months(w):.1f} a month, of "
        f"{len(dg) / months(w):.1f} entries a month. On the same coin and side:"
    )
    text = {
        "both": "main's opening stop fired that UTC day too",
        "only": "main was in the trade and was NOT stopped that day (a degen-only stop)",
        "absent": "main was not in that trade at that moment and was not stopped that day",
    }
    for k, line in text.items():
        print(f"    {len(gap[k]):4d} ({100 * len(gap[k]) / n:4.1f}%)  {line}")
    ends = ", ".join(f"{k} {v}" for k, v in main_end.most_common())
    print(
        f"  after a degen-only stop main's trade ended by: {ends}; median "
        f"{np.median(days_on):.1f} days later"
    )
    print(
        "    the degen trade held to main's final exit instead (no ladder, before costs), in "
        f"degen's R, against the -1R taken: {stats3(held_r, 'R')}"
    )
    print(f"    main's own whole trade, from main's entry, in main's R: {stats3(main_r, 'R')}")
    print(
        "  price at the next 00:00 UTC (degen's earliest re-entry) against the stop price, in "
        "degen's R; plus = the price came back and the stop cost that much, minus = it saved it:"
    )
    for k, label in (("only", "degen-only"), ("both", "both stopped"), ("absent", "main absent")):
        print(f"    {label:15}: {stats3(gap[k], 'R')}")
    print(f"    {'all degen stops':15}: {stats3([x for v in gap.values() for x in v], 'R')}")
    hit = {(d.market, d.side, day(d.closed)) for d in stops}
    rev = [t for t in mn if t.end == "stop"]
    alone = sum((t.market, t.side, day(t.closed)) not in hit for t in rev)
    print(
        f"  the other way round: main had {len(rev)} opening stops; degen's did not fire on that "
        f"coin and side that day in {alone} ({100 * alone / len(rev):.0f}%)"
    )


def main() -> None:
    """Print the Q2, Q3 and Q4 tables."""
    data, cache = Path(sys.argv[1]), Path(sys.argv[2])
    feeds = {tf: lib.build_feed(data, tf, cache) for tf in ("1h", "4h")}
    f1, f4 = feeds["1h"], feeds["4h"]
    degen, main_p, spot = (lib.account(n)[0] for n in ("degen", "main", "spot-perps"))
    differ = {
        k: f"{v} vs {getattr(main_p, k)}"
        for k, v in dataclasses.asdict(degen).items()
        if v != getattr(main_p, k) and k != "version"
    }
    hdr = f"{lib.HEADER} | {lib.HEADER}"
    print("EXP-2026-023 degen slice (paper replay, research only). Left block development")
    print("2020-10..2023-12, right block holdout 2024-01..2026-11-21; each run starts fresh at")
    print("$2,500. Columns as in run_exp023.py; 'stop%' counts every entry closed by a stop, the")
    print("opening stop or one a take-profit had moved. 1R = 30% of a position's collateral.")
    print(f"Settings that differ between degen and main (degen vs main): {differ}")

    # ---- Q2: all eight combinations of collateral, buffer and feed ---------------------
    cube: dict[tuple[int, int, str], Runs] = {}
    for coll in (5, 10):
        for buf in (3, 4):
            p = dataclasses.replace(degen, **{COLL: D(coll), BUF: D(buf)})
            for tf in ("1h", "4h"):
                cube[coll, buf, tf] = both(p, feeds[tf])
    live_degen, degen_4h, live_main = cube[5, 3, "1h"], cube[5, 3, "4h"], cube[10, 4, "4h"]
    held_sig = held_between_4h(f1)
    held = both(degen, f1, signals=held_sig)
    plain = {
        tf: both(degen, feeds[tf], signals=feeds[tf].signals("plain-50-200", lib.plain_50_200))
        for tf in ("1h", "4h")
    }
    tag = {"5 3 1h": " = live degen", "10 4 4h": " = live main", "10 4 1h": " = main on 1h"}
    rows = [
        (f"coll {c:2d}%, buffer {b}, {tf}{tag.get(f'{c} {b} {tf}', '')}", r)
        for (c, b, tf), r in cube.items()
    ]
    rows.append(("diag: degen, 1h marks, signal held to 4h", held))
    rows += [(f"diag: degen, plain 50/200 signal, {tf}", r) for tf, r in plain.items()]
    print("\n== Q2. Does hourly execution earn its keep?")
    print(f"{'setting':42} | {hdr}")
    for label, r in rows:
        print(f"{label:42} | " + " | ".join(lib.cell(r[w].stats) for w in WIN))
    print("\nSharpe gap with a 90% interval (paired block bootstrap of daily returns), dev | hold:")
    gaps = [
        (f"1h minus 4h, coll {c:2d}%, buffer {b}", cube[c, b, "1h"], cube[c, b, "4h"])
        for c in (5, 10)
        for b in (3, 4)
    ]
    gaps += [
        ("hourly marks alone: diag held minus degen on 4h", held, degen_4h),
        ("hourly decisions alone: live degen minus diag held", live_degen, held),
        ("1h minus 4h, degen with the plain 50/200 signal", plain["1h"], plain["4h"]),
        ("buffer 4 minus buffer 3 (coll 5%, 4h)", cube[5, 4, "4h"], degen_4h),
        ("coll 10% minus coll 5% (buffer 4, 4h)", live_main, cube[5, 4, "4h"]),
    ]
    for label, a, b in gaps:
        print(f"  {label:50}: {sharpe_gap(a, b)}")
    print("\nAverage effect of each difference over the other two, dev / hold (Sharpe; then")
    print("points of return per year, max drawdown, entries a month, fees per year):")
    names = ("1h feed instead of 4h", "buffer 4 instead of 3", "collateral 10% instead of 5%")
    for name, axis, hi, lo in zip(names, (2, 1, 0), ("1h", 4, 10), ("4h", 3, 5), strict=True):
        parts = []
        for key in ("sharpe", "cagr", "dd", "trades_mo", "fee_drag"):
            fmt, vals = "+.2f" if key == "sharpe" else "+.1f", []
            for w in WIN:
                up = [r[w].stats[key] for k, r in cube.items() if k[axis] == hi]
                down = [r[w].stats[key] for k, r in cube.items() if k[axis] == lo]
                vals.append(format(sum(up) / 4 - sum(down) / 4, fmt))
            parts.append(f"{key} {vals[0]} / {vals[1]}")
        print(f"  {name:28}: " + "   ".join(parts))
    print(
        "\nHow the entries ended: entries a month; share opened off the 4h grid; share closed by "
        "a signal\nchange / the opening stop / a stop after a take-profit / TP3; mean net result "
        "per entry in R;\nR a month; mean leverage; median hours held."
    )
    print(f"{'setting':42} | {MECH} | {MECH}")
    for label, r in rows:
        print(f"{label:42} | {mechanics(r)}")
    how = {"1h": "every hour (4h candles + latest hourly close)", "4h": "on 4h closes"}
    for tf, text in how.items():
        n = " / ".join(f"{signal_changes(feeds[tf], w):.1f}" for w in WIN)
        print(f"Signal changes a month over the three coins, read {text}: {n} (dev / hold)")
    for w in WIN:
        ts = trades(live_degen[w].events)
        quick = [t.r for t in ts if t.end == "signal" and t.closed - t.opened < H4]
        print(
            f"Live degen, {w}: entries closed by a signal change within 4 hours of opening: "
            f"{len(quick) / months(w):.1f} a month, mean {np.mean(quick):+.3f}R, "
            f"{sum(quick) / months(w):+.2f}R a month"
        )
    by_year: dict[int, float] = defaultdict(float)
    for w in WIN:
        x, y = day_rets(live_degen[w]), day_rets(degen_4h[w])
        for d in x:
            by_year[d.year] += math.log1p(x[d]) - math.log1p(y[d])
    years = ", ".join(f"{y} {v:+.2f}" for y, v in sorted(by_year.items()))
    print(f"Log return per calendar year, degen's settings on 1h minus on 4h: {years}")

    # ---- Q3: live degen against live main on the holdout -------------------------------
    spot_runs = both(spot, f4)
    print("\n== Q3. How different is degen from main? (live settings)")
    print("Correlation of daily returns and of 7-day returns; slope and volatility ratio of the")
    print("first account against the second:")
    pairs = (
        ("live degen (1h) vs live main (4h)", live_degen, live_main),
        ("live degen (1h) vs live spot-perps (4h)", live_degen, spot_runs),
        ("live main (4h) vs live spot-perps (4h)", live_main, spot_runs),
        ("degen settings on 4h vs live main (4h)", degen_4h, live_main),
        ("live degen (1h) vs degen settings on 4h", live_degen, degen_4h),
        ("diag: degen, plain 50/200, 1h vs live main", plain["1h"], live_main),
    )
    for label, a, b in pairs:
        print(f"  {label:42} hold: {corr(a['hold'], b['hold'])}   dev: {corr(a['dev'], b['dev'])}")
    start, end = lib.WINDOWS["hold"]
    grid = [start + k * H1 for k in range(int((end - start) / H1))]
    live = {"degen": live_degen, "main": live_main, "spot-perps": spot_runs}
    tr = {n: trades(r["hold"].events) for n, r in live.items()}
    check = [sum(t.pnl for t in tr[n]) - (live[n]["hold"].stats["end"] - 2500) for n in tr]
    print(f"  (check: trade P&L rebuilt from events minus equity change, $: {np.round(check, 2)})")
    print("Books on the holdout (the side each account holds in SOL, ETH, BTC):")
    bk = {n: books(t, grid) for n, t in tr.items()}
    for na, nb in (("degen", "main"), ("degen", "spot-perps"), ("main", "spot-perps")):
        overlap(bk[na], bk[nb], na, nb)
    print("When degen's opening stop fired (holdout):")
    stop_study(tr["degen"], tr["main"], f1, "hold")

    # ---- Q4: the pre-set list, ranked on development only ------------------------------
    def on_4h_close(acct: Any, market: str, side: Any, j: int) -> bool:
        return (f1.times[j] + H1).hour % 4 == 0

    variants = {
        "(a) degen as is": degen,
        "(b) buffer 6": dataclasses.replace(degen, **{BUF: D(6)}),
        "(b) buffer 8": dataclasses.replace(degen, **{BUF: D(8)}),
        "(c) entries on 4h closes only": degen,
        "(d) collateral 10%, buffer 8": dataclasses.replace(degen, **{COLL: D(10), BUF: D(8)}),
    }
    cands = {k: both(p, f1) for k, p in variants.items() if k[:3] in ("(b)", "(d)")}
    cands["(a) degen as is"] = live_degen
    cands["(c) entries on 4h closes only"] = both(degen, f1, gate=on_4h_close)
    ranked = sorted(cands, key=lambda k: -cands[k]["dev"].stats["sharpe"])
    print("\n== Q4. The pre-set list on 1h bars, ranked on development Sharpe only")
    titles = {"dev": "DEVELOPMENT (decides the rank)", "hold": "HOLDOUT (after ranking)"}
    for w, title in titles.items():
        print(f"{title}\n{'rank, variant':33} | {lib.HEADER} | against live main (4h)")
        for i, k in enumerate(ranked, 1):
            r = cands[k][w]
            print(f"{i}. {k:30} | {lib.cell(r.stats)} | {corr(r, live_main[w])}")
    print("Sharpe minus (a) with a 90% interval, dev | hold:")
    for k in ranked:
        if k != "(a) degen as is":
            print(f"  {k:30}: {sharpe_gap(cands[k], live_degen)}")
    print(f"\n{'variant':33} | {MECH} | {MECH}")
    for k in ranked:
        print(f"{k:33} | {mechanics(cands[k])}")
    print(f"{'live main (4h), for reference':33} | {mechanics(live_main)}")
    print("\nReference, NOT ranked and not in the pre-set list: the same settings with the signal")
    print("held between 4h closes (stops and take-profits still checked every hour):")
    print(f"{'variant':33} | {hdr}")
    for k, p in variants.items():
        if k[:3] != "(c)":
            runs = held if k[:3] == "(a)" else both(p, f1, signals=held_sig)
            print(f"{k:33} | " + " | ".join(lib.cell(runs[w].stats) for w in WIN))
            print(f"{'  Sharpe minus hourly decisions':33} : {sharpe_gap(runs, cands[k])}")


if __name__ == "__main__":
    main()
