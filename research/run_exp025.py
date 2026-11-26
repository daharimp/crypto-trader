"""EXP-2026-025: the pre-registered add-on tables (plan: ``research/EXP-2026-025-plan.md``).

Three add-ons on the account the owner chose (top ten coins, hourly decisions): a cooldown
after a losing trade (CD), a stop guard (SG), correlation sizing (VC) and a time limit
(TL). Every setting, slice and rule was fixed in the plan before any add-on was run; this
script only runs them and applies the rule.

Usage: python research/run_exp025.py <data_dir> <cache_dir> <out_dir> <job> [configs_dir]
Jobs: check | S1 | S2 | S3 | S4 | verdict | combo-S1 | combo-S2 | combo-S3 | combo-S4 |
engine-S1 | engine-S2 | engine-S3 | engine-S4
``check`` first (the loop must equal ``exp024_lib.run`` with every switch off), then the
four slices (each writes ``<out_dir>/<slice>.json``), then ``verdict``, then the ``combo``
jobs if any setting helps. ``configs_dir`` (default: the repository's ``configs``) is the
folder holding ``perps/jupiter.yaml``. The balance is 100 times the configured $2,500, as
in ``run_exp024.py``.

``engine-<slice>`` was added after the verdict, with ADR-053: it shows that the cooldown
built into the paper account (``risk.cooldown_after_loss_hours``) takes exactly the trades
the research cooldown took, so the tables above describe the setting that can be switched
on.
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
import exp025_lib as x
import run_exp024 as r24
from exp025_lib import Addons

from trader.perps.params import PerpsParams

D = Decimal
SCALE = D(100)
S3_COINS = [c for c in r24.MAJORS_2021 if c not in r24.TOP10][:10]
SLICES: dict[str, tuple[list[str], datetime, datetime]] = {
    "S1": r24.SLICES["dev10"],
    "S2": r24.SLICES["hold10"],
    "S3": (S3_COINS, datetime(2020, 10, 1, tzinfo=UTC), datetime(2026, 11, 25, tzinfo=UTC)),
    "S4": r24.SLICES["F2"],
}
VARIANTS: dict[str, tuple[str, Addons]] = {
    "CD4": ("CD cooldown 4h", Addons(cooldown_hours=4)),
    "CD12": ("CD cooldown 12h (central)", Addons(cooldown_hours=12)),
    "CD24": ("CD cooldown 24h", Addons(cooldown_hours=24)),
    "SG277": ("SG 2 stops in 7d, pause 7d (central)", Addons(stop_guard=(2, 7, 7))),
    "SG273": ("SG 2 stops in 7d, pause 3d", Addons(stop_guard=(2, 7, 3))),
    "SG3147": ("SG 3 stops in 14d, pause 7d", Addons(stop_guard=(3, 14, 7))),
    "VCT": ("VC-tiers", Addons(corr_sizing="tiers")),
    "VCR": ("VC-root", Addons(corr_sizing="root")),
    "TL24": ("TL time limit 24h", Addons(time_limit_hours=24)),
    "TL72": ("TL time limit 72h (central)", Addons(time_limit_hours=72)),
    "TL168": ("TL time limit 168h", Addons(time_limit_hours=168)),
}
# Reason: the rule asks a setting's neighbours in its grid to agree; an edge setting has one
# neighbour (the central one), and the two correlation modes are each other's.
NEIGHBOURS = {
    "CD4": ["CD12"],
    "CD12": ["CD4", "CD24"],
    "CD24": ["CD12"],
    "SG277": ["SG273", "SG3147"],
    "SG273": ["SG277"],
    "SG3147": ["SG277"],
    "VCT": ["VCR"],
    "VCR": ["VCT"],
    "TL24": ["TL72"],
    "TL72": ["TL24", "TL168"],
    "TL168": ["TL72"],
}
GROUPS = {
    "CD": ["CD12", "CD4", "CD24"],
    "SG": ["SG277", "SG273", "SG3147"],
    "VC": ["VCT", "VCR"],
    "TL": ["TL72", "TL24", "TL168"],
}  # central first
HEAD = (
    f"{'CAGR':>7} {'Shrp':>5} {'DD':>4} {'wDay':>6} {'en/mo':>6} {'dec/mo':>6} {'stop%':>5} "
    f"{'fee/y':>5} {'acts/mo':>7} | {'dShrp  [90% interval]':>22} | {'2x: CAGR':>8} {'Shrp':>5} {'DD':>4}"
)
Stats = dict[str, float]


def baseline(configs: Path | None) -> PerpsParams:
    """B0: main's costs and limits at 100x balance, collateral 1%, buffer 8, 5x, ten coins."""
    live, _ = base.account("main", configs)
    live = dataclasses.replace(live, starting_collateral_usd=live.starting_collateral_usd * SCALE)
    return r24.setting(live, "1", 8, 10, cap5=True)


def sized(params: PerpsParams, multiplier: float) -> PerpsParams:
    """B0 at a fixed collateral of 1% times ``multiplier`` (the "same size" twin)."""
    pct = (params.max_collateral_per_position_pct * D(str(multiplier))).quantize(D("0.0001"))
    return dataclasses.replace(params, max_collateral_per_position_pct=pct)


def measure(
    label: str,
    params: PerpsParams,
    feed: lib.Feed,
    name: str,
    addons: Addons | None = None,
    *,
    corr: x.Corr | None = None,
    ref: list[float] | None = None,
    params_2x: PerpsParams | None = None,
) -> tuple[Stats, list[float]]:
    """Run one setting on one slice at 1x and 2x costs, print its line, return its numbers."""
    coins, start, end = SLICES[name]
    one = x.run(params, feed, start, end, coins=coins, addons=addons, corr=corr)
    costly = r24.double_costs(params_2x or params)
    two = x.run(costly, feed, start, end, coins=coins, addons=addons, corr=corr)
    s, t = one.result.stats, two.result.stats
    months = (end - start).days / 365.25 * 12
    rets = x.daily_returns(one.result, float(params.starting_collateral_usd))
    out: Stats = {
        "cagr": s["cagr"],
        "sharpe": s["sharpe"],
        "dd": s["dd"],
        "worst_day": s["worst_day"],
        "en_mo": s["trades_mo"],
        "dec_mo": lib.clusters(one.result.events) / months,
        "stop": r24.opening_stops(one.result.events) / max(s["trades"], 1) * 100,
        "fee": s["fee_drag"],
        "acts_mo": one.acts / months,
        "cagr2": t["cagr"],
        "sharpe2": t["sharpe"],
        "dd2": t["dd"],
    }
    if one.multipliers:
        out["mult"] = sum(one.multipliers) / len(one.multipliers)
        out["mult2"] = sum(two.multipliers) / len(two.multipliers)
    paired = "                      "
    if ref is not None:
        out["d_sharpe"], out["lo"], out["hi"] = x.sharpe_difference(rets, ref)
        paired = f"{out['d_sharpe']:+6.2f} [{out['lo']:+5.2f}, {out['hi']:+5.2f}]"
    print(
        f"{label:38} | {out['cagr']:6.1f}% {out['sharpe']:5.2f} {out['dd']:3.0f}% "
        f"{out['worst_day']:5.1f}% {out['en_mo']:6.1f} {out['dec_mo']:6.1f} {out['stop']:4.0f}% "
        f"{out['fee']:4.0f}% {out['acts_mo']:7.1f} | {paired:>22} | {out['cagr2']:7.1f}% "
        f"{out['sharpe2']:5.2f} {out['dd2']:3.0f}%",
        flush=True,
    )
    return out, rets


def slice_table(data: Path, cache: Path, out: Path, name: str, configs: Path | None) -> None:
    """Every planned row on one slice; the numbers are saved for the verdict."""
    coins, start, end = SLICES[name]
    params = baseline(configs)
    feed = lib.build_feed(data, "1h", coins, cache)
    corr = x.Corr(x.four_hour_candles(feed))
    print(f"\n== {name}: {' '.join(coins)}, {start:%Y-%m-%d} to {end:%Y-%m-%d}, hourly")
    print(f"{'setting':38} | {HEAD}")
    stats: dict[str, Stats] = {}
    stats["B0"], ref = measure("B0 the chosen account", params, feed, name)
    for key, (label, addons) in VARIANTS.items():
        stats[key], _ = measure(label, params, feed, name, addons, corr=corr, ref=ref)
        if addons.corr_sizing is not None:
            mult, mult2 = stats[key]["mult"], stats[key]["mult2"]
            twin = sized(params, mult)
            stats[f"{key}-same"], _ = measure(
                f"  same size: collateral {twin.max_collateral_per_position_pct}%",
                twin,
                feed,
                name,
                ref=ref,
                params_2x=sized(params, mult2),
            )
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")


def judge(stats: dict[str, dict[str, Stats]]) -> dict[str, dict[str, Any]]:
    """Apply the plan's rule to every setting. ``stats[slice][setting]`` holds the numbers."""
    names = list(SLICES)

    def diffs(key: str) -> list[float]:
        return [stats[s][key]["sharpe"] - stats[s]["B0"]["sharpe"] for s in names]

    def sign(v: float) -> int:
        return (v > 0) - (v < 0)

    out: dict[str, dict[str, Any]] = {}
    for key in VARIANTS:
        own = diffs(key)
        near = [diffs(nb) for nb in NEIGHBOURS[key]]
        # Reason: "agree in sign": on that slice every neighbour moves Sharpe the same way.
        agree = sum(all(sign(nb[i]) == sign(d) for nb in near) for i, d in enumerate(own))
        higher = sum(d > 0 for d in own)
        helps = higher >= 3 and min(own) >= -0.05 and agree >= 3
        harmless = not helps and all(abs(d) <= 0.05 for d in own)
        change = [stats[s][key]["en_mo"] / stats[s]["B0"]["en_mo"] - 1 for s in names]
        out[key] = {
            "diffs": own,
            "higher": higher,
            "agree": agree,
            "verdict": "helps" if helps else "does no harm" if harmless else "hurts",
            "entries_change": change,
        }
    return out


def load_stats(out: Path) -> dict[str, dict[str, Stats]]:
    """Read the four slice files written by the slice jobs."""
    return {s: json.loads((out / f"{s}.json").read_text(encoding="utf-8")) for s in SLICES}


def picked(found: dict[str, dict[str, Any]]) -> dict[str, str]:
    """One helping setting per add-on: the central one if it helps, else the best neighbour."""
    out: dict[str, str] = {}
    for group, keys in GROUPS.items():
        good = [k for k in keys if found[k]["verdict"] == "helps"]
        if good:
            # Reason: ``keys`` lists the central setting first; ties go to it.
            out[group] = max(good, key=lambda k: (k == keys[0], found[k]["higher"]))
    return out


def verdict(out: Path) -> None:
    """Print the rule's verdict for every setting and add-on."""
    stats = load_stats(out)
    found = judge(stats)
    print("\n== Verdicts under the plan's rule (Sharpe at modelled costs, setting minus B0)")
    print(f"{'setting':38} | {'S1':>7} {'S2':>7} {'S3':>7} {'S4':>7} | higher  agree | verdict")
    for key, (label, _) in VARIANTS.items():
        f = found[key]
        cells = " ".join(f"{d:+7.3f}" for d in f["diffs"])
        print(f"{label:38} | {cells} | {f['higher']}/4     {f['agree']}/4   | {f['verdict']}")
    print("\n== Entries a month against B0 (a setting that removes more than a quarter is flagged)")
    print(f"{'setting':38} | {'S1':>6} {'S2':>6} {'S3':>6} {'S4':>6} |")
    b0 = " ".join(f"{stats[s]['B0']['en_mo']:6.1f}" for s in SLICES)
    print(f"{'B0 the chosen account':38} | {b0} |")
    for key, (label, _) in VARIANTS.items():
        cells = " ".join(f"{stats[s][key]['en_mo']:6.1f}" for s in SLICES)
        change = found[key]["entries_change"]
        flag = "  FLAG: removes more than a quarter" if min(change) < -0.25 else ""
        print(
            f"{label:38} | {cells} | {min(change) * 100:+.0f}% to {max(change) * 100:+.0f}%{flag}"
        )
    print("\n== By add-on")
    for group, keys in GROUPS.items():
        text = ", ".join(f"{k} {found[k]['verdict']}" for k in keys)
        print(f"{group}: {text}")
    chosen = picked(found)
    print(f"settings that help (one per add-on, for the combination): {chosen or 'none'}")


def combo(data: Path, cache: Path, out: Path, name: str, configs: Path | None) -> None:
    """Run the settings that help together on one slice (once, as the plan fixes)."""
    chosen = picked(judge(load_stats(out)))
    if not chosen:
        print("no setting helps under the rule, so there is no combination to run")
        return
    merged: dict[str, Any] = {}
    for key in chosen.values():
        addons = VARIANTS[key][1]
        merged.update({k: v for k, v in dataclasses.asdict(addons).items() if v is not None})
    coins, start, end = SLICES[name]
    params = baseline(configs)
    feed = lib.build_feed(data, "1h", coins, cache)
    print(f"\n== Combination on {name}: {' + '.join(chosen.values())}")
    print(f"{'setting':38} | {HEAD}")
    _, ref = measure("B0 the chosen account", params, feed, name)
    measure("all settings that help", params, feed, name, Addons(**merged), ref=ref)


def audit(events: list[dict[str, Any]], addons: Addons) -> dict[str, int]:
    """Recount from the events alone how often an open broke an add-on's rule (must be 0)."""
    wait: dict[str, datetime] = {}
    net: dict[str, Decimal] = {}
    had_tp: dict[str, bool] = {}
    opened: dict[str, datetime] = {}
    stops: dict[str, list[datetime]] = {}
    bad = {"open while waiting": 0, "time limit too early or after a take-profit": 0}
    for e in events:
        kind, m = e["event"], e.get("market")
        at = datetime.fromisoformat(e["at_utc"])
        if kind == "OPENED":
            bad["open while waiting"] += m in wait and at < wait[m]
            net[m], had_tp[m], opened[m] = -D(e["fee_usd"]), False, at
        elif kind == "TAKE_PROFIT":
            net[m] += D(e["pnl_usd"]) - D(e["fees_usd"])
            had_tp[m] = True
        elif kind == "CLOSED":
            total = net.pop(m) + D(e["pnl_usd"]) - D(e["fees_usd"])
            if e["reason"] == "TIME_LIMIT":
                early = at - opened[m] < timedelta(hours=addons.time_limit_hours or 0)
                bad["time limit too early or after a take-profit"] += early or had_tp[m]
            if addons.cooldown_hours is not None and total < 0:
                wait[m] = max(wait.get(m, at), at + timedelta(hours=addons.cooldown_hours))
            if addons.stop_guard and e["reason"] == "STOP_LOSS" and not had_tp[m]:
                n, look, pause = addons.stop_guard
                stops[m] = [s for s in stops.get(m, []) if s > at - timedelta(days=look)] + [at]
                if len(stops[m]) >= n:
                    wait[m] = max(wait.get(m, at), at + timedelta(days=pause))
    return bad


def tamper(corr_rows: dict[str, list[base.Row]], coins: list[str], samples: int = 40) -> None:
    """Show a correlation does not move when candles the decision cannot see are changed."""
    rng = random.Random(25)
    clean = x.Corr(corr_rows)
    span = corr_rows[coins[0]]
    same = moved = used = 0
    for _ in range(samples):
        a, b = rng.sample(coins, 2)
        decided = span[rng.randrange(400, len(span) - 5)][0] + timedelta(hours=rng.randrange(1, 9))
        want = clean.at(a, b, decided)
        if want == 0.0:
            continue
        used += 1
        for leak, limit in ((False, decided), (True, decided - timedelta(hours=8))):
            # Reason: a candle is visible when it closed by the decision; the control also
            # changes the last two visible candles, which must move the answer.
            changed = {
                m: [
                    r
                    if r[0] + base.TREND_STEP <= limit
                    else (*r[:4], r[4] * D(rng.uniform(0.5, 2)))
                    for r in corr_rows[m]
                ]
                for m in (a, b)
            }
            got = x.Corr(changed).at(a, b, decided)
            if leak:
                moved += got != want
            else:
                same += got == want
    print(f"correlation look-ahead test: {same}/{used} unchanged when unseen candles change")
    print(f"control (also changing the last two candles it may read): {moved}/{used} moved")
    if same != used or moved == 0:
        raise SystemExit("correlation look-ahead test FAILED")


def check(data: Path, cache: Path, configs: Path | None) -> None:
    """The loop equals ``exp024_lib.run`` with every switch off; the add-ons obey their rules."""
    params = baseline(configs)
    for name in ("S1", "S3"):
        coins, start, end = SLICES[name]
        feed = lib.build_feed(data, "1h", coins, cache)
        old = lib.run(params, feed, start, end, coins=coins)
        new = x.run(params, feed, start, end, coins=coins).result
        same = old.events == new.events and old.daily_equity == new.daily_equity
        print(
            f"equivalence on {name}: exp025 with every switch off against exp024_lib.run: "
            f"{len(new.events)} events, {len(new.daily_equity)} days, "
            f"{'identical' if same else 'DIFFERENT'}"
        )
        if not same:
            raise SystemExit("equivalence check FAILED")
    coins, start, end = SLICES["S4"]
    feed = lib.build_feed(data, "1h", coins, cache)
    plain = x.run(params, feed, start, end, coins=coins).result.events
    for key in ("CD12", "SG277", "TL72"):
        addons = VARIANTS[key][1]
        got = x.run(params, feed, start, end, coins=coins, addons=addons)
        print(f"rule audit on S4, {key}: {audit(got.result.events, addons)} (acts {got.acts})")
        # Reason: the audit must be able to fail; the baseline's own events break the rule.
        print(f"  control, B0's events against {key}'s rule: {audit(plain, addons)}")
    tamper(x.four_hour_candles(feed), coins)


def engine(data: Path, cache: Path, name: str, configs: Path | None) -> None:
    """The account's own cooldown setting against the research cooldown, event for event."""
    coins, start, end = SLICES[name]
    params = baseline(configs)
    feed = lib.build_feed(data, "1h", coins, cache)
    for hours in (4, 12, 24):
        research = x.run(params, feed, start, end, coins=coins, addons=Addons(hours)).result
        native = dataclasses.replace(params, cooldown_after_loss_hours=D(hours))
        built = lib.run(native, feed, start, end, coins=coins)
        # Reason: the built setting also journals when each wait starts; the research
        # version kept that in its own book.
        events = [e for e in built.events if e["event"] != "COOLDOWN_STARTED"]
        waits = len(built.events) - len(events)
        same = events == research.events and built.daily_equity == research.daily_equity
        print(
            f"{name}, cooldown {hours}h: {len(events)} events, {waits} waits started, "
            f"built setting against research add-on: {'identical' if same else 'DIFFERENT'}"
        )
        if not same:
            raise SystemExit("the built cooldown does not match the research cooldown")


def main() -> None:
    """Run one job."""
    data, cache, out, job = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    configs = Path(sys.argv[5]) if len(sys.argv) > 5 else None
    if job == "check":
        check(data, cache, configs)
    elif job in SLICES:
        slice_table(data, cache, out, job, configs)
    elif job == "verdict":
        verdict(out)
    elif job.startswith("combo-") and job[6:] in SLICES:
        combo(data, cache, out, job[6:], configs)
    elif job.startswith("engine-") and job[7:] in SLICES:
        engine(data, cache, job[7:], configs)
    else:
        raise SystemExit(f"unknown job {job!r}")


if __name__ == "__main__":
    main()
