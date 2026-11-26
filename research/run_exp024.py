"""EXP-2026-024: the pre-registered tables (plan: ``research/EXP-2026-024-plan.md``).

Fresh-data test of the EXP-2026-023 fixes (Part A), a top-20 account (Part B) and faster
trading (Part C). Every setting, slice and pass rule was fixed in the plan before the
candle files were read; this script only runs them.

Usage: python research/run_exp024.py <data_dir> <cache_dir> <job> [balance_multiple]
Jobs: A | B-F3 | B-F4 | B-dev | B-hold | C-F3 | C-F4 | C-dev | C-hold | live |
      X-<slice>  (exploratory, added after the owner chose the account; slices F3, F4,
      dev, hold for twenty coins and F2, F3-10, F4-10, dev10, hold10 for ten)
(one job per process, so several can run side by side; build the caches first with
``python research/exp024_lib.py <data_dir> <cache_dir> <tf> COIN...``).

``balance_multiple`` (default 100) multiplies the paper balance. Reason: the paper account
books borrow in whole cents at every accrual (``simulator.py``, ``fee.quantize(CENT)``).
A twenty-coin account on $2,500 holds positions of $75 to $500, whose borrow for four
hours is 0.5 to 3 cents and for one hour is under half a cent, so at $2,500 the 4h tables
book borrow up to 56% too high or 22% too low depending on the setting, and an hourly
account books none at all. At 100 times the balance the rounding is immaterial and
nothing else changes (no rule in the risk code has a fixed dollar amount). This was found
after the first Part A table and the first rows of Part B had been seen at $2,500; those
are kept in the results file. ``live`` always runs at the real balance.
"""

from __future__ import annotations

import dataclasses
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import exp023_lib as base
import exp024_lib as lib

from trader.perps.params import PerpsParams

D = Decimal
TOP20 = (
    "BTC ETH BNB XRP SOL TRX HYPE ZEC DOGE LINK ADA XLM BCH NEAR LTC AVAX UNI SUI HBAR TAO"
).split()
MAJORS_2021 = (
    "BTC ETH XRP LTC BCH BNB ADA DOT LINK XLM XMR EOS TRX XTZ THETA UNI ATOM VET NEO AAVE"
).split()
F1 = ["BTC", "ETH", "LTC"]
F2 = ["BTC", "ETH", "LTC", "BNB", "XRP", "ADA", "TRX", "XLM", "EOS", "NEO"]
F3 = [c for c in TOP20 if c not in ("BTC", "ETH", "SOL")]
F4 = [c for c in MAJORS_2021 if c not in ("BTC", "ETH")]
# Reason: the owner narrowed the account to the top ten on 2026-11-26, after the plan; both
# lists are in rank order, so the ten-coin versions are simply their first ten.
TOP10 = TOP20[:10]


def _day(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


# Reason: ends are exclusive; the files run to the 4h candle that opens 2026-11-24 20:00.
_SPAN = (_day(2020, 10, 1), _day(2026, 11, 25))
SLICES: dict[str, tuple[list[str], datetime, datetime]] = {
    "F1": (F1, _day(2018, 2, 1), _day(2020, 1, 1)),
    "F2": (F2, _day(2018, 8, 1), _day(2020, 1, 1)),
    "F3": (F3, _day(2020, 10, 1), _day(2026, 11, 25)),
    "F4": (F4, _day(2020, 10, 1), _day(2026, 11, 25)),
    "dev": (TOP20, _day(2020, 10, 1), _day(2024, 1, 1)),
    "hold": (TOP20, _day(2024, 1, 1), _day(2026, 11, 25)),
    "F3-10": ([c for c in TOP10 if c not in ("BTC", "ETH", "SOL")], *_SPAN),
    "F4-10": ([c for c in MAJORS_2021[:10] if c not in ("BTC", "ETH")], *_SPAN),
    "dev10": (TOP10, _day(2020, 10, 1), _day(2024, 1, 1)),
    "hold10": (TOP10, _day(2024, 1, 1), _day(2026, 11, 25)),
}
SCALE = [D(100)]  # balance multiple, set from the command line


def main_account() -> PerpsParams:
    """Main's live settings at ``SCALE`` times its paper balance."""
    live, _ = base.account("main")
    return dataclasses.replace(
        live, starting_collateral_usd=live.starting_collateral_usd * SCALE[0]
    )


HEAD = (
    f"{'CAGR':>7} {'Shrp':>5} {'DD':>4} {'wDay':>6} {'en/mo':>6} {'dec/mo':>6} "
    f"{'stop%':>5} {'fee/y':>5} | {'2x: CAGR':>8} {'Shrp':>5} {'DD':>4}"
)


def setting(
    live: PerpsParams, coll: str, buffer: int, positions: int, *, cap5: bool = False
) -> PerpsParams:
    """Main's settings with another collateral %, buffer, position count and leverage ceiling."""
    return dataclasses.replace(
        live,
        max_collateral_per_position_pct=D(coll),
        liquidation_buffer_daily_moves=D(buffer),
        max_open_positions=positions,
        target_leverage=D(5) if cap5 else live.target_leverage,
    )


def double_costs(p: PerpsParams) -> PerpsParams:
    """The same account with twice the fees and twice the borrow rate."""
    return dataclasses.replace(
        p,
        open_fee_bps=p.open_fee_bps * 2,
        close_fee_bps=p.close_fee_bps * 2,
        borrow_rate_pct_per_hour=p.borrow_rate_pct_per_hour * 2,
    )


def opening_stops(events: list[dict[str, Any]]) -> int:
    """Stops that fired before any take-profit, i.e. the full planned loss."""
    had_tp: dict[str, bool] = {}
    n = 0
    for e in events:
        if e["event"] == "OPENED":
            had_tp[e["market"]] = False
        elif e["event"] == "TAKE_PROFIT":
            had_tp[e["market"]] = True
        elif e["event"] == "CLOSED" and e["reason"] == "STOP_LOSS" and not had_tp.get(e["market"]):
            n += 1
    return n


def row(
    label: str,
    params: PerpsParams,
    feed: lib.Feed,
    name: str,
    *,
    group_cap: Decimal | None = None,
    signals: dict[str, lib.Series] | None = None,
) -> dict[str, float]:
    """Run one setting on one slice at 1x and 2x costs, print the line, return the 1x stats."""
    coins, start, end = SLICES[name]
    one = lib.run(params, feed, start, end, coins=coins, signals=signals, group_cap=group_cap)
    two = lib.run(
        double_costs(params), feed, start, end, coins=coins, signals=signals, group_cap=group_cap
    )
    s, t = one.stats, two.stats
    months = (end - start).days / 365.25 * 12
    stops = opening_stops(one.events) / max(s["trades"], 1) * 100
    print(
        f"{label:34} | {s['cagr']:6.1f}% {s['sharpe']:5.2f} {s['dd']:3.0f}% {s['worst_day']:5.1f}% "
        f"{s['trades_mo']:6.1f} {lib.clusters(one.events) / months:6.1f} {stops:4.0f}% "
        f"{s['fee_drag']:4.0f}% | {t['cagr']:7.1f}% {t['sharpe']:5.2f} {t['dd']:3.0f}%",
        flush=True,
    )
    return s


def part_a(data: Path, cache: Path) -> None:
    """Do the wider stop and the caps hold on 2018-2019?"""
    live = main_account()
    for name, coll, half, positions in (("F1", "10", "5", 3), ("F2", "3", "1.5", 10)):
        coins, start, end = SLICES[name]
        feed = lib.build_feed(data, "4h", coins, cache)
        print(f"\n== Part A, {name}: {' '.join(coins)}, {start:%Y-%m-%d} to {end:%Y-%m-%d}")
        print(f"{'setting':34} | {HEAD}")
        wide = setting(live, coll, 8, positions, cap5=True)
        got = {
            "LIVE": row(
                f"LIVE  (coll {coll}%, buffer 4)", setting(live, coll, 4, positions), feed, name
            ),
            "HALF": row(
                f"HALF  (coll {half}%, buffer 4)", setting(live, half, 4, positions), feed, name
            ),
            "WIDE": row(f"WIDE  (coll {coll}%, buffer 8, 5x)", wide, feed, name),
        }
        row(
            f"WIDE10 (coll {coll}%, buffer 10, 5x)",
            setting(live, coll, 10, positions, cap5=True),
            feed,
            name,
        )
        row("WIDE + same-side cap 6%", wide, feed, name, group_cap=D(6))
        row("WIDE + same-side cap 3%", wide, feed, name, group_cap=D(3))
        holds = (
            got["WIDE"]["dd"] < got["LIVE"]["dd"]
            and got["WIDE"]["sharpe"] >= got["LIVE"]["sharpe"] - 0.1
        )
        beats = got["WIDE"]["sharpe"] > got["HALF"]["sharpe"]
        print(f"rule: WIDE holds against LIVE: {holds}; WIDE beats HALF on Sharpe: {beats}")


def part_b(data: Path, cache: Path, name: str) -> None:
    """The top-20 account grid on one slice (4h decisions)."""
    live = main_account()
    coins, start, end = SLICES[name]
    feed = lib.build_feed(data, "4h", coins, cache)
    print(f"\n== Part B, {name}: {len(coins)} coins, {start:%Y-%m-%d} to {end:%Y-%m-%d}, 4h")
    print(f"{'setting':34} | {HEAD}")
    for coll in ("1", "1.5", "2.5"):
        for buffer in (4, 8):
            params = setting(live, coll, buffer, 20, cap5=buffer == 8)
            for cap in (None, D(6)):
                label = f"coll {coll}%, buffer {buffer}, cap {'none' if cap is None else '6%'}"
                row(label, params, feed, name, group_cap=cap)


def part_c(data: Path, cache: Path, name: str) -> None:
    """Three speeds at the central setting (collateral 1.5%, buffer 8, 5x, no cap)."""
    live = main_account()
    coins, start, end = SLICES[name]
    central = setting(live, "1.5", 8, 20, cap5=True)
    print(f"\n== Part C, {name}: {len(coins)} coins, {start:%Y-%m-%d} to {end:%Y-%m-%d}")
    print(f"{'speed':34} | {HEAD}")
    row("T1 4h decisions", central, lib.build_feed(data, "4h", coins, cache), name)
    hourly = lib.build_feed(data, "1h", coins, cache)
    row("T2 hourly decisions, 4h trend", central, hourly, name)
    row("T3 rule on hourly candles", central, hourly, name, signals=hourly.native_signals())


def chosen(data: Path, cache: Path, name: str) -> None:
    """Exploratory: the account the owner chose on 2026-11-26, on one slice.

    Not in the plan. The owner picked hourly decisions with the trend from 4h candles (T2)
    at collateral 1%, then narrowed the twenty coins to the top ten; Part C ran T2 on
    twenty coins at the central 1.5% only. Ten-coin slices also show 2% collateral, the
    size that puts the same share of the account at risk as 1% does on twenty coins.
    """
    live = main_account()
    coins, start, end = SLICES[name]
    positions = 20 if len(coins) > 10 else 10
    picked = setting(live, "1", 8, positions, cap5=True)
    print(f"\n== Chosen account, {name}: {' '.join(coins)}, {start:%Y-%m-%d} to {end:%Y-%m-%d}")
    print(f"{'buffer 8, 5x':34} | {HEAD}")
    row("4h decisions, coll 1% (reference)", picked, lib.build_feed(data, "4h", coins, cache), name)
    hourly = lib.build_feed(data, "1h", coins, cache)
    row("hourly decisions, coll 1%", picked, hourly, name)
    if positions == 10:
        row("hourly decisions, coll 2%", setting(live, "2", 8, 10, cap5=True), hourly, name)


def live_check(data: Path, cache: Path) -> None:
    """Replay main from the live start (2026-11-22) and print what it did."""
    live, _ = base.account("main")
    feed = lib.build_feed(data, "4h", list(base.COINS), cache)
    # Reason: live started at 22:53 UTC, inside the 20:00 candle; the first decision the
    # replay can take is at that candle's close, 2026-11-23 00:00.
    out = lib.run(live, feed, datetime(2026, 11, 22, 20, tzinfo=UTC), _day(2026, 11, 25))
    print("\n== main replayed from 2026-11-22 20:00 UTC (compare with the live journal)")
    for e in out.events:
        keep = {k: e[k] for k in ("at_utc", "event", "market", "side", "reason") if k in e}
        for k in ("leverage", "entry_price", "exit_price", "pnl_usd", "collateral_usd"):
            if k in e:
                keep[k] = e[k]
        print(keep)
    print("end equity", round(out.stats["end"], 2))


def main() -> None:
    """Run one job."""
    data, cache, job = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    if len(sys.argv) > 4:
        SCALE[0] = D(sys.argv[4])
    print(f"paper balance: {SCALE[0]} x the configured $2,500 (except the live check)")
    if job == "A":
        part_a(data, cache)
    elif job == "live":
        live_check(data, cache)
    elif job.startswith("B-"):
        part_b(data, cache, job[2:])
    elif job.startswith("C-"):
        part_c(data, cache, job[2:])
    elif job.startswith("X-"):
        chosen(data, cache, job[2:])
    else:
        raise SystemExit(f"unknown job {job!r}")


if __name__ == "__main__":
    main()
