"""EXP-2026-020: does a shared regime layer make long+short trading better than one side?

Research only; changes no trading code. Replays direction rules on BTC/ETH/SOL 4h candles
(Binance spot, 2020-01 .. 2026-11), 1x notional per coin, equal weight, with a hard stop on
every trade (2 typical daily moves) and a next-UTC-day wait after a stop (ADR-038). Rules are
picked on 2020-2023 (development) and checked on 2024-2026 (holdout).

Usage: python research/run_exp020.py <dir with btc_4h.csv eth_4h.csv sol_4h.csv>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BARS_PER_DAY = 6
FEE = 0.0007  # per side (Jupiter 0.06% + 0.01% impact)
BORROW_H = {"base": 0.000016, "stress": 0.0001}  # per hour, both sides pay on Jupiter
STOP_DAILY_MOVES = 2.0
COINS = ("btc", "eth", "sol")
PERIODS = {
    "development 2020-2023": ("2020-01-01", "2024-01-01"),
    "holdout 2024-2026": ("2024-01-01", "2026-12-01"),
    "bear 2022": ("2022-01-01", "2023-01-01"),
    "last 60 days": ("2026-09-22", "2026-12-01"),
}


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["ts_utc"]).set_index("ts_utc")
    return df[["open", "high", "low", "close"]].astype(float)


def features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    f["sma20"], f["sma50"], f["sma200"] = (
        c.rolling(20).mean(),
        c.rolling(50).mean(),
        c.rolling(200).mean(),
    )
    f["mom30"] = np.sign(c / c.shift(30 * BARS_PER_DAY) - 1)
    daily = np.log(c / c.shift(BARS_PER_DAY))
    f["dmove"] = daily.rolling(30 * BARS_PER_DAY).std()  # typical daily move (fraction)
    # Regime inputs: 200-bar SMA slope over 5 days and price vs SMA200.
    f["slope200"] = np.sign(f["sma200"] - f["sma200"].shift(5 * BARS_PER_DAY))
    return f


def side_rule(name: str, f: pd.DataFrame, c: pd.Series) -> pd.Series:
    """+1 long, -1 short, 0 flat, from data up to and including each bar's close."""
    up_sma = np.where(f["sma50"] > f["sma200"], 1, -1)
    above = np.where(c > f["sma200"], 1, -1)
    mom = f["mom30"].fillna(0).to_numpy()
    if name.startswith("tsmom30"):
        s = mom
    elif name.startswith("sma50/200"):
        s = up_sma
    elif name.startswith("sma20/50"):
        s = np.where(f["sma20"] > f["sma50"], 1, -1)
    elif name.startswith("regime2"):
        s = np.where((above == 1) & (mom == 1), 1, np.where((above == -1) & (mom == -1), -1, 0))
    elif name.startswith("regime"):
        # Shared regime detector: trend up = price above SMA200 AND 30-day momentum up AND
        # SMA200 rising; trend down = all three down; anything else = range -> flat.
        slope = f["slope200"].fillna(0).to_numpy()
        s = np.where(
            (above == 1) & (mom == 1) & (slope == 1),
            1,
            np.where((above == -1) & (mom == -1) & (slope == -1), -1, 0),
        )
    else:
        raise ValueError(name)
    s = pd.Series(s, index=f.index, dtype=float)
    s[f["sma200"].isna() | f["dmove"].isna()] = 0
    if name.endswith(" L"):
        s = s.clip(lower=0)
    elif name.endswith(" S"):
        s = s.clip(upper=0)
    return s


def replay(df: pd.DataFrame, f: pd.DataFrame, sig: pd.Series, borrow_h: float):
    """Bar-by-bar replay. Returns per-bar return series and a trade list."""
    o, hi, lo, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    s, dm = sig.to_numpy(), f["dmove"].to_numpy()
    days = df.index.normalize().to_numpy()
    n = len(df)
    ret = np.zeros(n)
    trades = []  # (entry_time, side, return)
    pos, entry, stop, t_in, blocked_day = 0, 0.0, 0.0, None, None
    borrow_bar = borrow_h * 24 / BARS_PER_DAY
    for i in range(1, n):
        r = 0.0
        if pos != 0:
            # stop check within bar i (gap fills at open)
            hit = (pos == 1 and lo[i] <= stop) or (pos == -1 and hi[i] >= stop)
            if hit:
                px = min(o[i], stop) if pos == 1 else max(o[i], stop)
                r = pos * (px / c[i - 1] - 1) - FEE - borrow_bar
                trades.append((t_in, pos, pos * (px / entry - 1) - 2 * FEE))
                pos, blocked_day = 0, days[i]
            else:
                r = pos * (c[i] / c[i - 1] - 1) - borrow_bar
        want = int(s[i])
        if pos != 0 and want != pos:  # signal changed: exit at close
            r -= FEE
            trades.append((t_in, pos, pos * (c[i] / entry - 1) - 2 * FEE))
            pos = 0
        if pos == 0 and want != 0 and (blocked_day is None or days[i] != blocked_day):
            pos, entry, t_in = want, c[i], df.index[i]
            stop = entry * (1 - pos * STOP_DAILY_MOVES * dm[i])
            r -= FEE
        ret[i] = r
    return pd.Series(ret, index=df.index), trades


def stats(port: pd.Series, trades: list, start: str, end: str) -> dict:
    r = port[(port.index >= start) & (port.index < end)]
    eq = (1 + r).cumprod()
    yrs = max(len(r) / (365 * BARS_PER_DAY), 1e-9)
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if len(r) else 0
    sharpe = r.mean() / r.std() * np.sqrt(365 * BARS_PER_DAY) if r.std() > 0 else 0
    dd = (1 - eq / eq.cummax()).max() if len(r) else 0
    tr = [t for t in trades if start <= str(t[0]) < end]
    wins = sum(x[2] for x in tr if x[2] > 0)
    losses = -sum(x[2] for x in tr if x[2] < 0)
    lsum = sum(x[2] for x in tr if x[1] == 1) / 3  # per-coin-weight contribution
    ssum = sum(x[2] for x in tr if x[1] == -1) / 3
    return {
        "trades": len(tr),
        "per_mo": len(tr) / (yrs * 12),
        "ret": eq.iloc[-1] - 1,
        "cagr": cagr,
        "dd": dd,
        "sharpe": sharpe,
        "pf": wins / losses if losses else float("inf"),
        "nL": sum(1 for x in tr if x[1] == 1),
        "L": lsum,
        "nS": sum(1 for x in tr if x[1] == -1),
        "S": ssum,
    }


RULES = [
    "tsmom30 L+S (perps today)",
    "tsmom30 L",
    "tsmom30 S",
    "sma50/200 L+S",
    "sma50/200 L",
    "sma50/200 S",
    "sma20/50 L+S",
    "regime L+S",
    "regime L",
    "regime S",
    "regime2 L+S",
    "regime2 L",
]


def main(data_dir: Path) -> None:
    dfs = {k: load(data_dir / f"{k}_4h.csv") for k in COINS}
    feats = {k: features(v) for k, v in dfs.items()}
    print(
        "EXP-2026-020 long/short regime layer. BTC/ETH/SOL 4h (Binance spot) 1x each, equal weight."
    )
    print(
        f"Stop {STOP_DAILY_MOVES} typical daily moves from entry on every trade; next-UTC-day wait after a stop."
    )
    print(f"Fees {FEE * 1e4:.0f} bps a side; borrow on both sides (spot longs would pay none).")
    print(
        "Return/CAGR/maxDD/Sharpe come from the per-bar equity, borrow included. trades, PF, L$ and S$"
    )
    print(
        "count closed trades opened inside the window, before borrow; L$/S$ = summed trade return / 3."
    )
    print(
        f"Data {min(d.index[0] for d in dfs.values())} .. {max(d.index[-1] for d in dfs.values())}\n"
    )
    for cost in ("base", "stress"):
        results = {}
        for rule in RULES:
            rets, trades = [], []
            for k in COINS:
                sig = side_rule(rule, feats[k], dfs[k]["close"])
                r, t = replay(dfs[k], feats[k], sig, BORROW_H[cost])
                rets.append(r)
                trades += t
            port = pd.concat(rets, axis=1).fillna(0).mean(axis=1)
            results[rule] = (port, trades)
        for pname, (a, b) in PERIODS.items():
            if cost == "stress" and pname not in ("development 2020-2023", "holdout 2024-2026"):
                continue
            print(f"== {pname}  [{cost} borrow {BORROW_H[cost] * 100:.4f}%/h]")
            print(
                f"{'rule':28s}{'trades':>7s}{'/mo':>6s}{'return':>9s}{'CAGR':>8s}{'maxDD':>7s}{'sharpe':>7s}{'PF':>6s}{'L n':>5s}{'L$':>7s}{'S n':>5s}{'S$':>7s}"
            )
            for rule, (port, trades) in results.items():
                s = stats(port, trades, a, b)
                print(
                    f"{rule:28s}{s['trades']:7d}{s['per_mo']:6.1f}{s['ret'] * 100:8.1f}%{s['cagr'] * 100:7.1f}%{s['dd'] * 100:6.1f}%"
                    f"{s['sharpe']:7.2f}{s['pf']:6.2f}{s['nL']:5d}{s['L'] * 100:6.0f}%{s['nS']:5d}{s['S'] * 100:6.0f}%"
                )
            print()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
