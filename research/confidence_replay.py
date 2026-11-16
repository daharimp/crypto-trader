"""Confidence replay: confidence measured every 4h while a trade runs; add more at 85%+.

EXPLORATORY (owner request, 2026-11-15: "run the confidence test"; earlier: "5-15% based on
confidence", "on really good and confident days [an] option to trade more if confident 85%
and above"). Fixes the flaw found in ``guarded_replay.py`` (confidence measured only at the
open, where the trend is always weak). Every input below was fixed in this file and
committed before any result was computed. Research only; changes no configuration.
TEST INPUTS: buffer 3, collateral 5-15% (approved: 10%, UD-23), the 30% stop, the 3-day
horizon, the buckets, the 200-moment minimum and the 5%-to-15% mapping. Approved values
used: 25x ceiling, 3.5% minimum liquidation distance (UD-27), 15% daily loss limit, 400%
total size (UD-23).

Confidence, per coin at every 4h close where the running rule holds a side:
- Bucket = trend strength (30-day return over a typical 30-day move: below 0.5, 0.5-1,
  1-1.5, 1.5 and up) x whether the 3- and 12-month trends agree with the side (both, mixed,
  both against): 12 buckets.
- A past "moment" made money if holding its side for the next 3 days (18 bars) gained more
  than the round-trip fee. Confidence = share of past moments in the same bucket that made
  money, pooled over SOL, BTC and ETH, counting only moments whose 3 days are over (no
  look-ahead), from the start of each coin's data. Needs at least 200 moments, else unknown.
- Calibration check: for every moment in the replay window, the confidence the bot would
  have shown against what then happened.

One $2,500 account, the running rule's side (4h, 30-day trend), buffer 3, positions valued
at each 4h close, 7 bps fee per side, 20 bps maintenance, Deribit funding.
- SIZE: collateral at the open = 5% + 10% x (confidence - 50%) / 35% of equity, kept between
  5% and 15%; 5% when unknown.
- ADD (owner's "trade more"): while a position is open, at a close where confidence is 85%
  or more and the position's collateral is under 15% of equity, add a second piece that
  brings it to 15% (at least 1% of equity), at the leverage assessed then. At most one add
  per position; it closes with the position (in paper the alert would ask the owner first;
  the replay assumes yes).
- STOP: each piece stops where it has lost 30% of its collateral, fees included; a gap
  fills at the open. After a stop, that coin opens nothing until the next UTC day.
- BAD DAY: down 15% of the day's starting equity -> no opens or adds for the rest of the
  UTC day (and a phone alert).
- Total open size at most 400% of equity; an open or add that would break it is skipped.

Variants: FLAT5 (5% always, no adds: what guarded_replay's OWNER really tested), SIZED (5-15%
at the open), ADD (5% at the open plus the 85% add), SIZED_ADD (both), and RUN4 (the running
rule: 10%, buffer 4, no stop, no bad-day stop) for reference.

Usage: uv run python research/confidence_replay.py
Needs data/long/<coin>_usd_4h.csv and data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from bigger_bets_replay import COINS, NY, RECENT_WEEKS, SHOW_DAYS
from degen_replay import VENUE, floored

from trader.perps.leverage_replay import agreement, assessed_leverage, trend_strength
from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv

START_EQUITY, TOTAL_CAP, HORIZON, MIN_MOMENTS, CONF, STOP_SHARE = 2500.0, 4.0, 18, 200, 0.85, 0.30
FEE, MAINT = VENUE.fee_bps / 10_000, VENUE.maintenance_bps / 10_000
BUCKETS = [f"{s}/{g}" for s in range(4) for g in (-1, 0, 1)]
# name: (buffer, base pct or None for sized, add at 85%, stop, bad-day limit %)
VARIANTS = {
    "RUN4": (4.0, 0.10, False, False, None),
    "FLAT5": (3.0, 0.05, False, True, 15.0),
    "SIZED": (3.0, None, False, True, 15.0),
    "ADD": (3.0, 0.05, True, True, 15.0),
    "SIZED_ADD": (3.0, None, True, True, 15.0),
}


def size_pct(conf: float) -> float:
    """Collateral share of equity from confidence (owner: 5-15%)."""
    if not np.isfinite(conf):
        return 0.05
    return 0.05 + 0.10 * min(max((conf - 0.50) / 0.35, 0.0), 1.0)


def prepare(coin: str, index: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Per-coin arrays on the shared 4h index, including each moment's bucket and outcome."""
    df = load_csv(f"data/long/{coin}_usd_4h.csv").reindex(index)
    c = df["close"]
    side = np.sign(c.pct_change(180)).fillna(0.0)
    move = c.pct_change().rolling(180).std() * math.sqrt(6)
    strength = pd.cut(trend_strength(c), [-np.inf, 0.5, 1.0, 1.5, np.inf], labels=False)
    agree = agreement(c, side).astype(int)
    ok = strength.notna() & (side != 0)
    bucket = np.where(ok, strength.fillna(0).astype(int).astype(str) + "/" + agree.astype(str), "")
    ahead = side * (c.shift(-HORIZON) / c - 1) - 2 * FEE
    out = {k: df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close")}
    out["side"] = side.to_numpy()
    out["bucket"] = bucket
    out["won"] = (ahead > 0).to_numpy()
    out["known"] = (ok & ahead.notna()).to_numpy()
    out["fund"] = np.nan_to_num(
        per_bar(load_funding(f"data/funding/deribit_{coin}.csv"), index).to_numpy(dtype=float)
    )
    for b in (4.0, 3.0):
        out[f"lev{b:.0f}"] = floored(assessed_leverage(move, b, VENUE)).to_numpy()
    return out


def confidence_table(data: dict[str, dict[str, np.ndarray]], n: int) -> dict[str, np.ndarray]:
    """Per bucket, the confidence known at each close (NaN below the minimum)."""
    table = {}
    for b in BUCKETS:
        wins, count = np.zeros(n), np.zeros(n)
        for d in data.values():
            idx = np.flatnonzero((d["bucket"] == b) & d["known"])
            resolve = idx + HORIZON
            keep = resolve < n
            np.add.at(count, resolve[keep], 1)
            np.add.at(wins, resolve[keep], d["won"][idx[keep]].astype(float))
        cw, cc = np.cumsum(wins), np.cumsum(count)
        with np.errstate(invalid="ignore", divide="ignore"):
            table[b] = np.where(cc >= MIN_MOMENTS, cw / cc, np.nan)
    return table


def conf_of(table: dict[str, np.ndarray], d: dict[str, np.ndarray], i: int) -> float:
    """Confidence the bot would show for this coin at close ``i``."""
    b = d["bucket"][i]
    return float(table[b][i]) if b in table else float("nan")


def piece(side: float, coll: float, lev: float, entry: float, stopped: bool) -> dict:
    """One open piece of a position."""
    size = coll * lev
    dist = max(STOP_SHARE / lev - 2 * FEE, 0.0)
    stop = entry * (1 - side * dist) if stopped else float("nan")
    return {
        "side": side,
        "coll": coll,
        "size": size,
        "entry": entry,
        "paid": 0.0,
        "value": coll - size * FEE,
        "stop": stop,
    }


def simulate(data, table, index, a, variant):
    """Run one account from bar ``a``; return dollars per bar and counters."""
    buf, base, add, stopped, limit = variant
    pos: dict[tuple[str, int], dict] = {}
    pnl = np.zeros(len(index))
    equity = day_start = START_EQUITY
    halted, day, wait = False, index[a].date(), set()
    n = {"opens": 0, "adds": 0, "stops": 0, "liqs": 0, "halt_days": 0, "skipped_cap": 0}
    pcts: list[float] = []
    for i in range(a, len(index) - 1):
        if index[i].date() != day:
            day, day_start, halted, wait = index[i].date(), equity, False, set()
        bar = 0.0
        for key in [k for k in pos if pos[k]["side"] != data[k[0]]["side"][i - 1]]:
            p, o = pos.pop(key), data[key[0]]["open"][i]
            left = max(
                p["coll"]
                + p["side"] * p["size"] * (o / p["entry"] - 1)
                - p["size"] * FEE
                - p["paid"],
                0.0,
            )
            bar += left - p["value"]
        for coin, d in data.items():
            target, lev = d["side"][i - 1], d[f"lev{buf:.0f}"][i - 1]
            if (
                target == 0
                or halted
                or coin in wait
                or equity <= 0
                or not (np.isfinite(lev) and lev >= 1.0)
            ):
                continue
            conf = conf_of(table, d, i - 1)
            used = sum(q["size"] for q in pos.values())
            if (coin, 0) not in pos:
                pct = size_pct(conf) if base is None else base
                p = piece(target, pct * equity, lev, d["open"][i], stopped)
                if used + p["size"] > TOTAL_CAP * equity:
                    n["skipped_cap"] += 1
                    continue
                pos[(coin, 0)] = p
                bar -= 2 * p["size"] * FEE
                n["opens"] += 1
                pcts.append(pct)
            elif add and (coin, 1) not in pos and conf >= CONF:
                extra = 0.15 * equity - pos[(coin, 0)]["coll"]
                if extra < 0.01 * equity:
                    continue
                p = piece(target, extra, lev, d["open"][i], stopped)
                if used + p["size"] > TOTAL_CAP * equity:
                    n["skipped_cap"] += 1
                    continue
                pos[(coin, 1)] = p
                bar -= 2 * p["size"] * FEE
                n["adds"] += 1
        for key in list(pos):
            d, p = data[key[0]], pos[key]
            p["paid"] += p["side"] * p["size"] * d["fund"][i]
            adverse = d["low"][i] if p["side"] > 0 else d["high"][i]
            if np.isfinite(p["stop"]) and (adverse - p["stop"]) * p["side"] <= 0:
                o = d["open"][i]
                fill = min(o, p["stop"]) if p["side"] > 0 else max(o, p["stop"])
                left = (
                    p["coll"]
                    + p["side"] * p["size"] * (fill / p["entry"] - 1)
                    - p["size"] * FEE
                    - p["paid"]
                )
                if left > p["size"] * MAINT:
                    bar += left - p["value"]
                    n["stops"] += 1
                    wait.add(key[0])
                    del pos[key]
                    continue
            worst = (
                p["coll"]
                + p["side"] * p["size"] * (adverse / p["entry"] - 1)
                - p["size"] * FEE
                - p["paid"]
            )
            if worst <= p["size"] * MAINT:
                bar -= p["value"]
                n["liqs"] += 1
                del pos[key]
                continue
            now = max(
                p["coll"]
                + p["side"] * p["size"] * (d["close"][i] / p["entry"] - 1)
                - p["size"] * FEE
                - p["paid"],
                0.0,
            )
            bar += now - p["value"]
            p["value"] = now
        pnl[i] = bar
        equity += bar
        if limit is not None and not halted and day_start - equity >= day_start * limit / 100:
            halted = True
            n["halt_days"] += 1
    n["avg_open_pct"] = round(float(np.mean(pcts)) * 100, 1) if pcts else 0.0
    return pd.Series(pnl[a:-1], index=index[a:-1]), n


def calibration(data, table, a: int) -> None:
    """Shown confidence against what happened over the next 3 days, replay window only."""
    rows = []
    for d in data.values():
        for i in range(a, len(d["side"])):
            if d["known"][i]:
                c = conf_of(table, d, i)
                if np.isfinite(c):
                    rows.append((c, d["won"][i]))
    df = pd.DataFrame(rows, columns=["conf", "won"])
    bands = pd.cut(df["conf"], [0, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0], right=False)
    print("Calibration (replay window): confidence shown vs share that made money in 3 days")
    print(
        df.groupby(bands, observed=True)["won"]
        .agg(moments="count", made_money="mean")
        .round(2)
        .to_string()
    )
    print(f"highest confidence shown: {df['conf'].max():.0%}\n")


def main() -> None:
    """Print calibration, the account comparison, and the recent 12-hour blocks."""
    index = load_csv("data/long/sol_usd_4h.csv").index
    for c in COINS[1:]:
        index = index.intersection(load_csv(f"data/long/{c}_usd_4h.csv").index)
    start = (index[0] + pd.Timedelta(days=200)).ceil("D")
    start += pd.Timedelta(days=(7 - start.day_of_week) % 7)
    a = int(index.searchsorted(start))
    data = {c: prepare(c, index) for c in COINS}
    table = confidence_table(data, len(index))
    print(f"One $2,500 account from {start.date()}; 12h blocks start 00:00/12:00 UTC.\n")
    calibration(data, table, a)
    bars = {}
    print(
        f"{'':<11}{'end $':>10}{'worst drop':>12}{'last 26 wks':>13}{'12h up':>8}{'worst 12h':>11}  counters"
    )
    for name, v in VARIANTS.items():
        s, n = simulate(data, table, index, a, v)
        bars[name] = s
        eq = START_EQUITY + s.cumsum()
        dd = float((eq / eq.cummax() - 1).min())
        then = eq[eq.index <= eq.index[-1] - pd.Timedelta(weeks=RECENT_WEEKS)].iloc[-1]
        b = s.resample("12h").sum()
        print(
            f"{name:<11}{eq.iloc[-1]:>10,.0f}{dd * 100:>11.0f}%{(eq.iloc[-1] / then - 1) * 100:>+12.0f}%"
            f"{(b > 0).mean() * 100:>7.0f}%{b.min():>11,.0f}  {n}"
        )
    table12 = pd.DataFrame({k: v.resample("12h").sum() for k, v in bars.items()}).round(0)
    table12.index = [t.tz_convert(NY).strftime("%a %b %d %I%p ET") for t in table12.index]
    print(f"\nrunning total over the last {SHOW_DAYS} days (12-hour blocks, New York time):")
    print(table12.iloc[-SHOW_DAYS * 2 :].cumsum().to_string())
    print(f"\nwhole account, last {RECENT_WEEKS} weeks in 12-hour blocks:")
    print(table12.iloc[-RECENT_WEEKS * 14 :].to_string())
    print("\nExploratory replay on past prices with test inputs; not a forecast.")


if __name__ == "__main__":
    main()
