"""EXP-2026-018: stop-loss and take-profit ladder replay for every bot (research only).

Owner request (2026-11-22): "there should always be a SL to protect every trade and then be
moved as trades become more successful to protect gains" and "hits 1st TP > move SL, hits
2nd TP > move SL > 3rd TP". The plan, method grid, split and selection rule are fixed in
research/EXP-2026-018-plan.md and in this file before any result was computed.

Each bot's own entry rule, one position per coin, three coins (BTC, ETH, SOL):
- perps-main: 4h bars, 30-day trend (tsmom_30d), long or short.
- perps-degen: 1h bars, 30-day trend from 1h closes, long or short.
- spot: 4h bars, SMA 20/50, long only.
Only the exit differs between methods, so every method trades the same entries with the
same size (notional = 1% of the coin's capital / 2 typical daily moves). Results are
reported per year and as max drawdown of the coin's constant capital, so they do not depend
on leverage; leverage scales return and drawdown together.

Distances are in "daily moves" (dm): the bot's typical daily move (ADR-032: std of bar
returns over 30 days scaled to a day) times the entry price, fixed at the open. R is the
initial stop distance. Fills, all pessimistic where the bar's order is unknown:
- a stop is checked first, on the bar's adverse extreme; a bar that opens through it fills
  at the open; a take-profit fills at its level;
- when a take-profit fills, the stop moves at once; if that bar closes past the new stop the
  rest exits at the close;
- a trailing stop is updated from the bar's extreme only after the bar is processed;
- after a stop, a trailing exit or the last take-profit, the coin waits for the next UTC
  day, then re-enters if the signal still points that way (the bots' ADR-038 rule);
- a signal change exits at the close (and opens the other side for perps).
Costs: 7 bps of notional per fill, borrow 0.0016%/hour of open notional (configs/perps).
Funding is not modeled (the bots pay Jupiter borrow, not funding).

Usage: uv run python research/stop_ladder_replay.py [data_dir]
Needs <data_dir>/{btc,eth,sol}_{4h,1h}.csv with ts_utc,open,high,low,close,volume.
"""

from __future__ import annotations

import itertools
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COINS = ("btc", "eth", "sol")
FEE = 7 / 10_000
BORROW_PER_HOUR = 0.0016 / 100
RISK_FRACTION = 0.01  # sizing only; identical for every method
SIZE_DM = 2.0  # notional = capital * 1% / (2 dm), the same for every method
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")
BOTS = {
    # name: (timeframe, bars per day, signal, shorts allowed, current stop in dm)
    "perps-main": ("4h", 6, "tsmom", True, 2.0),
    "perps-degen": ("1h", 24, "tsmom", True, 0.9),
    "spot": ("4h", 6, "sma", False, None),  # 2 x ATR(14), measured per entry below
}


@dataclass(frozen=True)
class Exit:
    """One exit method."""

    name: str
    stop_dm: float | None = None  # initial stop distance; None = no stop
    be_at_r: float | None = None  # move the stop to breakeven after +x R
    trail_dm: float | None = None  # chandelier distance from the best extreme
    trail_after_tp: int = 0  # trailing starts after this many take-profits (0 = at open)
    tps: tuple[float, ...] = ()  # take-profit levels in R
    fracs: tuple[float, ...] = ()  # share of the original size closed at each level
    spot_atr: bool = False  # spot's current rule: 2 x ATR(14) stop, no move


def grid() -> list[Exit]:
    """The fixed method grid (plan section 3)."""
    out = [Exit("no stop (signal exit only)")]
    out.append(Exit("current bot stop", stop_dm=-1.0))  # resolved per bot
    for k in (1.0, 1.5, 2.0, 3.0):
        out.append(Exit(f"fixed {k}dm", stop_dm=k))
        out.append(Exit(f"fixed {k}dm + breakeven at 1R", stop_dm=k, be_at_r=1.0))
    for m in (2.0, 3.0, 4.0):
        out.append(Exit(f"chandelier {m}dm", stop_dm=m, trail_dm=m))
    tp_sets = ((1, 2, 3), (1, 2, 4), (1.5, 3, 5), (2, 4, 6))
    frac_sets = ((1 / 3, 1 / 3, 1 / 3), (0.5, 0.25, 0.25), (0.25, 0.25, 0.5))
    for k, tps, fr, runner in itertools.product((1.5, 2.0), tp_sets, frac_sets, (False, True)):
        fr_name = "/".join(str(round(f * 100)) for f in fr)
        tp_name = "/".join(f"{t:g}" for t in tps)
        if runner:
            # Owner's ladder for TP1 and TP2; the last part trails at 3 dm instead of a TP3 cap.
            out.append(
                Exit(
                    f"ladder {k}dm TP {tp_name[: tp_name.rfind('/')]}R +trail3 ({fr_name})",
                    stop_dm=k,
                    tps=tuple(float(t) for t in tps[:2]),
                    fracs=fr[:2],
                    trail_dm=3.0,
                    trail_after_tp=2,
                )
            )
        else:
            out.append(
                Exit(
                    f"ladder {k}dm TP {tp_name}R ({fr_name})",
                    stop_dm=k,
                    tps=tuple(float(t) for t in tps),
                    fracs=fr,
                )
            )
    out += exploratory()
    # Reason: with a trailing runner TP3 is unused, so (1,2,3) and (1,2,4) are the same method.
    return list({e.name: e for e in out}.values())


def exploratory() -> list[Exit]:
    """
    Added AFTER the first results (plan section 6): the capped ladders gave up the few very
    large trend trades that make most of the profit, so these keep part or all of the
    position open with no cap and only ratchet the stop. Labelled "x:"; not pre-registered.
    """
    out = []
    for k in (1.5, 2.0):
        for step in (1.0, 2.0, 3.0):
            levels = tuple(step * n for n in range(1, 200))
            out.append(
                Exit(
                    f"x: ratchet {k}dm, stop up every {step:g}R",
                    stop_dm=k,
                    tps=levels,
                    fracs=(0.0,) * len(levels),
                )
            )
        for tps, fr in (
            ((1, 2), (0.25, 0.25)),
            ((2, 4), (0.25, 0.25)),
            ((2, 4), (1 / 3, 1 / 3)),
            ((1.5, 3), (0.25, 0.25)),
        ):
            name = "/".join(f"{t:g}" for t in tps)
            frn = "/".join(str(round(f * 100)) for f in fr)
            out.append(
                Exit(
                    f"x: ladder {k}dm TP {name}R ({frn}) + hold rest",
                    stop_dm=k,
                    tps=tuple(float(t) for t in tps),
                    fracs=fr,
                )
            )
            levels = tuple(float(t) for t in tps) + tuple(
                tps[-1] + (tps[-1] - tps[-2]) * n for n in range(1, 200)
            )
            fr_all = fr + (0.0,) * (len(levels) - len(fr))
            out.append(
                Exit(
                    f"x: ladder {k}dm TP {name}R ({frn}) + hold rest, ratchet on",
                    stop_dm=k,
                    tps=levels,
                    fracs=fr_all,
                )
            )
    return out


def load(path: Path) -> pd.DataFrame:
    """Load one candle file, indexed by UTC open time."""
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df.pop("ts_utc"), utc=True)
    return df[["open", "high", "low", "close"]].astype(float).sort_index()


def signal(df: pd.DataFrame, kind: str, bpd: int, shorts: bool) -> np.ndarray:
    """Direction decided at each bar's close (+1, -1, 0); causal."""
    c = df["close"]
    if kind == "tsmom":
        d = np.sign(c - c.shift(30 * bpd))
    else:
        d = np.sign(c.rolling(20).mean() - c.rolling(50).mean())
    d = d.fillna(0.0).to_numpy()
    return d if shorts else np.where(d > 0, 1.0, 0.0)


def unit(df: pd.DataFrame, bpd: int) -> np.ndarray:
    """Typical daily move as a fraction (ADR-032)."""
    return (df["close"].pct_change().rolling(30 * bpd).std() * math.sqrt(bpd)).to_numpy()


def atr14(df: pd.DataFrame) -> np.ndarray:
    """ATR(14), simple mean of true range."""
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(14).mean().to_numpy()


def run(df: pd.DataFrame, bot: str, ex: Exit) -> tuple[np.ndarray, list[dict[str, float]]]:
    """
    Replay one coin with one exit method.

    Returns:
        tuple: P&L per bar as a fraction of the coin's capital, and the closed trades.
    """
    tf, bpd, kind, shorts, current = BOTS[bot]
    o, h, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    days = df.index.floor("D").to_numpy()
    sig, dm, atr = signal(df, kind, bpd, shorts), unit(df, bpd), atr14(df)
    hours = 24 / bpd
    pnl = np.zeros(len(df))
    trades: list[dict[str, float]] = []
    pos = 0.0  # side
    entry = size = remaining = stop = r = best = u_entry = 0.0
    tp_hit, blocked_day, realized, mfe = 0, None, 0.0, 0.0

    def close_part(i: int, price: float, frac: float) -> None:
        nonlocal remaining, realized
        q = size * frac
        pnl[i] += q * (price - entry) / entry * pos - q * FEE
        realized += frac * (price - entry) * pos / r if r else 0.0
        remaining -= frac

    def finish(i: int, why: str) -> None:
        nonlocal pos
        trades.append({"r": realized, "mfe": mfe, "why": why, "bars": i})
        pos = 0.0

    for i in range(1, len(df)):
        if pos:
            pnl[i] -= size * remaining * BORROW_PER_HOUR * hours
            adverse, favorable = (lo[i], h[i]) if pos > 0 else (h[i], lo[i])
            done = False
            if stop and (adverse - stop) * pos <= 0:
                fill = o[i] if (o[i] - stop) * pos < 0 else stop
                close_part(i, fill, remaining)
                finish(i, "stop")
                blocked_day, done = days[i], True
            if not done:
                mfe = max(mfe, (favorable - entry) * pos / r) if r else mfe
                while tp_hit < len(ex.tps):
                    level = entry + pos * ex.tps[tp_hit] * r
                    if (favorable - level) * pos < 0:
                        break
                    close_part(i, level, ex.fracs[tp_hit])
                    tp_hit += 1
                    # Owner's ladder: TP1 -> stop to breakeven (fees covered), TP2 -> stop to TP1.
                    if tp_hit == 1:
                        new = entry * (1 + pos * 2 * FEE)
                    else:
                        new = entry + pos * ex.tps[tp_hit - 2] * r
                    stop = new if (new - stop) * pos > 0 else stop
                if remaining <= 1e-9:
                    finish(i, "last tp")
                    blocked_day, done = days[i], True
                elif tp_hit and (c[i] - stop) * pos <= 0:
                    close_part(i, c[i], remaining)
                    finish(i, "stop")
                    blocked_day, done = days[i], True
            if not done:
                if ex.be_at_r and (favorable - entry) * pos >= ex.be_at_r * r:
                    be = entry * (1 + pos * 2 * FEE)
                    stop = be if (be - stop) * pos > 0 else stop
                if ex.trail_dm and tp_hit >= ex.trail_after_tp:
                    best = max(best, favorable) if pos > 0 else min(best, favorable)
                    trail = best - pos * ex.trail_dm * u_entry
                    stop = trail if (trail - stop) * pos > 0 else stop
                if sig[i] != pos:
                    close_part(i, c[i], remaining)
                    finish(i, "signal")
        if blocked_day is not None and days[i] != blocked_day:
            blocked_day = None
        if not pos and sig[i] != 0 and blocked_day is None and dm[i] > 0:
            pos, entry = sig[i], c[i]
            u_entry = dm[i] * entry
            size = RISK_FRACTION / (SIZE_DM * dm[i])
            pnl[i] -= size * FEE
            remaining, tp_hit, realized, mfe = 1.0, 0, 0.0, 0.0
            k = ex.stop_dm
            if ex.spot_atr or (k == -1.0 and current is None):
                dist = 2 * atr[i] if atr[i] > 0 else 2 * u_entry
            elif k == -1.0:
                dist = current * u_entry
            elif k is None:
                dist = 0.0
            else:
                dist = k * u_entry
            stop = entry - pos * dist if dist else 0.0
            r = dist if dist else SIZE_DM * u_entry  # nominal R for the no-stop baseline
            best = entry
            realized -= 2 * FEE * entry / r
    return pnl, trades


def stats(pnl: pd.Series, trades: list[dict[str, float]], years: float) -> dict[str, float]:
    """Return per year, max drawdown, MAR, Sharpe (daily), and trade figures."""
    eq = pnl.cumsum()
    dd = float((eq.cummax() - eq).max())
    daily = pnl.resample("D").sum()
    ret = float(eq.iloc[-1]) / years
    sharpe = float(daily.mean() / daily.std() * math.sqrt(365)) if daily.std() > 0 else 0.0
    rs = np.array([t["r"] for t in trades]) if trades else np.zeros(1)
    winners = [t for t in trades if t["r"] > 0]
    giveback = np.mean([t["mfe"] - t["r"] for t in winners]) if winners else 0.0
    return {
        "ret_yr": ret * 100,
        "max_dd": dd * 100,
        "mar": ret / dd if dd > 0 else 0.0,
        "sharpe": sharpe,
        "trades_yr": len(trades) / years,
        "win": float((rs > 0).mean() * 100),
        "worst_r": float(rs.min()),
        "giveback_r": float(giveback),
    }


def main() -> None:
    """Run every bot x method on the in-sample and holdout periods and print tables."""
    data = Path(sys.argv[1] if len(sys.argv) > 1 else "data/stop-research")
    methods = grid()
    rows = []
    for bot, (tf, *_rest) in BOTS.items():
        frames = {coin: load(data / f"{coin}_{tf}.csv") for coin in COINS}
        for ex in methods:
            if bot == "spot" and ex.stop_dm == -1.0:
                ex = Exit(ex.name, spot_atr=True)
            per = {"in": [], "out": []}
            tr = {"in": [], "out": []}
            for _coin, df in frames.items():
                pnl, trades = run(df, bot, ex)
                s = pd.Series(pnl, index=df.index)
                cut = int(df.index.searchsorted(SPLIT))
                per["in"].append(s.iloc[:cut])
                per["out"].append(s.iloc[cut:])
                tr["in"] += [t for t in trades if t["bars"] < cut]
                tr["out"] += [t for t in trades if t["bars"] >= cut]
            for part in ("in", "out"):
                total = pd.concat(per[part], axis=1).fillna(0.0).sum(axis=1) / len(COINS)
                years = (total.index[-1] - total.index[0]).days / 365.25
                rows.append(
                    {"bot": bot, "method": ex.name, "part": part, **stats(total, tr[part], years)}
                )
    res = pd.DataFrame(rows)
    out = Path(__file__).with_name("EXP-2026-018-results.csv")
    res.to_csv(out, index=False)
    pd.set_option("display.width", 220, "display.max_rows", 500, "display.max_colwidth", 60)
    for bot in BOTS:
        b = res[res.bot == bot].pivot(index="method", columns="part")
        b = b.sort_values(("mar", "in"), ascending=False)
        cols = [
            (m, p)
            for m in (
                "ret_yr",
                "max_dd",
                "mar",
                "sharpe",
                "win",
                "worst_r",
                "giveback_r",
                "trades_yr",
            )
            for p in ("in", "out")
        ]
        print(f"\n=== {bot} (sorted by in-sample MAR) ===")
        print(b[cols].round(2).to_string())
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
