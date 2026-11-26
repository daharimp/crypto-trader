"""EXP-2026-023, signal slice: is the live signal's churn (and its cost) the problem?

Research only, paper only: a replay of the real paper engine (``exp023_lib``) on stored 4h
candles, 2020-2026. Nothing here places orders or touches a network.

Usage: python research/exp023_signal.py <data_dir> <cache_dir>

PRE-SET GRID. Written before any holdout number of these variants was looked at; nothing was
added, dropped or re-tuned after results. Every threshold was given in the task, none fitted.

  live   trend_50_200_range_10_30 as deployed: 50/200 averages, 10/30 while the 30-day
         efficiency ratio (ER) is below 0.05.
  a1/a2  hysteresis on the range switch: range mode starts at ER < 0.05 and ends only at
         ER > 0.08 (a1) or ER > 0.12 (a2).
  b1/b2  confirmation: a new direction of the live signal counts only once it has shown on
         2 (b1) or 3 (b2) consecutive 4h bars.
  c1/c2  minimum hold: after a change of direction the signal may not change again for 6 (c1)
         or 12 (c2) bars. Stops and take-profits are untouched.
  d      range mode goes flat (no position while ER < 0.05) instead of trading 10/30.
  e      plain 50/200, no range switch.

Each runs on main at the live liquidation buffer (4), on main at buffer 8, and on spot-perps.

PRE-SET SELECTION RULE. Variants are ranked on development only (2020-10..2023-12) by Sharpe
averaged over the three settings. The top one is "the pick"; it is called better than live
only if it also beats live on development in all three settings. Holdout (2024-01..2026-11-21)
is printed next to it and never used to choose. Sharpe differences come with a paired block
bootstrap interval (20-day blocks, 2000 draws), because small differences are noise.

PRE-SET COST GRID. Live and the two top-ranked variants at 0x, 1x, 2x and 3x costs (open fee,
close fee and borrow scaled together); 4x to 8x are run only to find where growth turns
negative. Funding is not modelled; the note printed with that table says what that means.

Added after the first run, description only (they select nothing): how often the ER < 0.05
flag itself changes, the regime x exit table, and the borrow-only rows for the live signal.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import sys
from collections import namedtuple
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import exp023_lib as lib
import numpy as np

from trader.perps.backtest import sma_stance
from trader.perps.math import PerpSide
from trader.perps.params import PerpsParams
from trader.regimes import trend as tr

D = Decimal
Factory = Callable[[], lib.SignalFn]
Signals = dict[str, list[PerpSide | None]]
Flags = dict[str, list[bool]]
ENTER = tr.RANGE_EFFICIENCY_BELOW
LABEL = "signal-churn1"  # cache prefix; bump the number whenever a variant's logic changes
WINDOWS = ("dev", "hold")
YEARS = {w: (b - a).days / 365.25 for w, (a, b) in lib.WINDOWS.items()}
COST_MULTS, COST_EXTRA = (0, 1, 2, 3), (4, 5, 6, 8)
BORROW_ONLY = (D(3), D("6.25"))  # 6.25x = 0.01%/h, the cautious rate the config used before
SETTINGS: tuple[tuple[str, str, dict[str, Decimal]], ...] = (
    ("main buffer 4 (live)", "main", {}),
    ("main buffer 8", "main", {"liquidation_buffer_daily_moves": D(8)}),
    ("spot-perps (1x)", "spot-perps", {}),
)


@dataclass
class Hysteresis:
    """Range mode starts at ER < 0.05 and ends only at ER > ``exit_above``."""

    exit_above: Decimal
    ranging: bool = False

    def __call__(self, closes: list[Decimal]) -> PerpSide | None:
        er = tr.efficiency_ratio(closes)
        if er is None:
            self.ranging = False  # Reason: the live rule counts "not measurable" as trending.
        elif er < ENTER:
            self.ranging = True
        elif er > self.exit_above:
            self.ranging = False
        if len(closes) < tr.SLOW:
            return None
        if self.ranging:
            return sma_stance(closes, tr.RANGE_FAST, tr.RANGE_SLOW)
        return sma_stance(closes, tr.FAST, tr.SLOW)


@dataclass
class Confirm:
    """The live signal's new direction counts once it has shown ``bars`` bars in a row."""

    bars: int
    raw: lib.SignalFn = field(default_factory=lib.live_signal)
    last: PerpSide | None = None
    out: PerpSide | None = None
    streak: int = 0

    def __call__(self, closes: list[Decimal]) -> PerpSide | None:
        now = self.raw(closes)
        self.streak = self.streak + 1 if now == self.last else 1
        self.last = now
        if now != self.out and self.streak >= self.bars:
            self.out = now
        return self.out


@dataclass
class MinHold:
    """After a change of direction the signal may not change again for ``bars`` bars."""

    bars: int
    raw: lib.SignalFn = field(default_factory=lib.live_signal)
    out: PerpSide | None = None
    since: int = 10**6

    def __call__(self, closes: list[Decimal]) -> PerpSide | None:
        now = self.raw(closes)
        self.since += 1
        if now != self.out and self.since >= self.bars:
            self.out, self.since = now, 0
        return self.out


def range_flat(closes: list[Decimal]) -> PerpSide | None:
    """No position while ranging (ER < 0.05); the 50/200 averages otherwise."""
    if len(closes) < tr.SLOW or tr.is_ranging(closes):
        return None
    return sma_stance(closes, tr.FAST, tr.SLOW)


# THE GRID (see the module docstring). name: (cache key, factory called once per coin)
GRID: dict[str, tuple[str, Factory]] = {
    "a1 hysteresis exit>0.08": ("a1", lambda: Hysteresis(D("0.08"))),
    "a2 hysteresis exit>0.12": ("a2", lambda: Hysteresis(D("0.12"))),
    "b1 confirm 2 bars": ("b1", lambda: Confirm(2)),
    "b2 confirm 3 bars": ("b2", lambda: Confirm(3)),
    "c1 min hold 6 bars": ("c1", lambda: MinHold(6)),
    "c2 min hold 12 bars": ("c2", lambda: MinHold(12)),
    "d range -> flat": ("d", lambda: range_flat),
    "e plain 50/200": ("e", lib.plain_50_200),
}
# One exit of (part of) a trade; ``cost`` includes its share of the opening fee.
Leg = namedtuple("Leg", "label gross cost size hours")


@dataclass
class Trade:
    """One position from its open to its last exit, rebuilt from the account's events."""

    market: str
    side: str
    opened: datetime
    equity: float  # account equity when it opened (collateral / collateral share)
    size: float
    ranging: bool  # trend.is_ranging on the bar that decided the entry
    left: float
    collateral: float
    open_fee: float
    borrow: float = 0.0
    legs: list[Leg] = field(default_factory=list)
    gross: float = 0.0  # the three below are filled in when the trade ends
    cost: float = 0.0
    hours: float = 0.0


Key = Callable[[Trade], str] | None
EXITS = {"SIGNAL_CHANGED": "signal flip", "TAKE_PROFIT_3": "TP3 (rest)", "END_OF_REPLAY": "end"}
REGIME = {False: "trending (50/200)", True: "ranging (10/30 decides)"}


def trades_of(res: lib.Result, params: PerpsParams, ranging: Flags, index: dict) -> list[Trade]:
    """Rebuild trades from ``Result.events`` (OPENED, TAKE_PROFIT, CLOSED, LIQUIDATED)."""
    share = float(params.max_collateral_per_position_pct) / 100
    fee = float(params.close_fee_bps) / 1e4
    live: dict[str, Trade] = {}
    done: list[Trade] = []
    for e in res.events:
        kind = e["event"]
        if kind not in ("OPENED", "TAKE_PROFIT", "CLOSED", "LIQUIDATED"):
            continue
        m, at = e["market"], datetime.fromisoformat(e["at_utc"])
        if kind == "OPENED":
            size, coll = float(e["size_usd"]), float(e["collateral_usd"])
            # Reason: the fill is at the open of the bar after the one that decided it.
            decided = ranging[m][index[at - lib.STEP["4h"]]]
            live[m] = Trade(
                m, e["side"], at, coll / share, size, decided, size, coll, float(e["fee_usd"])
            )
            continue
        t = live[m]
        closed = float(e["closed_size_usd"]) if kind == "TAKE_PROFIT" else t.left
        coll = t.collateral * closed / t.left
        if kind == "LIQUIDATED":
            label, gross, fees = "liquidated", -float(e["collateral_lost_usd"]), 0.0
        else:
            fees = float(e["fees_usd"])
            # Reason: the account never pays back less than zero, so a loss ends at the
            # collateral even when the journaled pnl is larger.
            gross = max(float(e["pnl_usd"]), fees - coll)
            t.borrow += fees - round(closed * fee, 2)
            if kind == "TAKE_PROFIT":
                label = f"TP{e['step']} (25%)"
            elif e["reason"] == "STOP_LOSS":
                label = "stop after a TP" if t.legs else "stop (opening)"
            else:
                label = EXITS[e["reason"]]
        hours = (at - t.opened).total_seconds() / 3600
        t.legs.append(Leg(label, gross, fees + t.open_fee * closed / t.size, closed, hours))
        t.left -= closed
        t.collateral -= coll
        if kind != "TAKE_PROFIT":
            t.gross, t.cost, t.hours = sum(x[1] for x in t.legs), sum(x[2] for x in t.legs), hours
            done.append(live.pop(m))
    return done


BH = f"{'n':>5} {'win':>4} {'gross':>6} {'cost':>6} {'net':>6} {'g/tr':>5} {'c/tr':>5}"
Item = tuple[float, float, float, float]  # gross $, cost $, notional $, equity at entry $


def bcell(items: list[Item], years: float) -> str:
    """Count, win share, gross/cost/net in % of equity a year, gross and cost in bps of size."""
    if not items:
        return f"{'-':>5}" + " " * (len(BH) - 5)
    gross = sum(g / eq for g, _, _, eq in items)
    cost = sum(c / eq for _, c, _, eq in items)
    size = sum(s / eq for _, _, s, eq in items)
    win = sum(1 for g, c, _, _ in items if g > c) / len(items) * 100
    k = 100 / years
    return (
        f"{len(items):5d} {win:3.0f}% {gross * k:6.1f} {cost * k:6.1f} {(gross - cost) * k:6.1f} "
        f"{gross / size * 1e4:5.0f} {cost / size * 1e4:5.0f}"
    )


def span(hours: float, limits: tuple[tuple[float, str], ...], rest: str) -> str:
    """Holding-time bucket."""
    return next((name for limit, name in limits if hours <= limit), rest)


def regime_exit(t: Trade) -> str:
    """Regime at entry crossed with how the trade ended (and how fast, for signal flips)."""
    regime, last = "range" if t.ranging else "trend", t.legs[-1].label
    if last == "signal flip":
        return f"{regime}: flip out {span(t.hours, ((24, '<=24h'), (72, '1-3d')), '>3d')}"
    return f"{regime}: {last if last == 'stop (opening)' else 'ladder exit / end'}"


def breakdown(title: str, trades: dict[str, list[Trade]], key: Key) -> None:
    """One table: rows are buckets, columns development | holdout. ``key`` None = per exit."""
    rows: dict[str, dict[str, list[Item]]] = {}
    for w in WINDOWS:
        for t in trades[w]:
            if key is None:
                pairs = [(x.label, (x.gross, x.cost, x.size, t.equity)) for x in t.legs]
            else:
                pairs = [(key(t), (t.gross, t.cost, t.size, t.equity))]
            for k, item in pairs:
                rows.setdefault(k, {w: [] for w in WINDOWS})[w].append(item)
    print(f"{title:28} | {BH} | {BH}")
    for k in sorted(rows, key=lambda k: (ORDER.index(k) if k in ORDER else 99, k)):
        by = rows[k]
        print(f"  {k:26} | {bcell(by['dev'], YEARS['dev'])} | {bcell(by['hold'], YEARS['hold'])}")


HOLD = ((8, "<=8h"), (24, "8-24h"), (72, "1-3d"), (168, "3-7d"))
ORDER = ["signal flip", "stop (opening)", "stop after a TP", "TP1 (25%)", "TP2 (25%)", "TP3 (rest)"]
ORDER += [*REGIME.values(), "long", "short", "BTC", "ETH", "SOL", *(n for _, n in HOLD), ">7d"]
ENDS = ("flip out <=24h", "flip out 1-3d", "flip out >3d", "stop (opening)", "ladder exit / end")
ORDER += [f"{r}: {x}" for r in ("range", "trend") for x in ENDS]
TABLES: tuple[tuple[str, Key], ...] = (
    ("total", lambda t: "all trades"),
    ("by exit (per exit fill)", None),
    ("by regime at entry", lambda t: REGIME[t.ranging]),
    ("by side", lambda t: t.side),
    ("by coin", lambda t: t.market),
    ("by holding time", lambda t: span(t.hours, HOLD, ">7d")),
    ("regime x how it ended", regime_exit),
)


def money_report(
    name: str, start_cash: float, res: dict[str, lib.Result], trades: dict[str, list[Trade]]
) -> None:
    """Section 1 for one account: where the net P&L of the live setting comes from."""
    print(f"\n== 1. Where the money comes from: {name}, live signal")
    for w in WINDOWS:
        ts, y = trades[w], YEARS[w]
        net = sum(t.gross - t.cost for t in ts)
        booked = res[w].stats["end"] - start_cash
        borrow = sum(t.borrow / t.equity for t in ts) * 100 / y
        cost = sum(t.cost / t.equity for t in ts) * 100 / y
        hours = y * 365.25 * 24
        expo = {
            s: sum(x.size / t.equity * x.hours for t in ts if t.side == s for x in t.legs) / hours
            for s in ("long", "short")
        }
        print(
            f"{w:4}: {len(ts)} trades, net ${net:,.0f} (account ${booked:,.0f}, gap "
            f"${net - booked:,.2f}); costs {cost:.0f}%/y of equity = fees {cost - borrow:.0f} + "
            f"borrow {borrow:.0f}; average open size {expo['long']:.2f}x equity long, "
            f"{expo['short']:.2f}x short"
        )
    for title, key in TABLES:
        breakdown(title, trades, key)


def churn(sig: Signals, ranging: Flags, times: list[datetime], w: str) -> str:
    """Signal changes per coin per month; share on ranging bars; share on a bar where the
    ER < 0.05 flag itself changed; share of time flat."""
    j0, j1 = (bisect.bisect_left(times, t) for t in lib.WINDOWS[w])
    flips = in_range = at_switch = flat = 0
    for m in lib.COINS:
        s, r = sig[m], ranging[m]
        for j in range(j0, j1):
            flat += s[j] is None
            if j > 0 and s[j] != s[j - 1]:
                flips += 1
                in_range += r[j]
                at_switch += r[j] != r[j - 1]
    per_month = flips / len(lib.COINS) / (YEARS[w] * 12)
    return (
        f"{per_month:6.1f} {in_range / max(flips, 1) * 100:5.0f}% "
        f"{at_switch / max(flips, 1) * 100:5.0f}% {flat / (len(lib.COINS) * (j1 - j0)) * 100:5.0f}%"
    )


def daily_returns(res: lib.Result, start_cash: float) -> np.ndarray:
    """Daily returns, the same series ``exp023_lib.summarize`` takes its Sharpe from."""
    eq = [v for _, v in sorted(res.daily_equity.items())]
    return np.array([b / a - 1 for a, b in zip([start_cash, *eq], eq, strict=False)])


def boot(a: np.ndarray, b: np.ndarray | None = None, block: int = 20, draws: int = 2000) -> str:
    """Sharpe of ``a`` (minus Sharpe of ``b``) with a 90% circular block-bootstrap interval."""
    rng = np.random.default_rng(23)
    n = len(a)
    starts = rng.integers(0, n, size=(draws, math.ceil(n / block)))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(draws, -1)[:, :n]

    def sharpe(x: np.ndarray) -> np.ndarray:
        return x.mean(axis=-1) / x.std(axis=-1, ddof=1) * math.sqrt(365)

    point, dist = sharpe(a), sharpe(a[idx])
    if b is not None:
        # Reason: both series are resampled on the same days, so shared market noise cancels.
        point, dist = point - sharpe(b), dist - sharpe(b[idx])
    lo, hi = np.percentile(dist, [5, 95])
    return f"{point:+5.2f} [{lo:+5.2f},{hi:+5.2f}]"


def with_costs(p: PerpsParams, fees: Decimal | int, borrow: Decimal | int) -> PerpsParams:
    """The account with both trading fees multiplied by ``fees`` and borrow by ``borrow``."""
    scaled = {"open_fee_bps": p.open_fee_bps * fees, "close_fee_bps": p.close_fee_bps * fees}
    return dataclasses.replace(
        p, **scaled, borrow_rate_pct_per_hour=p.borrow_rate_pct_per_hour * borrow
    )


def breakeven(points: list[tuple[int, float]]) -> str:
    """Cost multiple where growth per year crosses zero (straight line between two runs)."""
    for (k0, c0), (k1, c1) in zip(points, points[1:], strict=False):
        if c0 > 0 >= c1:
            return f"about {k0 + (k1 - k0) * c0 / (c0 - c1):.1f}x"
    return f"above {points[-1][0]}x" if points[-1][1] > 0 else f"at or below {points[0][0]}x"


def cost_table(feed: lib.Feed, sname: str, p: PerpsParams, picks: dict[str, Signals]) -> None:
    """Section 3 for one setting: the same replays with every cost multiplied."""

    def stats(q: PerpsParams, sig: Signals, w: str) -> dict[str, float]:
        return lib.run(q, feed, *lib.WINDOWS[w], signals=sig).stats

    print(f"\n-- {sname}\n{'signal @ cost multiple':32} | {lib.HEADER} | {lib.HEADER}")
    for vname, sig in picks.items():
        cagr: dict[str, list[tuple[int, float]]] = {w: [] for w in WINDOWS}
        for k in COST_MULTS:
            row = {w: stats(with_costs(p, k, k), sig, w) for w in WINDOWS}
            for w in WINDOWS:
                cagr[w].append((k, row[w]["cagr"]))
            print(f"{vname[:26]:26} @ {k}x  | {lib.cell(row['dev'])} | {lib.cell(row['hold'])}")
        for w in WINDOWS:
            for k in COST_EXTRA:
                if cagr[w][-1][1] <= 0:
                    break
                cagr[w].append((k, stats(with_costs(p, k, k), sig, w)["cagr"]))
        tail = "; ".join(
            f"{w} {breakeven(cagr[w])}"
            + "".join(f", {k}x {c:+.0f}%" for k, c in cagr[w][len(COST_MULTS) :])
            for w in WINDOWS
        )
        print(f"{'':6}growth per year turns negative: {tail}", flush=True)
    for k in BORROW_ONLY if sname.startswith("main") else ():
        row = {w: stats(with_costs(p, 1, k), picks["live"], w) for w in WINDOWS}
        label = f"live, borrow only @ {k}x"
        print(f"{label:32} | {lib.cell(row['dev'])} | {lib.cell(row['hold'])}", flush=True)


def main() -> None:
    """Print the three sections."""
    data, cache = Path(sys.argv[1]), Path(sys.argv[2])
    feed = lib.build_feed(data, "4h", cache)
    sigs: dict[str, Signals] = {"live": feed.signals()}
    for name, (key, factory) in GRID.items():
        sigs[name] = feed.signals(f"{LABEL}-{key}", factory)
    # Reason: hysteresis that leaves at the entry threshold is the live rule, so it must match
    # the harness's live signal bar for bar; this guards the re-implemented pieces above.
    assert feed.signals(f"{LABEL}-selfcheck", lambda: Hysteresis(ENTER)) == sigs["live"]
    ranging = {m: [tr.is_ranging(c) for c, _ in feed.views(m)] for m in lib.COINS}
    index = {t: j for j, t in enumerate(feed.times)}

    params: dict[str, PerpsParams] = {}
    runs: dict[tuple[str, str, str], lib.Result] = {}
    for sname, account, changed in SETTINGS:
        params[sname] = dataclasses.replace(lib.account(account)[0], **changed)
        for vname, sig in sigs.items():
            for w in WINDOWS:
                runs[sname, vname, w] = lib.run(params[sname], feed, *lib.WINDOWS[w], signals=sig)
    names = [s[0] for s in SETTINGS]
    cash = {s: float(params[s].starting_collateral_usd) for s in names}

    print("EXP-2026-023 signal slice. Paper-only replay; development 2020-10..2023-12 (left),")
    print("holdout 2024-01..2026-11-21 (right). Costs 7 bps a side + borrow 0.0016%/h; no funding.")
    print(
        "Section 1: n = trades (exit fills in 'by exit'), win = share with net > 0, gross / cost /"
    )
    print("net = summed P&L as % of the account's equity at entry, per year (not compounded), g/tr")
    print("and c/tr = gross P&L and cost per trade in bps of position size (cost = fees + borrow).")
    for sname in (names[0], names[2]):
        res = {w: runs[sname, "live", w] for w in WINDOWS}
        trades = {w: trades_of(res[w], params[sname], ranging, index) for w in WINDOWS}
        money_report(sname, cash[sname], res, trades)

    print("\n== 2. Churn-reducing variants (grid and selection rule fixed in the docstring)")
    head = f"{'flips':>6} {'range':>6} {'at sw':>6} {'flat':>6}"
    print("\nThe signal alone: changes per coin per month, share of them on ranging bars, share")
    print("of them on a bar where the ER < 0.05 flag itself changed, share of time flat.")
    print(f"{'variant':26} | {head} | {head}")
    for vname, sig in {"(ER < 0.05 flag itself)": ranging, **sigs}.items():
        cells = [churn(sig, ranging, feed.times, w) for w in WINDOWS]
        print(f"{vname:26} | {cells[0]} | {cells[1]}")
    for sname in names:
        print(f"\n-- {sname}\n{'variant':26} | {lib.HEADER} | {lib.HEADER}")
        for vname in sigs:
            cells = [lib.cell(runs[sname, vname, w].stats) for w in WINDOWS]
            print(f"{vname:26} | {cells[0]} | {cells[1]}")

    sharpe = {(v, w): [runs[s, v, w].stats["sharpe"] for s in names] for v in sigs for w in WINDOWS}
    ranked = sorted(sigs, key=lambda v: -sum(sharpe[v, "dev"]))
    print("\nRanking on development only (Sharpe: buffer 4, buffer 8, spot-perps, mean);")
    print("holdout shown next to it, not used. 'all 3' = beats live on development everywhere.")
    print(f"{'variant':26} | {'development Sharpe':>25} | {'holdout Sharpe':>25} | all 3")
    for v in ranked:
        cells = [
            " ".join(f"{x:5.2f}" for x in sharpe[v, w]) + f"  {sum(sharpe[v, w]) / 3:5.2f}"
            for w in WINDOWS
        ]
        wins = all(a > b for a, b in zip(sharpe[v, "dev"], sharpe["live", "dev"], strict=True))
        mark = "-" if v == "live" else "yes" if wins else "no"
        print(f"{v:26} | {cells[0]} | {cells[1]} | {mark}")
    print(f"Pick on development alone: {ranked[0]}" + (" (no change)" * (ranked[0] == "live")))

    rets = {k: daily_returns(r, cash[k[0]]) for k, r in runs.items()}
    print("\nSharpe minus live's Sharpe, with a 90% paired block-bootstrap interval (an interval")
    print("that spans zero means the difference cannot be told from noise).")
    print(
        f"{'variant':26} | "
        + " | ".join(f"{s.split(' (')[0] + ' ' + w:>19}" for s in names for w in WINDOWS)
    )
    for v in sigs:
        own = v == "live"  # live's row shows its own Sharpe, the others the difference to it
        cells = [
            boot(rets[s, v, w], None if own else rets[s, "live", w]) for s in names for w in WINDOWS
        ]
        print(f"{'live (its own Sharpe)' if own else v:26} | " + " | ".join(cells), flush=True)

    print("\n== 3. Cost sensitivity (open fee, close fee and borrow all multiplied; 1x = live)")
    print("Higher fees also move the fee-inclusive stop and the assessed leverage slightly.")
    picks = {v: sigs[v] for v in ["live", *[v for v in ranked if v != "live"][:2]]}
    for sname in names:
        cost_table(feed, sname, params[sname], picks)
    print("\nFunding: the replay charges a flat borrow of 0.0016%/h (about 14% of position size a")
    print("year) on both sides and no funding. The real borrow rate moves with pool utilization; a")
    print("funding venue would add a charge that a trend follower usually pays. Each extra 10% a")
    print("year on position size costs about 10% x the average open size (section 1) of equity.")


if __name__ == "__main__":
    main()
