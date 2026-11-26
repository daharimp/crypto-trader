"""EXP-2026-023 shared replay harness (research only): the live paper engine on history.

It drives the real paper account (``trader.perps.simulator.PaperPerpsAccount``) with the
live configs and the live signal over stored candles, with BTC, ETH and SOL in one
compounding account, in the same order of steps as ``trader.perps.session.cycle``:

1. bar *t* closes: accrue borrow, check stops and liquidations on the bar's adverse extreme
   (a bar that opens through a stop fills at the open), check take-profits on its
   favourable extreme, roll the UTC day (timestamps are the bar's close time);
2. read the signal from closes up to bar *t* (never later);
3. fill any change at the open of bar *t+1*.

An hourly account (degen) reads its signal and its typical daily move from completed 4h
candles plus the latest hourly close, like ``session._trend_view``.

Signals and daily moves do not depend on the account, so they are computed once per
timeframe and cached on disk; every variant then only replays the account.

Extra switches used by the experiment (all default off, so the default is the live bot):

* ``group_cap``: positions on one side count as one bet. The summed loss-at-stop of the
  open positions on a side may not pass this % of equity; coins opening together share the
  remaining room equally.
* ``gate``: an optional veto on new entries, ``gate(acct, market, side, bar_index) -> bool``.
* ``breakout_reentry``: after a stop, wait for a new 20-bar closing extreme in the trade's
  direction (or a signal change) before that coin may open on that side again.

Costs come from the config (7 bps a side, borrow 0.0016%/h). Funding is not modelled.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import pickle
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from trader.perps.backtest import sma_stance
from trader.perps.math import PerpSide, typical_daily_move
from trader.perps.params import PerpsParams, load_perps_params
from trader.perps.signals import make_signal
from trader.perps.simulator import PaperPerpsAccount

# Reason: the order the live session walks its markets (configs/perps), which decides who
# is refused first when a cap binds.
COINS = ("SOL", "ETH", "BTC")
LIVE_SIGNAL = "trend_50_200_range_10_30"
# Reason: SOL candles start 2020-08-11; the 200-bar average and the 30-day measures need
# about 34 days, so development starts on 2020-10-01 with every coin warmed up.
WINDOWS = {
    "dev": (datetime(2020, 10, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
    "hold": (datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 11, 22, tzinfo=UTC)),
}
STEP = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
TREND_STEP = timedelta(hours=4)
KEEP = 420  # closes handed to a signal: 200-bar average plus 181 for the 30-day efficiency
BREAKOUT_BARS = 20
LADDER = ((Decimal(4), Decimal(25)), (Decimal(8), Decimal(25)), (Decimal(12), Decimal(50)))
ACCOUNTS = {
    # name: (config file, execution timeframe); every account reads its trend from 4h candles
    "main": ("jupiter.yaml", "4h"),
    "degen": ("jupiter-degen.yaml", "1h"),
    "spot-perps": ("jupiter-spot-perps.yaml", "4h"),
}
SignalFn = Callable[[list[Decimal]], PerpSide | None]
Row = tuple[datetime, Decimal, Decimal, Decimal, Decimal]  # open time, open, high, low, close
Gate = Callable[[PaperPerpsAccount, str, PerpSide, int], bool]


def load(data: Path, coin: str, tf: str) -> list[Row]:
    """Read ``<coin>_<tf>.csv`` (ts_utc,open,high,low,close,volume), ascending."""
    rows: list[Row] = []
    with open(data / f"{coin.lower()}_{tf}.csv", encoding="utf-8") as f:
        next(f)
        for line in f:
            ts, o, h, lo, c, *_ = line.strip().split(",")
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            rows.append((t, Decimal(o), Decimal(h), Decimal(lo), Decimal(c)))
    return rows


def live_signal() -> SignalFn:
    """The deployed signal (ADR-044)."""
    return make_signal(LIVE_SIGNAL, 6)


def plain_50_200() -> SignalFn:
    """The 50/200 averages alone, without the switch to 10/30 while ranging."""
    return lambda closes: sma_stance(closes, 50, 200)


@dataclass
class Feed:
    """Candles of one execution timeframe plus cached signals and daily moves."""

    tf: str
    times: list[datetime]
    rows: dict[str, dict[datetime, Row]]
    trend: dict[str, list[Row]] | None  # 4h candles when the execution timeframe is 1h
    cache_dir: Path | None = None
    _mem: dict[str, Any] = field(default_factory=dict)

    def views(self, m: str) -> list[tuple[list[Decimal], list[Decimal]]]:
        """Per bar: (closes the signal sees, closes the daily move is measured on)."""
        out: list[tuple[list[Decimal], list[Decimal]]] = []
        if self.trend is None:
            hist: list[Decimal] = []
            for t in self.times:
                hist.append(self.rows[m][t][4])
                view = hist[-KEEP:]
                out.append((view, view))
            return out
        candles = self.trend[m]
        opens = [r[0] for r in candles]
        for t in self.times:
            decided = t + STEP[self.tf]
            # Reason: session._trend_view uses candles with open + 4h <= the decision time.
            i = bisect.bisect_right(opens, decided - TREND_STEP) - 1
            done = [r[4] for r in candles[max(0, i - KEEP + 1) : i + 1]] if i >= 0 else []
            at_boundary = bool(done) and candles[i][0] + TREND_STEP == decided
            closes = done if at_boundary else [*done, self.rows[m][t][4]]
            out.append((closes, done))
        return out

    def _cached(self, name: str, build: Callable[[], Any]) -> Any:
        if name in self._mem:
            return self._mem[name]
        path = self.cache_dir / f"{self.tf}-{name}.pkl" if self.cache_dir else None
        if path is not None and path.exists():
            with open(path, "rb") as f:
                value = pickle.load(f)  # noqa: S301 - our own cache file
        else:
            value = build()
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{id(self)}.tmp")
                with open(tmp, "wb") as f:
                    pickle.dump(value, f)
                tmp.replace(path)
        self._mem[name] = value
        return value

    def signals(
        self, label: str = "live", factory: Callable[[], SignalFn] = live_signal
    ) -> dict[str, list[PerpSide | None]]:
        """
        Signal per coin per bar, aligned with ``times``.

        Args:
            label (str): Cache name; use a new one for every different signal.
            factory (Callable[[], SignalFn]): Called once per coin, so a signal may keep
                state between bars (bars arrive in time order).

        Returns:
            dict[str, list[PerpSide | None]]: Target side per coin per bar.
        """

        def build() -> dict[str, list[PerpSide | None]]:
            out = {}
            for m in COINS:
                fn = factory()
                out[m] = [fn(closes) for closes, _ in self.views(m)]
            return out

        return self._cached(f"sig-{label}", build)

    def moves(self) -> dict[str, list[Decimal | None]]:
        """Typical daily move per coin per bar (ADR-032), aligned with ``times``."""

        def build() -> dict[str, list[Decimal | None]]:
            return {m: [typical_daily_move(mc[-200:], 6) for _, mc in self.views(m)] for m in COINS}

        return self._cached("moves", build)


def build_feed(data: Path, tf: str, cache_dir: Path | None = None) -> Feed:
    """Load every coin's candles for an execution timeframe."""
    bars = {m: load(data, m, tf) for m in COINS}
    rows = {m: {r[0]: r for r in bars[m]} for m in COINS}
    times = sorted(set.intersection(*(set(d) for d in rows.values())))
    trend = None if tf == "4h" else {m: load(data, m, "4h") for m in COINS}
    return Feed(tf, times, rows, trend, cache_dir)


@dataclass
class Result:
    """One replay: summary numbers, the account's events, and equity at each UTC day end."""

    stats: dict[str, float]
    events: list[dict[str, Any]]
    daily_equity: dict[date, float]


def _open_risk_pct(acct: PaperPerpsAccount, side: PerpSide, equity: Decimal) -> Decimal:
    """Summed loss-at-stop of the open positions on ``side``, % of equity."""
    share = acct.params.stop_loss_pct_of_collateral or Decimal(100)
    total = Decimal(0)
    for p in acct.positions.values():
        # Reason: once a take-profit moved the stop to breakeven or better, nothing is at risk.
        if p.side == side and p.moved_stop is None:
            total += p.collateral_usd * share / 100
    return total / equity * 100 if equity > 0 else Decimal(0)


def run(
    params: PerpsParams,
    feed: Feed,
    start: datetime,
    end: datetime,
    *,
    signals: dict[str, list[PerpSide | None]] | None = None,
    group_cap: Decimal | None = None,
    gate: Gate | None = None,
    breakout_reentry: bool = False,
) -> Result:
    """
    Replay one account over ``[start, end)``.

    Args:
        params (PerpsParams): Account settings (the live file, or a changed copy).
        feed (Feed): Candles and caches for the account's execution timeframe.
        start (datetime): First bar (the account starts flat with its starting balance).
        end (datetime): Bars opening at or after this are not used.
        signals: Output of ``feed.signals(...)``; the live signal when omitted.
        group_cap (Decimal | None): Same-side open risk cap, % of equity.
        gate (Gate | None): Veto for new entries.
        breakout_reentry (bool): Wait for a breakout before re-entering after a stop.

    Returns:
        Result: Stats, events and daily equity.
    """
    sig = signals if signals is not None else feed.signals()
    mov = feed.moves()
    step = STEP[feed.tf]
    times = feed.times
    j0 = bisect.bisect_left(times, start)
    j1 = bisect.bisect_left(times, end)
    acct = PaperPerpsAccount.start(params, times[j0])
    stop_share = (params.stop_loss_pct_of_collateral or Decimal(100)) / 100
    blocked: dict[str, PerpSide] = {}
    daily: dict[date, float] = {}
    peak, max_dd = acct.cash_usd, Decimal(0)
    for j in range(j0, j1):
        t = times[j]
        closes_at = t + step
        row = {m: feed.rows[m][t] for m in COINS}
        closes = {m: r[4] for m, r in row.items()}
        if j > j0:
            n0 = len(acct.events)
            adverse = {
                m: (row[m][3] if p.side == PerpSide.LONG else row[m][2])
                for m, p in acct.positions.items()
            }
            favorable = {
                m: (row[m][2] if p.side == PerpSide.LONG else row[m][3])
                for m, p in acct.positions.items()
            }
            acct.mark(
                {**closes, **adverse},
                closes_at,
                opens={m: r[1] for m, r in row.items()},
                favorable=favorable,
                closes=closes,
            )
            if breakout_reentry:
                for e in acct.events[n0:]:
                    if e["event"] == "CLOSED" and e["reason"] == "STOP_LOSS":
                        blocked[e["market"]] = PerpSide(e["side"])
        has_next = j + 1 < len(times) and times[j + 1] == closes_at
        marks = closes
        if has_next:
            fills = {m: feed.rows[m][closes_at][1] for m in COINS}
            marks = fills
            wanted: dict[PerpSide, list[str]] = {PerpSide.LONG: [], PerpSide.SHORT: []}
            for m in COINS:
                move = mov[m][j]
                if move is None:
                    acct.daily_moves.pop(m, None)
                else:
                    acct.daily_moves[m] = move
                target = sig[m][j]
                cur = acct.positions.get(m)
                if cur is not None and cur.side != target:
                    acct.close(m, fills, closes_at, reason="SIGNAL_CHANGED")
                if m in blocked:
                    look = [feed.rows[m][x][4] for x in times[max(j0, j - BREAKOUT_BARS) : j]]
                    side = blocked[m]
                    broke = bool(look) and (
                        closes[m] > max(look) if side == PerpSide.LONG else closes[m] < min(look)
                    )
                    if target != side or broke:
                        del blocked[m]
                if target is None or m in acct.positions or m in acct.stopped_today:
                    continue
                if blocked.get(m) == target:
                    continue
                if gate is not None and not gate(acct, m, target, j):
                    continue
                wanted[target].append(m)
            for side, markets in wanted.items():
                for k, m in enumerate(markets):
                    if group_cap is not None:
                        equity = acct.equity(fills)
                        room = group_cap - _open_risk_pct(acct, side, equity)
                        # Reason: coins opening together share the room equally.
                        pct = min(
                            params.max_collateral_per_position_pct,
                            max(room, Decimal(0)) / (len(markets) - k) / stop_share,
                        )
                        if pct < Decimal("0.5"):
                            continue
                        acct.params = dataclasses.replace(
                            params, max_collateral_per_position_pct=pct
                        )
                    acct.open(m, side, fills, closes_at)
                    acct.params = params
            acct.check_day_loss(fills, closes_at)
        equity = acct.equity(marks)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        # Reason: a bar closing at 00:00 belongs to the day that just ended.
        daily[(closes_at - timedelta(seconds=1)).date()] = float(equity)
    last = {m: feed.rows[m][times[j1 - 1]][4] for m in COINS}
    for m in list(acct.positions):
        acct.close(m, last, times[j1 - 1] + step, reason="END_OF_REPLAY")
    daily[(times[j1 - 1] + step - timedelta(seconds=1)).date()] = float(acct.cash_usd)
    return Result(summarize(acct, daily, max_dd, start, end), acct.events, daily)


def summarize(
    acct: PaperPerpsAccount,
    daily: dict[date, float],
    max_dd: Decimal,
    start: datetime,
    end: datetime,
) -> dict[str, float]:
    """Return per year, Sharpe (daily, 365 days), drawdown, trade counts, fee drag."""
    eq = [v for _, v in sorted(daily.items())]
    s0 = float(acct.params.starting_collateral_usd)
    years = (end - start).days / 365.25
    end_eq = float(acct.cash_usd)
    cagr = (end_eq / s0) ** (1 / years) - 1 if end_eq > 0 else -1.0
    rets = [b / a - 1 for a, b in zip([s0, *eq], eq, strict=False) if a > 0]
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
    ev = acct.events
    opens = sum(1 for e in ev if e["event"] == "OPENED")
    closed = [e for e in ev if e["event"] == "CLOSED"]
    stops = sum(1 for e in closed if e["reason"] == "STOP_LOSS")
    return {
        "cagr": cagr * 100,
        "sharpe": mu / sd * math.sqrt(365) if sd > 0 else 0.0,
        "dd": float(max_dd),
        "end": end_eq,
        "trades": opens,
        "trades_mo": opens / (years * 12),
        "stop_share": stops / max(opens, 1) * 100,
        "flips": sum(1 for e in closed if e["reason"] == "SIGNAL_CHANGED"),
        "tp_fills": sum(1 for e in ev if e["event"] == "TAKE_PROFIT")
        + sum(1 for e in closed if e["reason"] == "TAKE_PROFIT_3"),
        "liq": sum(1 for e in ev if e["event"] == "LIQUIDATED"),
        "worst_day": min(rets) * 100,
        "fees": float(acct.fees_paid_usd),
        # fees paid per year as % of the average equity
        "fee_drag": float(acct.fees_paid_usd) / (sum(eq) / len(eq)) / years * 100,
    }


def account(name: str, configs: Path | None = None) -> tuple[PerpsParams, str]:
    """Live settings and execution timeframe of a paper account."""
    file, tf = ACCOUNTS[name]
    return load_perps_params(configs, file), tf


HEADER = f"{'CAGR':>7} {'Shrp':>5} {'DD':>4} {'tr/mo':>5} {'stop%':>5} {'fee/y':>5} {'wDay':>6}"


def cell(s: dict[str, float]) -> str:
    """One window's numbers for a results table."""
    return (
        f"{s['cagr']:6.1f}% {s['sharpe']:5.2f} {s['dd']:3.0f}% {s['trades_mo']:5.1f} "
        f"{s['stop_share']:4.0f}% {s['fee_drag']:4.0f}% {s['worst_day']:5.1f}%"
    )
