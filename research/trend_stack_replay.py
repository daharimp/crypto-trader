"""Trend-stack replay: 1D direction, 1H structure, 15M trigger, stops, trailing exit.

EXPLORATORY (owner request, 2026-11-15). Ideas borrowed from the owner's Longatron GPT (the
1D -> 1H -> 15M stack, a confidence threshold, a stop on every trade); it is not a copy of
it. Every input below was fixed in this file and committed before any result was computed.
Research only; changes no configuration.

Each 15-minute close, from completed candles only:
- Direction (required): daily EMA 9 above EMA 26 -> longs only; below -> shorts only.
- Seven checks (shorts mirror each one):
  1. 1H EMA 9 above EMA 26;  2. 1H MACD (12, 26, 9) histogram above 0;
  3. 15M EMA 9 crossed above EMA 26 within the last 4 bars and is still above;
  4. 15M RSI 14 between 50 and 70 (shorts 30 to 50);  5. close above today's VWAP (UTC day);
  6. 15M Stoch RSI (14, 14, 3, 3) %K above %D;  7. 15M volume above its 20-bar average.
- Enter at the next open when flat and at least 6 of 7 checks pass (owner: 6 of 7).
- Stop: the 12-bar swing low (high for shorts), at least one 15M ATR 14 from the close.
- Exit (owner: trail the trend): the stop is hit, or at the next open after 15M EMA 9 crosses
  back over EMA 26. A gap through the stop fills at the open; a gap through the liquidation
  price loses the whole collateral.
- Leverage from the stop distance (owner: conservative on quantity, degen on quality):
  leverage = share of collateral lost if stopped / stop distance, rounded down to 0.1x,
  between 1x and 25x. Share: 20% on a 6-of-7 setup, 50% on a 7-of-7 setup (test inputs,
  not approved values). Variant FLAT20: 20% on every setup, to show what the 7-of-7 boost adds.
- $250 collateral per trade per coin, 7 bps fee per side on size, 20 bps maintenance,
  measured Deribit funding charged per 15 minutes (a quarter of the hourly rate).

Baseline: the running paper account (4h, 30-day trend, 4 daily moves), on the same weeks.

Usage: uv run python research/trend_stack_replay.py
Needs data/m15/<coin>_usd_15m.csv, data/long/<coin>_usd_4h.csv, data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
from degen_replay import HEAD, baseline, run, summary

from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv

COINS = ("sol", "btc", "eth")
FEE, MAINT, COLL, CAP = 0.0007, 0.002, 250.0, 25.0
SHARE = {6: 0.20, 7: 0.50}
FLAT = {6: 0.20, 7: 0.20}
M15 = pd.Timedelta(minutes=15)
RECENT_WEEKS = 26


def ema(s: pd.Series, n: int) -> pd.Series:
    """Exponential moving average (span ``n``)."""
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def completed(close: pd.Series, rule: str, bars: int) -> pd.Series:
    """Closes of complete ``rule`` candles, indexed by the 15M bar whose close completes them."""
    g = close.resample(rule, label="left", closed="left")
    out = g.last()[g.count() == bars]
    out.index = out.index + (bars - 1) * M15
    return out


def on_bars(s: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Carry a higher-timeframe series forward onto the 15M index (past values only)."""
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def checks(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Direction (+1, -1, 0) and the long and short check counts after each 15M close."""
    c, v = df["close"], df["volume"]
    h1, d1 = completed(c, "1h", 4), completed(c, "1D", 96)
    trend_d = on_bars(np.sign(ema(d1, 9) - ema(d1, 26)), df.index).fillna(0.0)
    e1 = on_bars(ema(h1, 9) - ema(h1, 26), df.index)
    macd = ema(h1, 12) - ema(h1, 26)
    hist = on_bars(macd - ema(macd, 9), df.index)
    gap = ema(c, 9) - ema(c, 26)
    up_x = ((gap > 0) & (gap.shift(1) <= 0)).astype(float).rolling(4).max() > 0
    dn_x = ((gap < 0) & (gap.shift(1) >= 0)).astype(float).rolling(4).max() > 0
    r = rsi(c)
    tp = (df["high"] + df["low"] + c) / 3
    day = df.index.floor("D")
    vwap = (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum()
    st = (r - r.rolling(14).min()) / (r.rolling(14).max() - r.rolling(14).min())
    k = st.rolling(3).mean()
    d = k.rolling(3).mean()
    loud = v > v.rolling(20).mean()
    long_ = [e1 > 0, hist > 0, up_x & (gap > 0), r.between(50, 70), c > vwap, k > d, loud]
    short = [e1 < 0, hist < 0, dn_x & (gap < 0), r.between(30, 50), c < vwap, k < d, loud]
    return trend_d, sum(x.astype(int) for x in long_), sum(x.astype(int) for x in short)


def simulate(df: pd.DataFrame, fund15: np.ndarray, a: int, share: dict[int, float]):
    """Replay from bar ``a``; return dollars per bar and the trade list."""
    o, hi, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    trend, nl, ns = (x.to_numpy() for x in checks(df))
    gap = (ema(df["close"], 9) - ema(df["close"], 26)).to_numpy()
    tr = np.maximum(
        hi - lo, np.maximum(abs(hi - np.r_[np.nan, c[:-1]]), abs(lo - np.r_[np.nan, c[:-1]]))
    )
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    swing_lo = pd.Series(lo).rolling(12).min().to_numpy()
    swing_hi = pd.Series(hi).rolling(12).max().to_numpy()
    pnl, trades = np.zeros(len(df)), []
    i = a - 1
    while i < len(df) - 2:
        i += 1
        want = 1 if trend[i] > 0 and nl[i] >= 6 else -1 if trend[i] < 0 and ns[i] >= 6 else 0
        if want == 0 or not np.isfinite(atr[i]):
            continue
        score = int(nl[i] if want > 0 else ns[i])
        raw_stop = swing_lo[i] if want > 0 else swing_hi[i]
        stop = min(raw_stop, c[i] - atr[i]) if want > 0 else max(raw_stop, c[i] + atr[i])
        entry = o[i + 1]
        dist = (entry - stop) / entry * want
        if not np.isfinite(dist) or dist <= 0:
            continue
        lev = min(CAP, max(1.0, math.floor(share[score] / dist * 10 + 1e-9) / 10))
        size, side, j, paid = COLL * lev, want, i + 1, 0.0
        liq = entry * (1 - want * (1 / lev - FEE - MAINT))
        # Hold from bar j: stop and liquidation inside each bar, trail at each close.
        while True:
            paid += side * size * fund15[j]
            adverse = lo[j] if side > 0 else hi[j]
            if (adverse - liq) * side <= 0 and (o[j] - liq) * side <= 0:
                res, why = -COLL, "liquidated"
            elif (adverse - stop) * side <= 0:
                fill = min(o[j], stop) if side > 0 else max(o[j], stop)
                res, why = side * size * (fill / entry - 1), "stop"
            elif j + 1 < len(df) and gap[j] * side < 0:
                res, why = side * size * (o[j + 1] / entry - 1), "trail"
                j += 1
            elif j + 1 >= len(df):
                res, why = side * size * (c[j] / entry - 1), "end"
            else:
                j += 1
                continue
            if why != "liquidated":
                res = max(res - 2 * size * FEE - paid, -COLL)
            pnl[j] += res
            trades.append({"bar": i, "score": score, "lev": lev, "pnl": res, "why": why})
            break
        # Reason: flat again; the next entry is decided at the exit bar's close at the earliest.
        i = j
    return pnl, trades


def main() -> None:
    """Print provenance, per-coin and whole-account weekly results, and trade quality."""
    print("=== Data files (rows, first, last, sha256) ===")
    for c in COINS:
        for path in (f"data/m15/{c}_usd_15m.csv", f"data/funding/deribit_{c}.csv"):
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
            print(
                f"  {path}: {len(lines) - 1} rows, {lines[1].split(',')[0]} to {lines[-1].split(',')[0]}, {digest}"
            )

    acct: dict[str, list[pd.Series]] = {"STACK": [], "FLAT20": [], "BASELINE": []}
    for coin in COINS:
        df = load_csv(f"data/m15/{coin}_usd_15m.csv")
        df4 = load_csv(f"data/long/{coin}_usd_4h.csv")
        hourly = load_funding(f"data/funding/deribit_{coin}.csv")
        fund15 = (hourly.reindex(df.index.floor("h")).to_numpy() / 4).astype(float)
        fund15 = np.nan_to_num(fund15)
        start = (df.index[0] + pd.Timedelta(days=40)).ceil("D")
        start += pd.Timedelta(days=(7 - start.day_of_week) % 7)
        a = int(df.index.searchsorted(start))
        print(f"\n=== {coin.upper()} from {start.date()} ({len(df) - a} 15M bars) ===")
        print(HEAD)
        for name, share in (("STACK", SHARE), ("FLAT20", FLAT)):
            pnl, trades = simulate(df, fund15, a, share)
            w = (
                pd.Series(pnl[a:], index=df.index[a:])
                .resample("W-SUN", label="left", closed="left")
                .sum()
            )
            acct[name].append(w)
            liqs = sum(t["why"] == "liquidated" for t in trades)
            avg = float(np.mean([t["lev"] for t in trades])) if trades else 0.0
            print(summary(f"{name} all", w, liqs, len(trades), float("nan"), avg))
            print(
                summary(f"{name} last {RECENT_WEEKS} wks", w.iloc[-RECENT_WEEKS:], 0, 0, 0, 0)[:-31]
            )
            if name == "STACK":
                for q in (6, 7):
                    t = [x for x in trades if x["score"] == q]
                    if t:
                        won = np.mean([x["pnl"] > 0 for x in t]) * 100
                        print(
                            f"    {q} of 7: {len(t)} trades, won {won:.0f}%, avg ${np.mean([x['pnl'] for x in t]):,.0f},"
                            f" total ${sum(x['pnl'] for x in t):,.0f}, avg lev {np.mean([x['lev'] for x in t]):.1f}x"
                        )
                exits = pd.Series([t["why"] for t in trades]).value_counts().to_dict()
                print(f"    exits: {exits}")
        a4 = int(df4.index.searchsorted(start))
        r, w, held, avg = run("BASELINE", df4, *baseline(df4), per_bar(hourly, df4.index), a4)
        acct["BASELINE"].append(w)
        print(summary("BASELINE all", w, r.liquidations, len(r.trades), held, avg))
        print(
            summary(f"BASELINE last {RECENT_WEEKS} wks", w.iloc[-RECENT_WEEKS:], 0, 0, 0, 0)[:-31]
        )

    print("\n=== Whole account: SOL + BTC + ETH together, $250 collateral each per trade ===")
    print(HEAD[:-31])
    totals = {}
    for name, parts in acct.items():
        w = pd.concat(parts, axis=1).dropna().sum(axis=1)
        totals[name] = w
        print(summary(f"{name} all", w, 0, 0, 0, 0)[:-31])
        print(summary(f"{name} last {RECENT_WEEKS} wks", w.iloc[-RECENT_WEEKS:], 0, 0, 0, 0)[:-31])
    last = pd.DataFrame(totals).iloc[-8:].round(0)
    last.index = [d.date() for d in last.index]
    print("\nwhole account, last 8 weeks (week starting Monday):")
    print(last.to_string())
    print("\nExploratory replay on past prices; not pre-registered and not a forecast.")


if __name__ == "__main__":
    main()
