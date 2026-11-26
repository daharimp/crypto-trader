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

1. "Under a bar" means max drawdown below it in BOTH windows. The least risk reduction is
   the passing setting with the largest average gross exposure in development.
2. Each capped setting is paired with two uncapped ones (same buffer or stop, smaller
   collateral): one with the same average gross exposure in development, one with the same
   development max drawdown. The collateral of both is solved on development only.
3. Robustness compares live, buffer=8, and the main setting with the highest development
   return per year among those with development max drawdown under 15% (holdout unused).

Windows: development 2020-10-01..2023-12-31, holdout 2024-01-01..2026-11-21; every run
starts fresh at $2,500. "expo" is the average over UTC day ends of open position size as %
of equity. Max drawdown in the grid tables is the harness's (equity at every 4h bar);
question 3 also shows it from day-end equity. Costs: 7 bps a side and the configured borrow
rate; funding, slippage and price impact are not modelled, so every drawdown printed here is
a floor for what live trading can show, not an estimate of it.

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
MAIN_CAPS = (None, "6", "3")
MAIN_STOP = D(30)
SPOT_COLLATERAL = ("5", "7.5", "10", "15")
SPOT_STOP = ("6", "10")
SPOT_CAPS = (None, "1.5")
BARS = (15.0, 20.0, 30.0)  # max drawdown bars, %; the owner's go-live bar is the first
GO_LIVE_DD = 15.0
DEV, HOLD = lib.WINDOWS["dev"], lib.WINDOWS["hold"]
DATA_END = datetime(2026, 11, 22, tzinfo=UTC)
START_USD = 2500.0
SECOND = timedelta(seconds=1)
MOVERS = ("OPENED", "TAKE_PROFIT", "CLOSED", "LIQUIDATED")
ROLLING_STARTS = 62  # first of every month, 2020-10 .. 2025-11
QUARTER_STARTS = 24  # 2020-10 .. 2026-07


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

    def cap_can_bind(self) -> bool:
        """Whether three full positions on one side would pass the cap."""
        return self.cap is None or self.cap < 3 * self.collateral * self.stop / 100


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

    def worst_dd(self) -> float:
        """The larger of the two windows' max drawdowns, %."""
        return max(self.dev.stats["dd"], self.hold.stats["dd"])


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

    def run(self, s: Setting, start: datetime, end: datetime) -> Run:
        """Replay one setting over ``[start, end)`` from a fresh $2,500 account."""
        key = (s, start, end)
        if key not in self.memo:
            changed: dict[str, Any] = {
                "max_collateral_per_position_pct": s.collateral,
                "stop_loss_pct_of_collateral": s.stop,
            }
            if s.buffer is not None:
                changed["liquidation_buffer_daily_moves"] = s.buffer
            params = dataclasses.replace(self.base[s.account], **changed)
            res = lib.run(params, self.feed, start, end, group_cap=s.cap)
            self.memo[key] = Run(res.stats, res.daily_equity, *_exposure(res))
        return self.memo[key]

    def row(self, s: Setting) -> Row:
        """Both windows of one setting."""
        return Row(s, self.run(s, *DEV), self.run(s, *HOLD))


def main_grid() -> list[Setting]:
    """The pre-set main grid."""
    out = [
        Setting("main", D(c), MAIN_STOP, D(b), None if cap is None else D(cap))
        for b in MAIN_BUFFER
        for c in MAIN_COLLATERAL
        for cap in MAIN_CAPS
    ]
    return [s for s in out if s.cap_can_bind()]


def spot_grid() -> list[Setting]:
    """The pre-set spot-perps grid."""
    out = [
        Setting("spot-perps", D(c), D(stop), None, None if cap is None else D(cap))
        for stop in SPOT_STOP
        for c in SPOT_COLLATERAL
        for cap in SPOT_CAPS
    ]
    return [s for s in out if s.cap_can_bind()]


def _cell(r: Run) -> str:
    """CAGR, Sharpe, max drawdown, worst day, CAGR / max drawdown."""
    s = r.stats
    return (
        f"{s['cagr']:7.1f}% {s['sharpe']:5.2f} {s['dd']:5.1f}% {s['worst_day']:6.1f}% "
        f"{s['cagr'] / s['dd']:5.2f}"
    )


CELL_HEAD = f"{'CAGR':>8} {'Shrp':>5} {'maxDD':>6} {'wDay':>7} {'C/DD':>5}"


def _line(label: str, r: Row) -> str:
    d = r.dev.stats
    return (
        f"{label:24} | {r.dev.expo:4.0f}% {d['trades_mo']:5.1f} {d['stop_share']:4.0f}% "
        f"{d['fee_drag']:4.0f}% | {_cell(r.dev)} | {_cell(r.hold)}"
    )


LINE_HEAD = (
    f"{'setting':24} | {'expo':>5} {'tr/mo':>5} {'stop%':>5} {'fee/y':>5} | {CELL_HEAD} | {CELL_HEAD}"
)


def frontier(lab: Lab, title: str, grid: list[Setting], live: Setting) -> list[Row]:
    """Print one account's grid and which settings stay under each drawdown bar."""
    print(f"\n== Question 1: {title}")
    print("left block development, right block holdout; expo, tr/mo, stop%, fee/y: development")
    print(LINE_HEAD)
    rows = [lab.row(s) for s in grid]
    for r in rows:
        print(_line(r.s.label + (" LIVE" if r.s == live else ""), r), flush=True)
    for bar in BARS:
        ok = sorted((r for r in rows if r.worst_dd() < bar), key=lambda r: -r.dev.expo)
        print(f"\nmax drawdown under {bar:.0f}% in both windows: {len(ok)} of {len(rows)} settings")
        if not ok:
            continue
        top = max(ok, key=lambda r: r.dev.stats["cagr"])
        print(f"  least risk reduction (largest exposure): {ok[0].s.label}")
        print(f"  highest development return among them:   {top.s.label}")
        for r in ok if bar == GO_LIVE_DD else ok[:5]:
            print("  " + _line(r.s.label, r))
    ratio = [r.hold.stats["dd"] / r.dev.stats["dd"] for r in rows]
    worse = sum(1 for x in ratio if x > 1)
    print(
        f"\nholdout max drawdown / development max drawdown: min {min(ratio):.2f}, "
        f"median {statistics.median(ratio):.2f}, max {max(ratio):.2f}; "
        f"holdout was deeper in {worse} of {len(rows)} settings"
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
    ("average gross exposure, % of equity", lambda r: r.expo, ".0f"),
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


def matched(lab: Lab, k: Setting) -> tuple[Setting, Setting]:
    """Uncapped twins of ``k``: same development exposure, and same development drawdown."""
    plain = dataclasses.replace(k, cap=None)
    target = lab.run(k, *DEV)
    c = k.collateral
    for _ in range(3):
        got = lab.run(dataclasses.replace(plain, collateral=c), *DEV).expo
        c = (c * D(str(target.expo / got))).quantize(D("0.01"))
    by_expo = dataclasses.replace(plain, collateral=c)
    # Reason: drawdown rises with collateral, so bisect on it (to 0.01% of equity).
    lo, hi = D("0.2"), k.collateral
    for _ in range(10):
        mid = ((lo + hi) / 2).quantize(D("0.01"))
        if lab.run(dataclasses.replace(plain, collateral=mid), *DEV).stats["dd"] < target.stats["dd"]:
            lo = mid
        else:
            hi = mid
    return by_expo, dataclasses.replace(plain, collateral=hi)


def cap_versus_smaller(lab: Lab, rows: list[Row]) -> None:
    """Question 2: every capped setting against its two uncapped twins."""
    capped = [r for r in rows if r.s.cap is not None]
    wins = {"expo": [0, 0, 0, 0], "dd": [0, 0, 0, 0]}
    gaps: dict[str, list[float]] = {"expo": [], "dd": []}
    print(LINE_HEAD)
    for r in capped:
        print(_line(r.s.label, r))
        for kind, twin in zip(("expo", "dd"), matched(lab, r.s), strict=True):
            t = lab.row(twin)
            print(_line(f"  same {kind}: c={twin.collateral}", t), flush=True)
            a, b = r.hold.stats, t.hold.stats
            better = (
                a["cagr"] > b["cagr"],
                a["sharpe"] > b["sharpe"],
                a["dd"] < b["dd"],
                a["cagr"] / a["dd"] > b["cagr"] / b["dd"],
            )
            wins[kind] = [w + int(x) for w, x in zip(wins[kind], better, strict=True)]
            gaps[kind].append(a["cagr"] / a["dd"] - b["cagr"] / b["dd"])
    n = len(capped)
    for kind, text in (("expo", "same exposure"), ("dd", "same development drawdown")):
        w = wins[kind]
        print(
            f"cap against uncapped at the {text}, HOLDOUT, {n} pairs: higher return {w[0]}, "
            f"higher Sharpe {w[1]}, smaller drawdown {w[2]}, higher return/drawdown {w[3]}; "
            f"median gap in return/drawdown {statistics.median(gaps[kind]):+.2f}"
        )


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


def _spread(xs: list[float]) -> str:
    """min, 10th percentile, median, 90th percentile, max."""
    q = statistics.quantiles(xs, n=10, method="inclusive")
    return (
        f"{min(xs):7.1f} {q[0]:7.1f} {statistics.median(xs):7.1f} {q[8]:7.1f} {max(xs):7.1f}"
    )


def _share(flags: list[bool]) -> str:
    return f"{sum(flags)}/{len(flags)} ({sum(flags) / len(flags) * 100:.0f}%)"


SPREAD_HEAD = f"{'min':>7} {'p10':>7} {'median':>7} {'p90':>7} {'max':>7}"
Picks = list[tuple[str, Setting]]


def by_year(lab: Lab, picks: Picks) -> None:
    """Question 3a: one fresh run per calendar year."""
    print("\n(a) calendar years, a fresh $2,500 each: return %, max drawdown % from day-end")
    print("    equity (and from 4h bars in brackets). 2026 ends on 2026-11-21.")
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
    print(f"{'':36} {SPREAD_HEAD}")
    for name, s in picks:
        runs = [lab.run(s, t, _month(t.year, t.month, 12)) for t in starts]
        paths = [_path(r.daily) for r in runs]
        rets = [p[0] for p in paths]
        day_dd = [p[1] for p in paths]
        bar_dd = [r.stats["dd"] for r in runs]
        print(f"{name:14} 12-month return %    {_spread(rets)} | lost money {_share([x < 0 for x in rets])}")
        print(
            f"{'':14} max DD %, day-end     {_spread(day_dd)} | over 15% "
            f"{_share([x > GO_LIVE_DD for x in day_dd])}"
        )
        print(
            f"{'':14} max DD %, 4h bars     {_spread(bar_dd)} | over 15% "
            f"{_share([x > GO_LIVE_DD for x in bar_dd])}",
            flush=True,
        )


def first_hundred(lab: Lab, picks: Picks) -> None:
    """Question 3c: what the first 100 entries of a fresh account show."""
    quarters = [_month(2020, 10, 3 * i) for i in range(QUARTER_STARTS)]
    print("\n(c) a fresh account every quarter, cut at the end of the UTC day of the 100th entry:")
    print("    days needed, return %, max drawdown % (day-end equity), '+' = Sharpe above 0")
    print(f"{'start':8} | " + " | ".join(f"{name:^27}" for name, _ in picks))
    found: dict[str, list[tuple[float, float, float, float, datetime]]] = {n: [] for n, _ in picks}
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
    print(f"\n{'':36} {SPREAD_HEAD}")
    for name, s in picks:
        got = found[name]
        rets = [g[1] for g in got]
        passed = [g[2] < GO_LIVE_DD and g[3] > 0 for g in got]
        print(f"{name:14} days to 100 entries   {_spread([g[0] for g in got])}")
        print(f"{'':14} return % at the cut   {_spread(rets)} | lost money {_share([x < 0 for x in rets])}")
        print(
            f"{'':14} max DD % at the cut   {_spread([g[2] for g in got])} | over 15% "
            f"{_share([g[2] > GO_LIVE_DD for g in got])}"
        )
        print(f"{'':14} met the bar (DD under 15% and Sharpe above 0): {_share(passed)}")
        _what_follows(lab, name, s, got, passed)


def _what_follows(
    lab: Lab,
    name: str,
    s: Setting,
    got: list[tuple[float, float, float, float, datetime]],
    passed: list[bool],
) -> None:
    """Compare each 100-entry test with the 12 months that start the month after it ends."""
    pairs: list[tuple[float, float, float, bool]] = []
    for (days, ret, _, _, q), ok in zip(got, passed, strict=True):
        cut = q + timedelta(days=days)
        nxt = _month(cut.year, cut.month, 0 if cut.day == 1 else 1)
        if nxt > _month(2020, 10, ROLLING_STARTS - 1):
            continue
        after = lab.run(s, nxt, _month(nxt.year, nxt.month, 12))
        pairs.append((ret, _path(after.daily)[0], after.stats["dd"], ok))
    rho = statistics.correlation([p[0] for p in pairs], [p[1] for p in pairs], method="ranked")
    met = [p for p in pairs if p[3]]
    missed = [p for p in pairs if not p[3]]
    print(
        f"{'':14} next 12 months ({len(pairs)} tests with a full year after them): rank "
        f"correlation of test return with next-year return {rho:+.2f}"
    )
    for label, group in (("met the bar", met), ("missed the bar", missed)):
        if group:
            print(
                f"{'':14}   tests that {label}: next year lost money in "
                f"{_share([p[1] < 0 for p in group])}, had max DD over 15% in "
                f"{_share([p[2] > GO_LIVE_DD for p in group])}, median return "
                f"{statistics.median(p[1] for p in group):+.1f}%"
            )


def main() -> None:
    """Run the three questions and print the tables."""
    lab = Lab(Path(sys.argv[1]), Path(sys.argv[2]))
    print("EXP-2026-023 sizing slice (paper only). Grids and rules: see the module docstring.")
    print("Backtest numbers; not a forecast. Live drawdowns are normally deeper than these.")
    live = Setting("main", D(10), MAIN_STOP, D(4))
    rows = frontier(lab, "main, 30% stop, ladder kept", main_grid(), live)
    pivots(rows)
    spot_live = Setting("spot-perps", D(15), D(6))
    spot_rows = frontier(lab, "spot-perps, 1x, no ladder", spot_grid(), spot_live)

    print("\n== Question 2: a same-side cap against simply posting less collateral")
    print("each capped setting, then the uncapped setting with the same average exposure and")
    print("the uncapped setting with the same development max drawdown (same buffer or stop)")
    print("-- main")
    cap_versus_smaller(lab, rows)
    print("-- spot-perps")
    cap_versus_smaller(lab, spot_rows)

    under = [r for r in rows if r.dev.stats["dd"] < GO_LIVE_DD]
    best = max(under, key=lambda r: r.dev.stats["cagr"]).s
    picks: Picks = [
        ("live", live),
        ("buffer=8", dataclasses.replace(live, buffer=D(8))),
        ("under-15 pick", best),
    ]
    print("\n== Question 3: robustness of live and two candidates")
    print(f"under-15 pick (highest development return with development DD under 15%): {best.label}")
    print(LINE_HEAD)
    for name, s in picks:
        print(_line(f"{name}: {s.label}", lab.row(s)))
    by_year(lab, picks)
    rolling(lab, picks)
    first_hundred(lab, picks)


if __name__ == "__main__":
    main()
