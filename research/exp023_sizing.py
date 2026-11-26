"""EXP-2026-023 sizing slice: how position size trades return for drawdown (research only).

Replays the real paper engine (``exp023_lib``) on 4h candles for the ``main`` and
``spot-perps`` paper accounts. Simulated money only; nothing here places an order.

Grids, written here before this slice ran a single holdout replay:

* main: ``max_collateral_per_position_pct`` {2, 3, 5, 7.5, 10} x
  ``liquidation_buffer_daily_moves`` {4, 6, 8, 12} x ``group_cap`` {none, 6, 3} (same-side
  open risk, % of equity). The stop stays at 30% of collateral and the 4R/8R/12R ladder
  stays. A cap that cannot bind (cap >= 3 x collateral x stop%) is skipped: 40 settings.
* spot-perps: collateral {5, 7.5, 10, 15} x stop {6, 10}% of collateral x ``group_cap``
  {none, 1.5}, same skip rule: 13 settings. No ladder, 1x, as deployed.

Rules, also fixed beforehand:

1. "Under a bar" means max drawdown below it in BOTH windows. Passing settings are listed
   largest average gross exposure (development) first: the first row is the least risk
   reduction, the first row without a cap the least reduction by size alone.
2. Each capped setting is paired with uncapped twins (same buffer or stop, less collateral):
   one with the same average gross exposure and one with the same max drawdown, both solved
   on development only.
3. Robustness compares live, buffer=8, and the main setting with the highest development
   return per year among those with development max drawdown under 15% (holdout unused).

Added after the first full run, to explain what the cap does (no grid or rule changed): a
third twin, "equal split" (collateral = cap / (3 x stop%): the cap's risk budget shared by
three coins), and the entry-size table at the end of question 2.

Windows: development 2020-10-01..2023-12-31, holdout 2024-01-01..2026-11-21; every run
starts fresh at $2,500. "expo" is the average over UTC day ends of open position size as %
of equity (development/holdout). Max drawdown is the harness's (equity at every 4h bar);
question 3 also shows it from day-end equity; calendar year 2026 ends on 2026-11-21.
Slippage and price impact are not modelled and equity is never marked inside a bar, so
every drawdown printed here is a floor for what live trading can show, not an estimate.

Usage: python research/exp023_sizing.py <data_dir> <cache_dir>
"""

from __future__ import annotations

import dataclasses
import math
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as lib

D = Decimal
MAIN_COLLATERAL = ("2", "3", "5", "7.5", "10")
MAIN_BUFFER = ("4", "6", "8", "12")
MAIN_CAPS = (None, D(6), D(3))
MAIN_STOP = D(30)
SPOT_COLLATERAL = ("5", "7.5", "10", "15")
SPOT_STOP = ("6", "10")
SPOT_CAPS = (None, D("1.5"))
BARS = (15.0, 20.0, 30.0)  # max drawdown bars, %; the owner's go-live bar is the first
GO_LIVE_DD = 15.0
DEV, HOLD = lib.WINDOWS["dev"], lib.WINDOWS["hold"]
DATA_END = datetime(2026, 11, 22, tzinfo=UTC)
START_USD = 2500.0
SECOND = timedelta(seconds=1)
MOVERS = ("OPENED", "TAKE_PROFIT", "CLOSED", "LIQUIDATED")
ROLLING_STARTS = 62  # first of every month, 2020-10 .. 2025-11
QUARTER_STARTS = 24  # 2020-10 .. 2026-07
FULL_SIZE = 0.8  # an entry with at least this share of the configured collateral is "full"


@dataclass(frozen=True)
class Setting:
    """One sizing choice for one account."""

    account: str
    collateral: Decimal
    stop: Decimal
    buffer: Decimal | None = None
    cap: Decimal | None = None

    @property
    def label(self) -> str:
        """Short name used in the tables."""
        mid = f"stop={self.stop}" if self.buffer is None else f"b={self.buffer}"
        return f"c={self.collateral} {mid} cap={'-' if self.cap is None else self.cap}"


@dataclass(frozen=True)
class Run:
    """What the tables need from one replay."""

    stats: dict[str, float]
    daily: dict[date, float]
    expo: float  # average gross exposure, % of equity
    hundredth: date | None  # UTC day of the 100th entry


@dataclass(frozen=True)
class Row:
    """One setting over both windows."""

    s: Setting
    dev: Run
    hold: Run


def _day(e: dict[str, Any]) -> date:
    """UTC day an event belongs to (the harness's rule: 00:00 closes the day before)."""
    return (datetime.fromisoformat(e["at_utc"]) - SECOND).date()


def _exposure(res: lib.Result) -> tuple[float, date | None]:
    """Average day-end open size as % of equity, and the day of the 100th entry."""
    moves = [e for e in res.events if e["event"] in MOVERS]
    size: dict[str, float] = {}
    shares: list[float] = []
    opened, hundredth, i = 0, None, 0
    for day, equity in sorted(res.daily_equity.items()):
        while i < len(moves) and _day(moves[i]) <= day:
            e = moves[i]
            i += 1
            if e["event"] == "OPENED":
                size[e["market"]] = float(e["size_usd"])
                opened += 1
                if opened == 100:
                    hundredth = day
            elif e["event"] == "TAKE_PROFIT":
                size[e["market"]] = float(e["remaining_size_usd"])
            else:
                size.pop(e["market"], None)
        shares.append(sum(size.values()) / equity * 100 if equity > 0 else 0.0)
    return statistics.fmean(shares), hundredth


class Lab:
    """The 4h feed, the live settings and a memo of finished replays."""

    def __init__(self, data: Path, cache: Path) -> None:
        self.feed = lib.build_feed(data, "4h", cache)
        self.base = {name: lib.account(name)[0] for name in ("main", "spot-perps")}
        self.memo: dict[tuple[Setting, datetime, datetime], Run] = {}

    def replay(self, s: Setting, start: datetime, end: datetime) -> lib.Result:
        """Replay one setting over ``[start, end)`` from a fresh $2,500 account."""
        changed: dict[str, Any] = {"max_collateral_per_position_pct": s.collateral}
        changed["stop_loss_pct_of_collateral"] = s.stop
        if s.buffer is not None:
            changed["liquidation_buffer_daily_moves"] = s.buffer
        params = dataclasses.replace(self.base[s.account], **changed)
        return lib.run(params, self.feed, start, end, group_cap=s.cap)

    def run(self, s: Setting, start: datetime, end: datetime) -> Run:
        """The memoised summary of one replay."""
        key = (s, start, end)
        if key not in self.memo:
            res = self.replay(s, start, end)
            self.memo[key] = Run(res.stats, res.daily_equity, *_exposure(res))
        return self.memo[key]

    def row(self, s: Setting) -> Row:
        """Both windows of one setting."""
        return Row(s, self.run(s, *DEV), self.run(s, *HOLD))


def grid(account: str) -> list[Setting]:
    """The pre-set grid of one account, without the caps that cannot bind."""
    main = account == "main"
    out = [
        Setting(account, D(c), MAIN_STOP if main else D(x), D(x) if main else None, cap)
        for x in (MAIN_BUFFER if main else SPOT_STOP)
        for c in (MAIN_COLLATERAL if main else SPOT_COLLATERAL)
        for cap in (MAIN_CAPS if main else SPOT_CAPS)
    ]
    # Reason: three full positions risk 3 x collateral x stop%; a cap at or above never binds.
    return [s for s in out if s.cap is None or s.cap < 3 * s.collateral * s.stop / 100]


def _cell(r: Run) -> str:
    """CAGR, Sharpe, max drawdown, worst day, CAGR / max drawdown."""
    s = r.stats
    return (
        f"{s['cagr']:7.1f}% {s['sharpe']:5.2f} {s['dd']:5.1f}% {s['worst_day']:6.1f}% "
        f"{s['cagr'] / s['dd']:5.2f}"
    )


CELL_HEAD = f"{'CAGR':>8} {'Shrp':>5} {'maxDD':>6} {'wDay':>7} {'C/DD':>5}"
LINE_HEAD = (
    f"{'setting':24} | {'expo d/h':>8} {'tr/mo':>5} {'stop%':>5} {'fee/y':>5} | "
    f"{CELL_HEAD} | {CELL_HEAD}"
)


def _line(label: str, r: Row) -> str:
    d = r.dev.stats
    return (
        f"{label:24} | {r.dev.expo:3.0f}/{r.hold.expo:3.0f}% {d['trades_mo']:5.1f} "
        f"{d['stop_share']:4.0f}% {d['fee_drag']:4.0f}% | {_cell(r.dev)} | {_cell(r.hold)}"
    )


def frontier(lab: Lab, title: str, account: str, live: Setting) -> list[Row]:
    """Print one account's grid and which settings stay under each drawdown bar."""
    print(f"\n== Question 1: {title}")
    print("left block development, right block holdout; tr/mo, stop%, fee/y: development")
    print(LINE_HEAD)
    rows = [lab.row(s) for s in grid(account)]
    for r in rows:
        print(_line(r.s.label + (" LIVE" if r.s == live else ""), r), flush=True)
    for bar in BARS:
        ok = [r for r in rows if max(r.dev.stats["dd"], r.hold.stats["dd"]) < bar]
        print(f"\nmax drawdown under {bar:.0f}% in both windows: {len(ok)} of {len(rows)} settings")
        for r in sorted(ok, key=lambda r: -r.dev.expo):
            print("  " + _line(r.s.label, r))
    ratio = [r.hold.stats["dd"] / r.dev.stats["dd"] for r in rows]
    print(
        f"\nholdout max drawdown / development max drawdown: min {min(ratio):.2f}, "
        f"median {statistics.median(ratio):.2f}, max {max(ratio):.2f}; "
        f"holdout was deeper in {sum(1 for x in ratio if x > 1)} of {len(rows)} settings"
    )
    return rows


def _log_ratio(r: Run) -> float:
    """Log growth per year over log max drawdown: the size-free version of CAGR / DD."""
    return math.log1p(r.stats["cagr"] / 100) / -math.log1p(-r.stats["dd"] / 100)


PIVOTS: tuple[tuple[str, Callable[[Run], float], str], ...] = (
    ("return per year, %", lambda r: r.stats["cagr"], ".0f"),
    ("max drawdown, %", lambda r: r.stats["dd"], ".0f"),
    ("return per year / max drawdown", lambda r: r.stats["cagr"] / r.stats["dd"], ".2f"),
    ("log growth / log drawdown (size-free)", _log_ratio, ".2f"),
    ("Sharpe", lambda r: r.stats["sharpe"], ".2f"),
)


def pivots(rows: list[Row]) -> None:
    """Uncapped main settings as buffer x collateral tables, development / holdout."""
    plain = {(r.s.buffer, r.s.collateral): r for r in rows if r.s.cap is None}
    print("\n-- main without a cap: development / holdout, rows buffer, columns collateral %")
    for name, fn, fmt in PIVOTS:
        print(f"{name}")
        print(f"{'':10}" + "".join(f"{'c=' + c:>14}" for c in MAIN_COLLATERAL))
        for b in MAIN_BUFFER:
            cells = []
            for c in MAIN_COLLATERAL:
                r = plain[(D(b), D(c))]
                cells.append(f"{fn(r.dev):{fmt}}/{fn(r.hold):{fmt}}")
            print(f"{'buffer=' + b:10}" + "".join(f"{x:>14}" for x in cells))


def matched(lab: Lab, k: Setting) -> dict[str, Setting]:
    """Uncapped twins of ``k``: same exposure, same drawdown (development), equal split."""
    plain = dataclasses.replace(k, cap=None)
    target = lab.run(k, *DEV)
    c = k.collateral
    for _ in range(3):
        got = lab.run(dataclasses.replace(plain, collateral=c), *DEV).expo
        c = (c * D(str(target.expo / got))).quantize(D("0.01"))
    # Reason: drawdown rises with collateral, so bisect on it (to 0.01% of equity).
    lo, hi = D("0.2"), k.collateral
    for _ in range(10):
        mid = ((lo + hi) / 2).quantize(D("0.01"))
        twin = dataclasses.replace(plain, collateral=mid)
        if lab.run(twin, *DEV).stats["dd"] < target.stats["dd"]:
            lo = mid
        else:
            hi = mid
    assert k.cap is not None
    split = (k.cap / (3 * k.stop / 100)).quantize(D("0.01"))
    return {
        "same expo": dataclasses.replace(plain, collateral=c),
        "same dev DD": dataclasses.replace(plain, collateral=hi),
        "equal split": dataclasses.replace(plain, collateral=split),
    }


def cap_versus_smaller(lab: Lab, rows: list[Row]) -> None:
    """Question 2: every capped setting against its uncapped twins."""
    capped = [r for r in rows if r.s.cap is not None]
    wins: dict[tuple[str, str], list[int]] = {}
    print(LINE_HEAD)
    for r in capped:
        print(_line(r.s.label, r))
        for kind, twin in matched(lab, r.s).items():
            t = lab.row(twin)
            print(_line(f"  {kind}: c={twin.collateral}", t), flush=True)
            for w in ("dev", "hold"):
                a, b = getattr(r, w).stats, getattr(t, w).stats
                better = (
                    a["cagr"] > b["cagr"],
                    a["sharpe"] > b["sharpe"],
                    a["dd"] < b["dd"],
                    a["cagr"] / a["dd"] > b["cagr"] / b["dd"],
                )
                old = wins.get((kind, w), [0, 0, 0, 0])
                wins[(kind, w)] = [x + int(y) for x, y in zip(old, better, strict=True)]
    print(f"in how many of {len(capped)} pairs the cap beat the uncapped twin:")
    for (kind, w), v in wins.items():
        print(
            f"  {kind:12} {'development' if w == 'dev' else 'holdout':12} higher return {v[0]:2d}, "
            f"higher Sharpe {v[1]:2d}, smaller drawdown {v[2]:2d}, higher return/drawdown {v[3]:2d}"
        )


def cap_sizes(lab: Lab, k: Setting) -> None:
    """Which entries a setting bets most on: full-size against cut-down entries."""
    for name, window in (("development", DEV), ("holdout", HOLD)):
        res = lab.replay(k, *window)
        live: dict[str, list[float]] = {}  # market -> [full size?, collateral, P&L so far]
        done: dict[bool, list[float]] = {True: [], False: []}  # P&L, % of collateral
        for e in res.events:
            m = str(e.get("market"))
            if e["event"] == "OPENED":
                usd = float(e["collateral_usd"])
                share = usd / res.daily_equity[_day(e)] * 100 / float(k.collateral)
                live[m] = [float(share >= FULL_SIZE), usd, -float(e["fee_usd"])]
            elif e["event"] in ("TAKE_PROFIT", "CLOSED"):
                live[m][2] += float(e["pnl_usd"]) - float(e["fees_usd"])
                if e["event"] == "CLOSED":
                    full, usd, pnl = live.pop(m)
                    done[bool(full)].append(pnl / usd * 100)
        n = len(done[True]) + len(done[False])
        text = f"{k.label:17} {name:12} {n:5d} entries, {len(done[True]) / n:4.0%} at full size"
        for label, xs in (("full-size", done[True]), ("cut-down", done[False])):
            if xs:
                text += f"; {label} mean P&L {statistics.fmean(xs):+5.1f}% of collateral"
        print(text, flush=True)


def _month(year: int, month: int, add: int = 0) -> datetime:
    """First day of a month, ``add`` months later."""
    k = year * 12 + month - 1 + add
    return datetime(k // 12, k % 12 + 1, 1, tzinfo=UTC)


def _path(daily: dict[date, float], until: date | None = None) -> tuple[float, float, float]:
    """Return %, max drawdown % and Sharpe from day-end equity, optionally cut at a day."""
    eq = [v for d, v in sorted(daily.items()) if until is None or d <= until]
    peak, dd = START_USD, 0.0
    for v in eq:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak * 100)
    rets = [b / a - 1 for a, b in zip([START_USD, *eq], eq, strict=False)]
    sd = statistics.stdev(rets) if len(rets) > 1 else 0.0
    sharpe = statistics.fmean(rets) / sd * math.sqrt(365) if sd > 0 else 0.0
    return (eq[-1] / START_USD - 1) * 100, dd, sharpe


def _share(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)} ({sum(flags) / len(flags) * 100:.0f}%)"


def _dist(
    who: str, what: str, xs: list[float], tag: str = "", hit: list[bool] | None = None
) -> None:
    """Print min, 10th percentile, median, 90th percentile, max, and a share if given."""
    q = statistics.quantiles(xs, n=10, method="inclusive")
    five = " ".join(f"{x:7.1f}" for x in (min(xs), q[0], statistics.median(xs), q[8], max(xs)))
    tail = "" if hit is None else f" | {tag} {_share(hit)}"
    print(f"{who:14} {what:21} {five}{tail}", flush=True)


SPREAD_HEAD = f"{'':36} {'min':>7} {'p10':>7} {'median':>7} {'p90':>7} {'max':>7}"
Picks = list[tuple[str, Setting]]
Test = tuple[float, float, float, float, datetime]  # days, return %, max DD %, Sharpe, start


def by_year(lab: Lab, picks: Picks) -> None:
    """Question 3a: one fresh run per calendar year."""
    print("\n(a) calendar years, a fresh $2,500 each: return %, max DD % day-end (4h bars)")
    print(f"{'year':5} | " + " | ".join(f"{name:^26}" for name, _ in picks))
    for y in range(2021, 2027):
        cells = []
        for _, s in picks:
            run = lab.run(s, _month(y, 1), min(_month(y + 1, 1), DATA_END))
            ret, dd, _ = _path(run.daily)
            cells.append(f"{ret:+9.1f}%  dd {dd:4.1f}% ({run.stats['dd']:4.1f})")
        print(f"{y:<5} | " + " | ".join(cells), flush=True)


def rolling(lab: Lab, picks: Picks) -> None:
    """Question 3b: 12-month windows starting on the first of every month."""
    starts = [_month(2020, 10, i) for i in range(ROLLING_STARTS)]
    print(f"\n(b) {len(starts)} rolling 12-month windows, starts 2020-10 .. 2025-11, each fresh")
    print(SPREAD_HEAD)
    for name, s in picks:
        runs = [lab.run(s, t, _month(t.year, t.month, 12)) for t in starts]
        paths = [_path(r.daily) for r in runs]
        rets = [p[0] for p in paths]
        day_dd = [p[1] for p in paths]
        bar_dd = [r.stats["dd"] for r in runs]
        _dist(name, "12-month return %", rets, "lost money", [x < 0 for x in rets])
        _dist("", "max DD %, day-end", day_dd, "over 15%", [x > GO_LIVE_DD for x in day_dd])
        _dist("", "max DD %, 4h bars", bar_dd, "over 15%", [x > GO_LIVE_DD for x in bar_dd])


def first_hundred(lab: Lab, picks: Picks) -> None:
    """Question 3c: what the first 100 entries of a fresh account show."""
    quarters = [_month(2020, 10, 3 * i) for i in range(QUARTER_STARTS)]
    print("\n(c) a fresh account every quarter, cut at the end of the UTC day of the 100th entry:")
    print("    days needed, return %, max drawdown % (day-end equity), '+' = Sharpe above 0")
    print(f"{'start':8} | " + " | ".join(f"{name:^27}" for name, _ in picks))
    found: dict[str, list[Test]] = {n: [] for n, _ in picks}
    for q in quarters:
        cells = []
        for name, s in picks:
            run = lab.run(s, q, min(_month(q.year, q.month, 12), DATA_END))
            if run.hundredth is None:
                cells.append(f"{'fewer than 100 entries':27}")
                continue
            ret, dd, sharpe = _path(run.daily, run.hundredth)
            days = (run.hundredth - q.date()).days + 1
            found[name].append((float(days), ret, dd, sharpe, q))
            cells.append(f"{days:4d}d {ret:+8.1f}% dd {dd:5.1f}% {'+' if sharpe > 0 else '-'}")
        print(f"{q:%Y-%m}  | " + " | ".join(cells), flush=True)
    print("\n" + SPREAD_HEAD)
    for name, s in picks:
        got = found[name]
        rets = [g[1] for g in got]
        dds = [g[2] for g in got]
        passed = [g[2] < GO_LIVE_DD and g[3] > 0 for g in got]
        _dist(name, "days to 100 entries", [g[0] for g in got])
        _dist("", "return % at the cut", rets, "lost money", [x < 0 for x in rets])
        _dist("", "max DD % at the cut", dds, "over 15%", [x > GO_LIVE_DD for x in dds])
        print(f"{'':14} met the bar (DD under 15% and Sharpe above 0): {_share(passed)}")
        _what_follows(lab, s, got, passed)


def _what_follows(lab: Lab, s: Setting, got: list[Test], passed: list[bool]) -> None:
    """Compare each 100-entry test with the 12 months that start the month after it ends."""
    pairs: list[tuple[float, float, float, bool]] = []
    for (days, ret, _, _, q), ok in zip(got, passed, strict=True):
        cut = q + timedelta(days=days)
        nxt = _month(cut.year, cut.month, 0 if cut.day == 1 else 1)
        if nxt > _month(2020, 10, ROLLING_STARTS - 1):
            continue
        after = lab.run(s, nxt, _month(nxt.year, nxt.month, 12))
        pairs.append((ret, _path(after.daily)[0], after.stats["dd"], ok))
    both = zip(*((p[0], p[1]) for p in pairs), strict=True)
    ranks = [[float(sorted(v).index(x)) for x in v] for v in both]
    print(
        f"{'':14} the 12 months after the test ({len(pairs)} tests have a full year after "
        f"them): rank correlation of test return with next-year return "
        f"{statistics.correlation(*ranks):+.2f}"
    )
    for label, want in (("met", True), ("missed", False)):
        group = [p for p in pairs if p[3] is want]
        if group:
            print(
                f"{'':14}   tests that {label} the bar: next year lost money in "
                f"{_share([p[1] < 0 for p in group])}, had max DD over 15% (4h bars) in "
                f"{_share([p[2] > GO_LIVE_DD for p in group])}, median return "
                f"{statistics.median(p[1] for p in group):+.1f}%"
            )


def main() -> None:
    """Run the three questions and print the tables."""
    lab = Lab(Path(sys.argv[1]), Path(sys.argv[2]))
    print("EXP-2026-023 sizing slice (paper only). Grids and rules: see the module docstring.")
    print("Backtest numbers; not a forecast. Live drawdowns are normally deeper than these.")
    live = Setting("main", D(10), MAIN_STOP, D(4))
    rows = frontier(lab, "main, 30% stop, ladder kept", "main", live)
    pivots(rows)
    spot_live = Setting("spot-perps", D(15), D(6))
    spot_rows = frontier(lab, "spot-perps, 1x, no ladder", "spot-perps", spot_live)
    print("\n== Question 2: a same-side cap against simply posting less collateral")
    print("each capped setting, then its uncapped twins (see the module docstring)")
    print("-- main")
    cap_versus_smaller(lab, rows)
    print("-- spot-perps")
    cap_versus_smaller(lab, spot_rows)
    print("-- what the cap does to entry size (main, collateral 10, buffer 4)")
    for cap in MAIN_CAPS:
        cap_sizes(lab, dataclasses.replace(live, cap=cap))
    under = [r for r in rows if r.dev.stats["dd"] < GO_LIVE_DD]
    best = max(under, key=lambda r: r.dev.stats["cagr"]).s
    wide = dataclasses.replace(live, buffer=D(8))
    picks: Picks = [("live", live), ("buffer=8", wide), ("under-15 pick", best)]
    print("\n== Question 3: robustness of live and two candidates")
    print(f"under-15 pick (highest development return with development DD under 15%): {best.label}")
    print(LINE_HEAD)
    for name, s in picks:
        print(_line(name, lab.row(s)))
    by_year(lab, picks)
    rolling(lab, picks)
    first_hundred(lab, picks)


if __name__ == "__main__":
    main()
