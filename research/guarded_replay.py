"""Guarded replay: the owner's plan (buffer 3, bad-day stop, 5-15% by confidence, 30% stop).

EXPLORATORY (owner request, 2026-11-15: "3 is the floor; if performance is bad that day a
noti should be sent to stop and analyze for the rest of the day; on really good and
confident days [an] option to trade more if confident 85% and above on [the] move"; "5-15% based on confidence and with a SL strat to
prevent [more] than 30% loss of what [is] at risk during [the] trade"). Every
input below was fixed in this file and committed before any result was computed. Research
only; changes no configuration. TEST INPUTS: buffer 3 and 2, collateral 5-15% (the approved
value is 10%, UD-23), the 30% stop, the confidence buckets, the 5%-to-15% mapping and the
20-trade minimum. Approved values used: 25x ceiling and 3.5% minimum liquidation distance
(UD-27), 15% daily loss limit, 3 positions, 400% total size (UD-23).

One account: $2,500 start, SOL + BTC + ETH, the running rule's signal (4h candles, 30-day
trend, long or short), positions valued at each 4h close. Collateral is a share of the
account's equity when the position opens (as the paper bot does): 10% in RUN4, B3 and
B3_HALT15; 5-15% by confidence in the OWNER variants.
- Bad day: when the account is down at least LIMIT% of its equity at the start of the UTC
  day (checked at each 4h close), it stops for the rest of the day (and would send a phone
  alert). HALT: no new positions; CLOSE: also closes every position at the next open.
- Confidence: at each close where a trade would open, the share of past trades in the same
  bucket that made money, counting only trades already closed by then (no look-ahead),
  across the three coins. Bucket = trend strength (30-day return over a typical 30-day
  move: below 0.5, 0.5-1, 1-1.5, 1.5 and up) x whether the 3- and 12-month trends agree
  (both for, mixed, both against). Needs at least 20 past trades in the bucket.
- BOOST: at 85% confidence or more, open at buffer 2 instead of 3 (in the paper account the
  alert would ask the owner first; the replay assumes yes).
- SIZE (owner: 5-15% based on confidence): collateral = 5% + 10% x (confidence - 50%) / 35%,
  kept between 5% and 15%; 5% when confidence is unknown. So 50% or less -> 5%, 85%+ -> 15%.
- STOP (owner: never lose more than 30% of what is at risk): a stop at the price where the
  trade, fees included, has lost 30% of its collateral. A gap through it fills at the open.
  After a stop that coin waits for the next UTC day before it can open again (otherwise
  the still-valid trend would reopen it at once).
- Total open size stays at or under 400% of equity; an open that would break it is skipped.
Costs as the other replays: 7 bps fee per side, 20 bps maintenance, Deribit funding,
liquidation on each bar's adverse extreme loses the collateral.

Usage: uv run python research/guarded_replay.py
Needs data/long/<coin>_usd_4h.csv and data/funding/deribit_<coin>.csv.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from bigger_bets_replay import COINS, NY, RECENT_WEEKS, SHOW_DAYS, row
from degen_replay import VENUE, floored

from trader.perps.leverage_replay import agreement, assessed_leverage, trend_strength
from trader.research.funding import load_funding, per_bar
from trader.research.lab import load_csv

START_EQUITY, TOTAL_CAP, MIN_TRADES, CONF = 2500.0, 4.0, 20, 0.85
FEE, MAINT = VENUE.fee_bps / 10_000, VENUE.maintenance_bps / 10_000
STOP_SHARE = 0.30
# name: (base buffer, bad-day limit % or None, close on a bad day, boost, sized, stop)
VARIANTS = {
    "RUN4": (4.0, None, False, False, False, False),
    "B3": (3.0, None, False, False, False, False),
    "B3_HALT15": (3.0, 15.0, False, False, False, False),
    "OWNER": (3.0, 15.0, False, True, True, True),
    "OWNER_NOSTOP": (3.0, 15.0, False, True, True, False),
    "OWNER_CLOSE": (3.0, 15.0, True, True, True, True),
}


def size_pct(conf: float) -> float:
    """Collateral share of equity from confidence (owner: 5-15%)."""
    if not np.isfinite(conf):
        return 0.05
    return 0.05 + 0.10 * min(max((conf - 0.50) / 0.35, 0.0), 1.0)


def confidence(c: pd.Series, side: pd.Series, bucket: pd.Series) -> pd.DataFrame:
    """Every entry of the base signal: bar, bucket, the bar its trade closes, and the result."""
    s, o = side.to_numpy(), c.to_numpy()
    rows, i = [], 1
    while i < len(s) - 1:
        if s[i] != 0 and s[i] != s[i - 1]:
            e = i + 1
            while e < len(s) - 1 and s[e] == s[i]:
                e += 1
            gain = s[i] * (o[e] / o[i] - 1) - 2 * FEE
            rows.append((i, bucket.iloc[i], e, gain > 0))
            i = e
        else:
            i += 1
    return pd.DataFrame(rows, columns=["bar", "bucket", "closed", "won"])


def prepare(coin: str, index: pd.DatetimeIndex) -> dict[str, np.ndarray | pd.DataFrame]:
    """Per-coin arrays on the shared 4h index."""
    df = load_csv(f"data/long/{coin}_usd_4h.csv").reindex(index)
    fund = per_bar(load_funding(f"data/funding/deribit_{coin}.csv"), index)
    c = df["close"]
    side = np.sign(c.pct_change(180)).fillna(0.0)
    move = c.pct_change().rolling(180).std() * math.sqrt(6)
    strength = pd.cut(trend_strength(c), [-np.inf, 0.5, 1.0, 1.5, np.inf], labels=False)
    bucket = strength.astype("Int64").astype(str) + "/" + agreement(c, side).astype(int).astype(str)
    out: dict[str, np.ndarray | pd.DataFrame] = {
        k: df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close")
    }
    out["side"] = side.to_numpy()
    out["fund"] = np.nan_to_num(fund.to_numpy(dtype=float))
    out["bucket"] = bucket.to_numpy()
    out["entries"] = confidence(c, side, bucket)
    for b in (4.0, 3.0, 2.0):
        out[f"lev{b:.0f}"] = floored(assessed_leverage(move, b, VENUE)).to_numpy()
    return out


def conf_at(entries: list[pd.DataFrame], bucket: str, i: int) -> float:
    """Share of trades in ``bucket`` closed before bar ``i`` that made money (NaN if few)."""
    won = n = 0
    for e in entries:
        done = e[(e["closed"] < i) & (e["bucket"] == bucket)]
        won += int(done["won"].sum())
        n += len(done)
    return won / n if n >= MIN_TRADES else float("nan")


def simulate(data: dict, index: pd.DatetimeIndex, a: int, variant: tuple) -> tuple[pd.Series, dict]:
    """Run one account from bar ``a``; return dollars per bar and counters."""
    base, limit, close_bad, boost, sized, stopped = variant
    entries = [d["entries"] for d in data.values()]
    pos: dict[str, dict] = {}
    pnl = np.zeros(len(index))
    equity = day_start = START_EQUITY
    halted, force_close, day = False, False, index[a].date()
    n = {"halt_days": 0, "boost_asks": 0, "liqs": 0, "stops": 0, "trades": 0, "skipped_cap": 0}
    wait: dict[str, object] = {}
    pcts: list[float] = []
    for i in range(a, len(index) - 1):
        if index[i].date() != day:
            day, day_start, halted, wait = index[i].date(), equity, False, {}
        bar = 0.0
        for coin, d in data.items():
            p, target = pos.get(coin), d["side"][i - 1]
            if p and (target != p["side"] or force_close):
                left = max(
                    p["coll"]
                    + p["side"] * p["size"] * (d["open"][i] / p["entry"] - 1)
                    - p["size"] * FEE
                    - p["paid"],
                    0.0,
                )
                bar += left - p["value"]
                del pos[coin]
                p = None
            lev = d[f"lev{base:.0f}"][i - 1]
            ok = p is None and target != 0 and not halted and coin not in wait and equity > 0
            if ok and np.isfinite(lev) and lev >= 1.0:
                conf = conf_at(entries, d["bucket"][i - 1], i - 1) if boost or sized else np.nan
                if boost and conf >= CONF:
                    n["boost_asks"] += 1
                    lev = d["lev2"][i - 1] if np.isfinite(d["lev2"][i - 1]) else lev
                pct = size_pct(conf) if sized else 0.10
                coll = pct * equity
                size = coll * lev
                if sum(q["size"] for q in pos.values()) + size > TOTAL_CAP * equity:
                    n["skipped_cap"] += 1
                else:
                    entry = d["open"][i]
                    dist = max(STOP_SHARE / lev - 2 * FEE, 0.0)
                    stop = entry * (1 - target * dist) if stopped else np.nan
                    pos[coin] = {
                        "side": target,
                        "size": size,
                        "entry": entry,
                        "paid": 0.0,
                        "coll": coll,
                        "value": coll - size * FEE,
                        "stop": stop,
                    }
                    pcts.append(pct)
                    bar -= 2 * size * FEE
                    n["trades"] += 1
        force_close = False
        for coin in list(pos):
            d, p = data[coin], pos[coin]
            p["paid"] += p["side"] * p["size"] * d["fund"][i]
            adverse = d["low"][i] if p["side"] > 0 else d["high"][i]
            worst = (
                p["coll"]
                + p["side"] * p["size"] * (adverse / p["entry"] - 1)
                - p["size"] * FEE
                - p["paid"]
            )
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
                    wait[coin] = True
                    del pos[coin]
                    continue
            if worst <= p["size"] * MAINT:
                bar -= p["value"]
                n["liqs"] += 1
                del pos[coin]
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
            force_close = close_bad
    n["avg_size_pct"] = round(float(np.mean(pcts)) * 100, 1) if pcts else 0.0
    return pd.Series(pnl[a:-1], index=index[a:-1]), n


def main() -> None:
    """Print the comparison and the recent 12-hour blocks."""
    frames = [load_csv(f"data/long/{c}_usd_4h.csv").index for c in COINS]
    index = frames[0]
    for f in frames[1:]:
        index = index.intersection(f)
    start = (index[0] + pd.Timedelta(days=200)).ceil("D")
    start += pd.Timedelta(days=(7 - start.day_of_week) % 7)
    a = int(index.searchsorted(start))
    data = {c: prepare(c, index) for c in COINS}
    print(f"One $2,500 account from {start.date()}; 12h blocks start 00:00/12:00 UTC.\n")
    bars, counts = {}, {}
    for name, v in VARIANTS.items():
        bars[name], counts[name] = simulate(data, index, a, v)
        print(f"  {name}: {counts[name]}")
    print(
        f"\n{'':<22}{'total $':>10}{'12h up':>8}{'med 12h':>8}{'best 12h':>9}{'worst 12h':>9}"
        f"{'wks up':>8}{'worst wk':>9}{'max drop':>10}{'liqs':>6}"
    )
    blocks = {n: s.resample("12h").sum() for n, s in bars.items()}
    weeks = {n: s.resample("W-MON", label="left", closed="left").sum() for n, s in bars.items()}
    recent = blocks["B3"].index[-1] - pd.Timedelta(weeks=RECENT_WEEKS)
    for n in bars:
        b, w = blocks[n], weeks[n]
        print(row(f"{n} all", b, w, counts[n]["liqs"], 0)[:-6])
        print(
            row(f"{n} last {RECENT_WEEKS} wks", b[b.index > recent], w[w.index > recent], 0, 0)[
                :-12
            ]
        )
    table = pd.DataFrame(blocks).round(0)
    table.index = [t.tz_convert(NY).strftime("%a %b %d %I%p ET") for t in table.index]
    print(f"\nrunning total over the last {SHOW_DAYS} days (12-hour blocks, New York time):")
    print(table.iloc[-SHOW_DAYS * 2 :].cumsum().to_string())
    print(f"\nwhole account, last {RECENT_WEEKS} weeks in 12-hour blocks:")
    print(table.iloc[-RECENT_WEEKS * 14 :].to_string())
    print("\nExploratory replay on past prices with test inputs; not a forecast.")


if __name__ == "__main__":
    main()
