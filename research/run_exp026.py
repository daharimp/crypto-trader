"""EXP-2026-026: do confidence measures predict trade results, and does sizing by one beat
flat sizing? (plan: ``research/EXP-2026-026-plan.md``; harness: ``exp026_lib.py``)

Every measure, slice, range and rule was fixed in the plan before any score was computed;
this script only runs them and applies the rules. Two things the plan left open were decided
here, also before any score was computed:
- Step 1 on account A is judged on main as configured (10% of the account a position), the
  size the owner's amendment made the one that would run; the 2% account is printed beside
  it as a check.
- M4's direction is read on slice A1 at that size (top third's mean result against the
  bottom third's) and written to ``m4-direction.json``, so ``step1-A1`` must run before
  every other step-1 or step-2 job.

Usage: python research/run_exp026.py <data_dir> <cache_dir> <out_dir> <job> [configs_dir]
Jobs: prep | check | step1-<slice> | step2-<slice> | verdict
Slices: A1 A2 A3 (main's account, 4h decisions) and B1 B2 B3 B4 (the top-ten hourly
account on the four slices of EXP-2026-025). The balance is 100 times the configured $2,500.
"""

from __future__ import annotations

import dataclasses
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as base
import exp024_lib as lib
import exp026_lib as x
import numpy as np
import run_exp024 as r24
import run_exp025 as r25

from trader.perps.math import PerpSide
from trader.perps.params import PerpsParams

D = Decimal
SCALE = D(100)
Q = D("0.0001")


def _day(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


A_COINS = list(base.COINS)
# name: (account, coins in decision order, first bar, end (exclusive))
SLICES: dict[str, tuple[str, list[str], datetime, datetime]] = {
    "A1": ("A", A_COINS, _day(2020, 10, 1), _day(2024, 1, 1)),
    "A2": ("A", A_COINS, _day(2024, 1, 1), _day(2026, 11, 25)),
    "A3": ("A", *r24.SLICES["F1"]),
    "B1": ("B", *r25.SLICES["S1"]),
    "B2": ("B", *r25.SLICES["S2"]),
    "B3": ("B", *r25.SLICES["S3"]),
    "B4": ("B", *r25.SLICES["S4"]),
}
FRESH = ("A3", "B3", "B4")
# Flat collateral % of the account a position; the first one is the size that is judged.
SIZES = {"A": ("10", "2"), "B": ("1",)}
TF = {"A": "4h", "B": "1h"}
# Smallest and largest size as a multiple of the flat size.
RANGES = {"narrow": (D(2) / 3, D(4) / 3), "wide": (D(1) / 2, D(3) / 2)}


def account(kind: str, c: str, configs: Path | None) -> PerpsParams:
    """Account A (main as configured) or B (the top-ten hourly account) at flat size ``c``%."""
    live, _ = base.account("main", configs)
    live = dataclasses.replace(live, starting_collateral_usd=live.starting_collateral_usd * SCALE)
    if kind == "B":
        live = r24.setting(live, "1", 8, 10, cap5=True)
    return dataclasses.replace(live, max_collateral_per_position_pct=D(c))


def load(data: Path, cache: Path | None, name: str) -> tuple[lib.Feed, x.Scorer]:
    """The slice's candles and a scorer over them."""
    kind, coins, _, _ = SLICES[name]
    feed = lib.build_feed(data, TF[kind], coins, cache)
    return feed, x.Scorer(feed, tuple(coins), feed.signals(), x.features(feed, cache))


def direction(out: Path) -> int:
    """M4's direction as fixed on A1: +1 (far from the average is better) or -1."""
    saved = json.loads((out / "m4-direction.json").read_text(encoding="utf-8"))
    return int(saved["direction"])


def adj(value: Any, measure: str, sign: int) -> Any:
    """The score used for judging and sizing: M4 is turned over when its direction is -1."""
    return 1 - value if measure == "M4" and sign < 0 else value


def scored_entries(
    params: PerpsParams, feed: lib.Feed, sc: x.Scorer, name: str
) -> list[dict[str, Any]]:
    """Every entry of the flat account with its raw scores and its result in R."""
    _, coins, start, end = SLICES[name]
    result, entries = x.run(params, feed, start, end, coins=coins, scorer=sc)
    stop = params.stop_loss_pct_of_collateral
    if stop is None:
        raise SystemExit("the account has no stop, so a result in R is undefined")
    res = x.trade_results(result.events, stop / 100)
    rows = []
    for e in entries:
        r, how = res[(e.market, e.at_utc)]
        scores = {k: float(v) for k, v in e.scores.items()}
        rows.append({"m": e.market, "side": e.side, "at": e.at_utc, "r": r, "how": how, **scores})
    return rows


def table(rows: list[dict[str, Any]], sign: int) -> dict[str, dict[str, Any]]:
    """Per measure: the thirds, the top-minus-bottom gap in mean R and the rank correlation."""
    r = np.array([e["r"] for e in rows])
    out: dict[str, dict[str, Any]] = {}
    for k in x.MEASURES:
        s = np.array([adj(e[k], k, sign) for e in rows])
        groups, note = x.thirds(s, r)
        out[k] = {
            "thirds": groups,
            "note": note,
            "rho": x.spearman(s, r),
            "gap": groups[2][1] - groups[0][1],
        }
    return out


def step1(data: Path, cache: Path, out: Path, name: str, configs: Path | None) -> None:
    """Score every entry of the flat account on one slice and print the thirds."""
    kind, coins, start, end = SLICES[name]
    feed, sc = load(data, cache, name)
    out.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Any] = {}
    for c in SIZES[kind]:
        rows = scored_entries(account(kind, c, configs), feed, sc, name)
        if name == "A1" and c == SIZES[kind][0]:
            gap = table(rows, 1)["M4"]["gap"]
            fixed = {"direction": -1 if gap < 0 else 1, "raw_gap_on_A1": gap}
            (out / "m4-direction.json").write_text(json.dumps(fixed), encoding="utf-8")
        sign = direction(out)
        tab = table(rows, sign)
        wins = sum(e["r"] > 0 for e in rows) / len(rows) * 100
        print(
            f"\n== Step 1, {name}: {' '.join(coins)}, {start:%Y-%m-%d} to {end:%Y-%m-%d}, "
            f"{TF[kind]}, {c}% a position: {len(rows)} entries, mean result "
            f"{np.mean([e['r'] for e in rows]):+.3f}R, {wins:.0f}% winners"
        )
        print(
            f"{'measure':8} | {'bottom third':>20} | {'middle third':>20} | {'top third':>20} | "
            f"{'top-bottom':>10} | {'rank corr':>9} | note"
        )
        for k in x.MEASURES:
            t = tab[k]
            cells = " | ".join(
                f"{n:5d} {mean:+7.3f}R {win * 100:4.0f}%" for n, mean, win in t["thirds"]
            )
            turned = " (turned over)" if k == "M4" and sign < 0 else ""
            print(f"{k:8} | {cells} | {t['gap']:+9.3f}R | {t['rho']:+9.3f} | {t['note']}{turned}")
        saved[c] = {"rows": rows, "table": tab}
    (out / f"step1-{name}.json").write_text(json.dumps(saved), encoding="utf-8")


def pair(
    params: PerpsParams, feed: lib.Feed, sc: x.Scorer, name: str, sizer: x.Sizer
) -> dict[str, Any]:
    """One sized account and its flat twin at the sized account's average size."""
    _, coins, start, end = SLICES[name]
    sized, entries = x.run(params, feed, start, end, coins=coins, scorer=sc, sizer=sizer)
    avg = (sum((e.pct for e in entries), D(0)) / len(entries)).quantize(Q)
    flat = dataclasses.replace(params, max_collateral_per_position_pct=avg)
    twin, _ = x.run(flat, feed, start, end, coins=coins)
    s0 = float(params.starting_collateral_usd)
    lo, hi = x.sharpe_diff_interval(x.daily_returns(sized, s0), x.daily_returns(twin, s0))

    def cells(res: base.Result) -> dict[str, float]:
        s = res.stats
        keep = {k: s[k] for k in ("cagr", "sharpe", "dd", "worst_day")}
        return {**keep, "ret_dd": s["cagr"] / s["dd"] if s["dd"] > 0 else 0.0}

    return {
        "avg": float(avg),
        "sized": cells(sized),
        "twin": cells(twin),
        "d_sharpe": sized.stats["sharpe"] - twin.stats["sharpe"],
        "lo": lo,
        "hi": hi,
    }


def step2(data: Path, cache: Path, out: Path, name: str, configs: Path | None) -> None:
    """Size by each measure inside each range and compare with the flat twin."""
    kind, coins, start, end = SLICES[name]
    feed, sc = load(data, cache, name)
    sign = direction(out)
    saved: dict[str, Any] = {}
    for c in SIZES[kind]:
        params = account(kind, c, configs)
        print(
            f"\n== Step 2, {name}: {' '.join(coins)}, {start:%Y-%m-%d} to {end:%Y-%m-%d}, "
            f"{TF[kind]}, flat size {c}%: sized by a measure against a flat twin of the same "
            "average size"
        )
        print(
            f"{'measure range':15} | {'avg':>6} | {'sized: CAGR  Shrp   DD   wDay  R/DD':>36} | "
            f"{'twin: CAGR  Shrp   DD   wDay  R/DD':>36} | {'dShrp  [90% interval]':>22} | "
            f"{'2x costs: dShrp':>15}"
        )
        saved[c] = {}
        for k in x.MEASURES:
            saved[c][k] = {}
            for label, (lo_x, hi_x) in RANGES.items():
                low, high = D(c) * lo_x, D(c) * hi_x

                def sizer(
                    scores: x.Scores, k: str = k, low: Decimal = low, high: Decimal = high
                ) -> Decimal:
                    return (low + (high - low) * adj(scores[k], k, sign)).quantize(Q)

                one = pair(params, feed, sc, name, sizer)
                two = pair(r24.double_costs(params), feed, sc, name, sizer)
                saved[c][k][label] = {"1x": one, "2x": two}

                def show(v: dict[str, float]) -> str:
                    return (
                        f"{v['cagr']:10.1f}% {v['sharpe']:5.2f} {v['dd']:3.0f}% "
                        f"{v['worst_day']:5.1f}% {v['ret_dd']:5.2f}"
                    )

                print(
                    f"{k + ' ' + label:15} | {one['avg']:5.2f}% | {show(one['sized']):>36} | "
                    f"{show(one['twin']):>36} | {one['d_sharpe']:+6.2f} [{one['lo']:+5.2f}, "
                    f"{one['hi']:+5.2f}] | {two['d_sharpe']:+15.2f}",
                    flush=True,
                )
    (out / f"step2-{name}.json").write_text(json.dumps(saved), encoding="utf-8")


def verdict(out: Path) -> None:
    """Apply the plan's two rules to every measure."""
    sign = direction(out)
    names = list(SLICES)
    s1 = {n: json.loads((out / f"step1-{n}.json").read_text(encoding="utf-8")) for n in names}
    s2 = {n: json.loads((out / f"step2-{n}.json").read_text(encoding="utf-8")) for n in names}
    judged = {n: SIZES[SLICES[n][0]][0] for n in names}
    fresh = [names.index(n) for n in FRESH]
    print(f"M4's direction, fixed on A1: {'far is better' if sign > 0 else 'near is better'}")
    print("\n== Step 1: top third's mean result minus the bottom third's, in R, per slice")
    head = " ".join(f"{n:>7}" for n in names)
    print(f"{'measure':8} | {head} | higher fresh | pooled rank corr [90%] | informative")
    informative: dict[str, bool] = {}
    pooled: dict[str, float] = {}
    for k in x.MEASURES:
        gaps = [s1[n][judged[n]]["table"][k]["gap"] for n in names]
        rows = [e for n in names for e in s1[n][judged[n]]["rows"]]
        score = np.array([adj(e[k], k, sign) for e in rows])
        res = np.array([e["r"] for e in rows])
        weeks = [tuple(datetime.fromisoformat(e["at"]).isocalendar()[:2]) for e in rows]
        pooled[k] = x.spearman(score, res)
        lo, hi = x.week_interval(score, res, weeks)
        higher, fresh_higher = sum(g > 0 for g in gaps), sum(gaps[i] > 0 for i in fresh)
        informative[k] = higher >= 5 and fresh_higher >= 2
        cells = " ".join(f"{g:+7.3f}" for g in gaps)
        print(
            f"{k:8} | {cells} | {higher}/7    {fresh_higher}/3   | {pooled[k]:+6.3f} "
            f"[{lo:+.3f}, {hi:+.3f}] | {'yes' if informative[k] else 'no'}"
        )

    def diffs(k: str, label: str, size: dict[str, str]) -> list[float]:
        return [s2[n][size[n]][k][label]["1x"]["d_sharpe"] for n in names]

    def sgn(v: float) -> int:
        return (v > 0) - (v < 0)

    print("\n== Step 2: Sharpe of the sized account minus its flat twin's, wide range, per slice")
    print(f"{'measure':8} | {head} | higher fresh | narrow agrees | earns the range")
    earns: dict[str, bool] = {}
    for k in x.MEASURES:
        wide, narrow = diffs(k, "wide", judged), diffs(k, "narrow", judged)
        higher, fresh_higher = sum(d > 0 for d in wide), sum(wide[i] > 0 for i in fresh)
        agree = sum(sgn(a) == sgn(b) for a, b in zip(wide, narrow, strict=True))
        passes = higher >= 5 and fresh_higher >= 2 and agree >= 5
        earns[k] = informative[k] and passes
        cells = " ".join(f"{d:+7.3f}" for d in wide)
        why = "" if earns[k] or not passes else " (sizing passes, but not informative)"
        print(
            f"{k:8} | {cells} | {higher}/7    {fresh_higher}/3   | {agree}/7           | "
            f"{'yes' if earns[k] else 'no'}{why}"
        )
    small = {n: SIZES[SLICES[n][0]][-1] for n in names}
    print("\n== Size-free check: the same wide-range difference with account A at 2% a position")
    for k in x.MEASURES:
        cells = " ".join(f"{d:+7.3f}" for d in diffs(k, "wide", small))
        print(f"{k:8} | {cells} |")
    good = [k for k in x.MEASURES if earns[k]]
    if good:
        best = "MC" if "MC" in good else max(good, key=lambda k: pooled[k])
        print(f"\nmeasures that earn the range: {', '.join(good)}; recommended: {best}")
    else:
        print("\nno measure earns the range under the plan's rule")


def window_feed(feed: lib.Feed, lo: datetime, hi: datetime) -> lib.Feed:
    """A copy of ``feed`` holding only candles that open in ``[lo, hi)``, with no disk cache."""
    rows = {m: {t: r for t, r in feed.rows[m].items() if lo <= t < hi} for m in feed.coins}
    order = {m: sorted(rows[m]) for m in feed.coins}
    times = sorted(set().union(*(set(v) for v in rows.values())))
    trend = None
    if feed.trend is not None:
        trend = {m: [r for r in feed.trend[m] if lo <= r[0] < hi] for m in feed.coins}
    return lib.Feed(feed.tf, feed.coins, times, rows, order, trend, None)


def changed(feed: lib.Feed, since: datetime, rng: random.Random) -> lib.Feed:
    """A copy of ``feed`` with every price changed in the candles that close after ``since``."""

    def bend(r: base.Row, width: timedelta) -> base.Row:
        if r[0] + width <= since:
            return r
        k = D(str(round(rng.uniform(0.5, 2.0), 4)))
        return (r[0], r[1] * k, r[2] * k, r[3] * k, r[4] * k)

    step = base.STEP[feed.tf]
    rows = {m: {t: bend(r, step) for t, r in feed.rows[m].items()} for m in feed.coins}
    trend = None
    if feed.trend is not None:
        trend = {m: [bend(r, base.TREND_STEP) for r in feed.trend[m]] for m in feed.coins}
    return lib.Feed(feed.tf, feed.coins, feed.times, rows, feed.order, trend, None)


def tamper(data: Path, kind: str, coins: list[str]) -> None:
    """Show that no score moves when candles a decision cannot see are changed."""
    rng = random.Random(26)
    full = lib.build_feed(data, TF[kind], coins, None)
    step = base.STEP[full.tf]
    same = moved = asked = 0
    for _ in range(3):
        cut = full.times[rng.randrange(len(full.times) // 2, len(full.times) - 24 * 30)]
        clean = window_feed(full, cut - timedelta(days=430), cut + timedelta(days=10))
        # Reason: the control also changes the last 60 days a decision may read, which must
        # move the scores, or the test could not fail.
        feeds = (clean, changed(clean, cut, rng), changed(clean, cut - timedelta(days=60), rng))
        scorers = [x.Scorer(f, tuple(coins), f.signals(), x.features(f)) for f in feeds]
        for t in [t for t in clean.times if t + step <= cut][-48:]:
            for m in coins:
                if t not in clean.rows[m]:
                    continue
                for side in (PerpSide.LONG, PerpSide.SHORT):
                    want, future, control = (s.at(m, side, t, t + step) for s in scorers)
                    asked += 1
                    same += future == want
                    moved += control != want
    print(
        f"score look-ahead test, {TF[kind]}: {same}/{asked} score sets unchanged when unseen "
        f"candles change; control (also the last 60 days seen): {moved}/{asked} moved"
    )
    if same != asked or moved == 0:
        raise SystemExit("score look-ahead test FAILED")


def check(data: Path, cache: Path, configs: Path | None) -> None:
    """The loop equals ``exp024_lib.run`` unless a sizer changes a size; scores see no future."""
    for name in ("A1", "B1"):
        kind, coins, start, end = SLICES[name]
        params = account(kind, SIZES[kind][0], configs)
        feed, sc = load(data, cache, name)
        old = lib.run(params, feed, start, end, coins=coins)
        plain, _ = x.run(params, feed, start, end, coins=coins)
        scored, entries = x.run(params, feed, start, end, coins=coins, scorer=sc)
        flat = params.max_collateral_per_position_pct
        const, _ = x.run(
            params, feed, start, end, coins=coins, scorer=sc, sizer=lambda _, flat=flat: flat
        )
        same = all(
            r.events == old.events and r.daily_equity == old.daily_equity
            for r in (plain, scored, const)
        )
        opened = [e for e in old.events if e["event"] == "OPENED"]
        in_range = all(0 <= v <= 1 for e in entries for v in e.scores.values())
        half, _ = x.run(
            params, feed, start, end, coins=coins, scorer=sc, sizer=lambda _, flat=flat: flat / 2
        )
        first = next(e for e in half.events if e["event"] == "OPENED")
        ratio = D(first["collateral_usd"]) / D(opened[0]["collateral_usd"])
        print(
            f"equivalence on {name}: plain, scored and constant-size runs against "
            f"exp024_lib.run: {len(old.events)} events, {'identical' if same else 'DIFFERENT'}; "
            f"{len(entries)} entries scored for {len(opened)} opens; scores inside 0..1: "
            f"{in_range}; a half-size sizer posts {ratio:.4f} of the first collateral"
        )
        if not same or len(entries) != len(opened) or not in_range or abs(ratio - D("0.5")) > Q:
            raise SystemExit("check FAILED")
        scored_entries(params, feed, sc, name)  # every entry must find its result
    tamper(data, "A", A_COINS)
    tamper(data, "B", ["BTC", "ETH", "XRP"])


def main() -> None:
    """Run one job."""
    data, cache, out, job = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    configs = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    kind, _, name = job.partition("-")
    if job == "prep":
        for each in SLICES:
            feed, _ = load(data, cache, each)
            feed.moves()
            print(f"prepared {each}", flush=True)
    elif job == "check":
        check(data, cache, configs)
    elif kind == "step1" and name in SLICES:
        step1(data, cache, out, name, configs)
    elif kind == "step2" and name in SLICES:
        step2(data, cache, out, name, configs)
    elif job == "verdict":
        verdict(out)
    else:
        raise SystemExit(f"unknown job {job!r}")


if __name__ == "__main__":
    main()
