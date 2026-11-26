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
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import sys
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
ENTER = tr.RANGE_EFFICIENCY_BELOW
LABEL = "signal-churn1"  # cache prefix; bump the number whenever a variant's logic changes
WINDOWS = ("dev", "hold")
YEARS = {w: (b - a).days / 365.25 for w, (a, b) in lib.WINDOWS.items()}
COST_MULTS, COST_EXTRA = (0, 1, 2, 3), (4, 5, 6, 8)
SETTINGS: tuple[tuple[str, str, dict[str, Decimal]], ...] = (
    ("main buffer 4 (live)", "main", {}),
    ("main buffer 8", "main", {"liquidation_buffer_daily_moves": D(8)}),
    ("spot-perps (1x)", "spot-perps", {}),
)


def hysteresis(exit_above: Decimal) -> Factory:
    """Range mode starts at ER < 0.05 and ends only at ER > ``exit_above``."""

    def factory() -> lib.SignalFn:
        ranging = False

        def fn(closes: list[Decimal]) -> PerpSide | None:
            nonlocal ranging
            er = tr.efficiency_ratio(closes)
            if er is None:
                ranging = False  # Reason: the live rule counts "not measurable" as trending.
            elif er < ENTER:
                ranging = True
            elif er > exit_above:
                ranging = False
            if len(closes) < tr.SLOW:
                return None
            if ranging:
                return sma_stance(closes, tr.RANGE_FAST, tr.RANGE_SLOW)
            return sma_stance(closes, tr.FAST, tr.SLOW)

        return fn

    return factory


def confirm(bars: int) -> Factory:
    """The live signal's new direction counts once it has shown ``bars`` bars in a row."""

    def factory() -> lib.SignalFn:
        raw = lib.live_signal()
        last: PerpSide | None = None
        out: PerpSide | None = None
        streak = 0

        def fn(closes: list[Decimal]) -> PerpSide | None:
            nonlocal last, out, streak
            now = raw(closes)
            streak = streak + 1 if now == last else 1
            last = now
            if now != out and streak >= bars:
                out = now
            return out

        return fn

    return factory


def min_hold(bars: int) -> Factory:
    """After a change of direction the signal may not change again for ``bars`` bars."""

    def factory() -> lib.SignalFn:
        raw = lib.live_signal()
        out: PerpSide | None = None
        since = bars

        def fn(closes: list[Decimal]) -> PerpSide | None:
            nonlocal out, since
            now = raw(closes)
            since += 1
            if now != out and since >= bars:
                out, since = now, 0
            return out

        return fn

    return factory


def range_flat() -> lib.SignalFn:
    """No position while ranging (ER < 0.05); the 50/200 averages otherwise."""

    def fn(closes: list[Decimal]) -> PerpSide | None:
        if len(closes) < tr.SLOW or tr.is_ranging(closes):
            return None
        return sma_stance(closes, tr.FAST, tr.SLOW)

    return fn


# THE GRID (see the module docstring). name: (cache key, factory)
GRID: dict[str, tuple[str, Factory]] = {
    "a1 hysteresis exit>0.08": ("a1", hysteresis(D("0.08"))),
    "a2 hysteresis exit>0.12": ("a2", hysteresis(D("0.12"))),
    "b1 confirm 2 bars": ("b1", confirm(2)),
    "b2 confirm 3 bars": ("b2", confirm(3)),
    "c1 min hold 6 bars": ("c1", min_hold(6)),
    "c2 min hold 12 bars": ("c2", min_hold(12)),
    "d range -> flat": ("d", range_flat),
    "e plain 50/200": ("e", lib.plain_50_200),
}


@dataclass
class Leg:
    """One exit of (part of) a trade; ``cost`` includes its share of the opening fee."""

    label: str
    gross: float
    cost: float
    size: float
    hours: float


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

    @property
    def gross(self) -> float:
        return sum(x.gross for x in self.legs)

    @property
    def cost(self) -> float:
        return sum(x.cost for x in self.legs)

    @property
    def hours(self) -> float:
        return self.legs[-1].hours


EXITS = {"SIGNAL_CHANGED": "signal flip", "TAKE_PROFIT_3": "TP3 (rest)", "END_OF_REPLAY": "end"}


def trades_of(
    res: lib.Result, params: PerpsParams, ranging: dict[str, list[bool]], index: dict
) -> list[Trade]:
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


def hold_bucket(hours: float) -> str:
    """Holding-time bucket of a trade."""
    for limit, name in ((8, "<=8h"), (24, "8-24h"), (72, "1-3d"), (168, "3-7d")):
        if hours <= limit:
            return name
    return ">7d"


def regime_hold(t: Trade) -> str:
    """Regime at entry crossed with a coarse holding time."""
    span = "<=24h" if t.hours <= 24 else "1-3d" if t.hours <= 72 else ">3d"
    return f"{'range' if t.ranging else 'trend'} entry, held {span}"


def breakdown(
    title: str,
    trades: dict[str, list[Trade]],
    key: Callable[[Trade], str] | None,
    order: list[str],
) -> None:
    """One table: rows are buckets, columns development | holdout. ``key`` None = per exit."""
    rows: dict[str, dict[str, list[Item]]] = {k: {w: [] for w in WINDOWS} for k in order}
    for w in WINDOWS:
        for t in trades[w]:
            if key is None:
                pairs = [(x.label, (x.gross, x.cost, x.size, t.equity)) for x in t.legs]
            else:
                pairs = [(key(t), (t.gross, t.cost, t.size, t.equity))]
            for k, item in pairs:
                rows.setdefault(k, {w: [] for w in WINDOWS})[w].append(item)
    print(f"{title:28} | {BH} | {BH}")
    for k, by in rows.items():
        if by["dev"] or by["hold"]:
            print(f"  {k:26} | {bcell(by['dev'], YEARS['dev'])} | {bcell(by['hold'], YEARS['hold'])}")


def money_report(
    name: str, start_cash: float, res: dict[str, lib.Result], trades: dict[str, list[Trade]]
) -> None:
    """Section 1 for one account: where the net P&L of the live setting comes from."""
    print(f"\n== 1. Where the money comes from: {name}, live signal")
    print(
        "Columns per window (development | holdout): n = trades (exits in the first table), "
        "win = share with net > 0,\ngross / cost / net = summed P&L as % of the account's "
        "equity at entry, per year (not compounded),\ng/tr and c/tr = gross P&L and cost "
        "per trade in bps of position size (cost = fees both sides + borrow)."
    )
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
    everything = ["all trades"]
    breakdown("total", trades, lambda t: "all trades", everything)
    exits = ["signal flip", "stop (opening)", "stop after a TP", "TP1 (25%)", "TP2 (25%)"]
    breakdown("by exit (per exit fill)", trades, None, [*exits, "TP3 (rest)", "liquidated"])
    breakdown(
        "by regime at entry",
        trades,
        lambda t: "ranging (10/30 decides)" if t.ranging else "trending (50/200)",
        [],
    )
    breakdown("by side", trades, lambda t: t.side, ["long", "short"])
    breakdown("by coin", trades, lambda t: t.market, ["BTC", "ETH", "SOL"])
    breakdown(
        "by holding time",
        trades,
        lambda t: hold_bucket(t.hours),
        ["<=8h", "8-24h", "1-3d", "3-7d", ">7d"],
    )
    spans = ("<=24h", "1-3d", ">3d")
    breakdown(
        "regime x holding time",
        trades,
        regime_hold,
        [f"{r} entry, held {s}" for r in ("range", "trend") for s in spans],
    )


def churn(sig: Signals, ranging: dict[str, list[bool]], times: list[datetime], w: str) -> str:
    """Signal changes per coin per month, share of them on ranging bars, share of time flat."""
    j0, j1 = (bisect.bisect_left(times, t) for t in lib.WINDOWS[w])
    flips = in_range = flat = 0
    for m in lib.COINS:
        s = sig[m]
        for j in range(j0, j1):
            flat += s[j] is None
            if j > 0 and s[j] != s[j - 1]:
                flips += 1
                in_range += ranging[m][j]
    per_month = flips / len(lib.COINS) / (YEARS[w] * 12)
    return (
        f"{per_month:6.1f} {in_range / max(flips, 1) * 100:5.0f}% "
        f"{flat / (len(lib.COINS) * (j1 - j0)) * 100:5.0f}%"
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


def with_costs(p: PerpsParams, k: int) -> PerpsParams:
    """The account with open fee, close fee and borrow all multiplied by ``k``."""
    return dataclasses.replace(
        p,
        open_fee_bps=p.open_fee_bps * k,
        close_fee_bps=p.close_fee_bps * k,
        borrow_rate_pct_per_hour=p.borrow_rate_pct_per_hour * k,
    )


def breakeven(points: list[tuple[int, float]]) -> str:
    """Cost multiple where growth per year crosses zero (straight line between two runs)."""
    for (k0, c0), (k1, c1) in zip(points, points[1:], strict=False):
        if c0 > 0 >= c1:
            return f"{k0 + (k1 - k0) * c0 / (c0 - c1):.1f}x"
    return f">{points[-1][0]}x" if points[-1][1] > 0 else f"<={points[0][0]}x"


def cost_table(feed: lib.Feed, sname: str, p: PerpsParams, picks: dict[str, Signals]) -> None:
    """Section 3 for one setting: the same replays with every cost multiplied."""
    print(f"\n-- {sname}\n{'signal @ cost multiple':32} | {lib.HEADER} | {lib.HEADER}")
    for vname, sig in picks.items():
        cagr: dict[str, list[tuple[int, float]]] = {w: [] for w in WINDOWS}
        for k in COST_MULTS:
            stats = [lib.run(with_costs(p, k), feed, *lib.WINDOWS[w], signals=sig).stats for w in WINDOWS]
            for w, s in zip(WINDOWS, stats, strict=True):
                cagr[w].append((k, s["cagr"]))
            print(f"{vname[:26]:26} @ {k}x  | {lib.cell(stats[0])} | {lib.cell(stats[1])}", flush=True)
        for w in WINDOWS:
            for k in COST_EXTRA:
                if cagr[w][-1][1] <= 0:
                    break
                s = lib.run(with_costs(p, k), feed, *lib.WINDOWS[w], signals=sig).stats
                cagr[w].append((k, s["cagr"]))
        tail = "; ".join(
            f"{w}: growth turns negative at about {breakeven(cagr[w])} ("
            + ", ".join(f"{k}x {c:+.0f}%" for k, c in cagr[w][len(COST_MULTS) :])
            + ")"
            for w in WINDOWS
        )
        print(f"{'':32}   {tail.replace(' ()', '')}", flush=True)


def main() -> None:
    """Print the three sections."""
    data, cache = Path(sys.argv[1]), Path(sys.argv[2])
    feed = lib.build_feed(data, "4h", cache)
    sigs: dict[str, Signals] = {"live": feed.signals()}
    for name, (key, factory) in GRID.items():
        sigs[name] = feed.signals(f"{LABEL}-{key}", factory)
    # Reason: hysteresis that leaves at the entry threshold is the live rule, so it must match
    # the harness's live signal bar for bar; this guards the re-implemented pieces above.
    assert feed.signals(f"{LABEL}-selfcheck", hysteresis(ENTER)) == sigs["live"], "self-check"
    ranging = {m: [tr.is_ranging(c) for c, _ in feed.views(m)] for m in lib.COINS}
    index = {t: j for j, t in enumerate(feed.times)}

    params: dict[str, PerpsParams] = {}
    runs: dict[tuple[str, str, str], lib.Result] = {}
    for sname, account, changed in SETTINGS:
        params[sname] = dataclasses.replace(lib.account(account)[0], **changed)
        for vname, sig in sigs.items():
            for w in WINDOWS:
                runs[sname, vname, w] = lib.run(params[sname], feed, *lib.WINDOWS[w], signals=sig)

    print("EXP-2026-023 signal slice. Paper-only replay; development 2020-10..2023-12, holdout")
    print("2024-01..2026-11-21. Costs 7 bps a side + borrow 0.0016%/h; funding is not modelled.")
    for sname in (SETTINGS[0][0], SETTINGS[2][0]):
        res = {w: runs[sname, "live", w] for w in WINDOWS}
        trades = {w: trades_of(res[w], params[sname], ranging, index) for w in WINDOWS}
        money_report(sname, float(params[sname].starting_collateral_usd), res, trades)

    print("\n== 2. Churn-reducing variants (grid and selection rule fixed in the docstring)")
    head = f"{'flips':>6} {'range':>6} {'flat':>6}"
    print(f"\nThe signal alone (changes per coin per month, share of changes on ranging bars,")
    print(f"share of time flat):\n{'variant':26} | {head} | {head}")
    for vname, sig in sigs.items():
        cells = [churn(sig, ranging, feed.times, w) for w in WINDOWS]
        print(f"{vname:26} | {cells[0]} | {cells[1]}")
    for sname, _, _ in SETTINGS:
        print(f"\n-- {sname}\n{'variant':26} | {lib.HEADER} | {lib.HEADER}")
        for vname in sigs:
            cells = [lib.cell(runs[sname, vname, w].stats) for w in WINDOWS]
            print(f"{vname:26} | {cells[0]} | {cells[1]}")

    names = [s[0] for s in SETTINGS]
    sharpe = {
        (v, w): [runs[s, v, w].stats["sharpe"] for s in names] for v in sigs for w in WINDOWS
    }
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
    pick = ranked[0]
    print(f"Pick on development alone: {pick}" + (" (no change)" if pick == "live" else ""))

    cash = {s: float(params[s].starting_collateral_usd) for s in names}
    rets = {k: daily_returns(r, cash[k[0]]) for k, r in runs.items()}
    print("\nSharpe minus live's Sharpe, with a 90% paired block-bootstrap interval (an interval")
    print("that spans zero means the difference cannot be told from noise).")
    print(f"{'variant':26} | " + " | ".join(f"{s[:14] + ' ' + w:>20}" for s in names for w in WINDOWS))
    for v in sigs:
        if v == "live":
            cells = [boot(rets[s, v, w]) for s in names for w in WINDOWS]
            print(f"{'live (its own Sharpe)':26} | " + " | ".join(cells), flush=True)
            continue
        cells = [boot(rets[s, v, w], rets[s, "live", w]) for s in names for w in WINDOWS]
        print(f"{v:26} | " + " | ".join(cells), flush=True)

    print("\n== 3. Cost sensitivity (open fee, close fee and borrow all multiplied; 1x = live)")
    print("Higher fees also move the fee-inclusive stop and the assessed leverage slightly.")
    top = [v for v in ranked if v != "live"][:2]
    picks = {v: sigs[v] for v in ["live", *top]}
    for sname in names:
        cost_table(feed, sname, params[sname], picks)
    print(
        "\nFunding: the replay charges a flat borrow of 0.0016%/h (about 14% of position size "
        "a year) on both\nsides and no funding. Jupiter Perps charges borrow, not funding, but "
        "its real rate moves with pool\nutilization, which is highest in strong trends, when "
        "this bot holds the most. On a funding venue a\ntrend follower is usually on the paying "
        "side. Read the 2x and 3x rows as the cautious case: each\nextra 10% a year on position "
        "size costs about 10% x the average open size (section 1) of equity a year."
    )


if __name__ == "__main__":
    main()
