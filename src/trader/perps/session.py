"""Forward paper perps session: long in uptrends, short in downtrends, on live candles (ADR-031).

Paper only. Prices come from an injected public-candle fetcher; nothing here places an
order, holds a key, or talks to a venue. Each cycle processes every newly completed bar the
way the historical replay does:

1. mark open positions against the completed bar's adverse extreme (liquidation), accrue
   the hourly borrow fee, and roll the day;
2. read the signal from closes up to that bar;
3. move toward the signal at the next bar's open (for the newest bar: the latest price).

State is saved after every cycle, so a restart resumes the same account. Events are appended
to a JSON-lines file.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .backtest import Bar, sma_stance
from .math import PerpSide, typical_daily_move
from .params import PerpsParams
from .simulator import PaperPerpsAccount, PerpPosition

STATE_VERSION = 1
TIMEFRAMES = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
# Seconds the exchange gets to publish a bar after it closes, before the session reads it.
SETTLE_SECONDS = 90
NOTIFY = {"OPENED", "CLOSED", "LIQUIDATED", "DAY_HALTED", "TAKE_PROFIT"}

# (symbol, timeframe) -> [[open_time_ms, open, high, low, close, volume], ...] oldest first;
# the last row is the still-forming candle.
CandleFetcher = Callable[[str, str], list[list[float]]]
# Closes up to the decision bar -> long, short, or None (flat).
Signal = Callable[[list[Decimal]], PerpSide | None]


class SessionStateError(RuntimeError):
    """The saved state cannot be used (wrong version or a different configuration)."""


def default_signal(closes: list[Decimal]) -> PerpSide | None:
    """The replay's baseline: long while SMA 20 is above SMA 50, short while below."""
    return sma_stance(closes, 20, 50)


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def _dump_account(acct: PaperPerpsAccount) -> dict[str, Any]:
    return {
        "cash_usd": str(acct.cash_usd),
        "day_start_equity_usd": str(acct.day_start_equity_usd),
        "day": acct.day,
        "realized_pnl_usd": str(acct.realized_pnl_usd),
        "fees_paid_usd": str(acct.fees_paid_usd),
        "stopped_today": sorted(acct.stopped_today),
        "day_halted": acct.day_halted,
        "positions": {
            m: {
                "side": p.side.value,
                "size_usd": str(p.size_usd),
                "collateral_usd": str(p.collateral_usd),
                "entry_price": str(p.entry_price),
                "opened_at": _iso(p.opened_at),
                "borrow_fees_usd": str(p.borrow_fees_usd),
                "last_accrual": _iso(p.last_accrual) if p.last_accrual else None,
                "initial_stop": None if p.initial_stop is None else str(p.initial_stop),
                "tps_hit": p.tps_hit,
                "moved_stop": None if p.moved_stop is None else str(p.moved_stop),
            }
            for m, p in acct.positions.items()
        },
    }


def _load_account(params: PerpsParams, d: dict[str, Any]) -> PaperPerpsAccount:
    acct = PaperPerpsAccount(
        params, Decimal(d["cash_usd"]), Decimal(d["day_start_equity_usd"]), d["day"]
    )
    acct.realized_pnl_usd = Decimal(d["realized_pnl_usd"])
    acct.fees_paid_usd = Decimal(d["fees_paid_usd"])
    # Reason: state files written before ADR-038 have neither key.
    acct.stopped_today = set(d.get("stopped_today", []))
    acct.day_halted = bool(d.get("day_halted", False))
    for m, p in d["positions"].items():
        acct.positions[m] = PerpPosition(
            m,
            PerpSide(p["side"]),
            Decimal(p["size_usd"]),
            Decimal(p["collateral_usd"]),
            Decimal(p["entry_price"]),
            datetime.fromisoformat(p["opened_at"]),
            Decimal(p["borrow_fees_usd"]),
            datetime.fromisoformat(p["last_accrual"]) if p["last_accrual"] else None,
            # Reason: state written before ADR-045 has no ladder keys.
            None if p.get("initial_stop") is None else Decimal(p["initial_stop"]),
            int(p.get("tps_hit", 0)),
            None if p.get("moved_stop") is None else Decimal(p["moved_stop"]),
        )
    return acct


def describe(event: dict[str, Any]) -> str:
    """
    One plain-language line for an account event (used for phone alerts).

    Args:
        event (dict[str, Any]): An entry of ``PaperPerpsAccount.events``.

    Returns:
        str: Summary.
    """
    kind, m, side = event["event"], event.get("market"), event.get("side")
    if kind == "OPENED":
        return (
            f"opened {side} {m} at {event.get('leverage', '?')}x: ${event['size_usd']} position "
            f"on ${event['collateral_usd']} collateral at {event['entry']}; "
            f"liquidation near {event['liquidation_price']}"
        )
    if kind == "CLOSED":
        return (
            f"closed {side} {m} at {event['exit']}: "
            f"${event['pnl_usd']} before ${event['fees_usd']} fees"
        )
    if kind == "TAKE_PROFIT":
        return (
            f"take-profit {event['step']} on {side} {m} at {event['exit']}: closed "
            f"${event['closed_size_usd']} (${event['pnl_usd']} before ${event['fees_usd']} fees), "
            f"${event['remaining_size_usd']} still open; stop moved up"
        )
    if kind == "DAY_HALTED":
        return (
            f"BAD DAY: down ${event['loss_usd']} ({event['loss_pct']}%) since the start of the "
            f"UTC day, past the {event['limit_pct']}% limit. No new positions until 00:00 UTC; "
            "stop and analyze for the rest of the day"
        )
    if kind == "LIQUIDATED":
        return (
            f"LIQUIDATED {side} {m} at {event['mark']}: "
            f"lost ${event['collateral_lost_usd']} collateral"
        )
    return str(kind)


@dataclass
class PerpsSession:
    """One forward paper account driven by a signal on public candles."""

    params: PerpsParams
    fetch: CandleFetcher
    state_path: Path
    events_path: Path
    notify: Callable[[str], Any] = lambda text: None
    halted: Callable[[], bool] = lambda: False
    signal: Signal = default_signal
    signal_name: str = "sma_stance_20_50"
    timeframe: str = "4h"
    # Optional (ADR-040): read the signal and the volatility from completed candles of this
    # longer timeframe plus the latest price, while deciding, marking and stopping every
    # ``timeframe`` bar. Kraken's free feed holds 720 candles, one short of 30 days of 1h
    # bars, so an hourly sweep takes its 30-day trend from 4h candles.
    trend_timeframe: str | None = None
    symbols: dict[str, str] = field(default_factory=dict)
    acct: PaperPerpsAccount | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    # Optional (ADR-041): one JSON line per processed bar with the account's equity, so an
    # archived run keeps its full equity curve, not only the day-change points.
    equity_path: Path | None = None
    # Seconds to wait after a bar closes before reading it: the exchange needs a moment to
    # publish it, and an account that reads many markets waits longer so that its requests
    # do not land in the same second as the other accounts' (ADR-051).
    settle_seconds: int = SETTLE_SECONDS
    # Whether this session has a run on disk (loaded or saved); see ``_save``.
    _on_disk: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate the timeframe, default the symbols, and load any saved state."""
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {sorted(TIMEFRAMES)}")
        if self.trend_timeframe is not None and (
            self.trend_timeframe not in TIMEFRAMES
            or TIMEFRAMES[self.trend_timeframe] <= TIMEFRAMES[self.timeframe]
        ):
            raise ValueError("trend_timeframe must be a longer timeframe than timeframe")
        if not 0 <= self.settle_seconds < TIMEFRAMES[self.timeframe] / timedelta(seconds=1):
            raise ValueError("settle_seconds must be shorter than one bar")
        if not self.symbols:
            self.symbols = {m: f"{m}/USD" for m in self.params.markets}
        if self.state_path.exists():
            self._load()

    # --- persistence ---------------------------------------------------------------------
    def _load(self) -> None:
        try:
            d = json.loads(self.state_path.read_text(encoding="utf-8"))
            if d["state_version"] != STATE_VERSION:
                raise SessionStateError(f"state version {d['state_version']} is not supported")
            meta = d["meta"]
            same = (
                meta["signal"],
                meta["timeframe"],
                meta["markets"],
                meta.get("trend_timeframe"),
            ) == (
                self.signal_name,
                self.timeframe,
                sorted(self.params.markets),
                self.trend_timeframe,
            )
            if not same:
                raise SessionStateError(
                    "saved perps session used a different signal, timeframe, or market list; "
                    "archive it with `trader perps paper reset --reason ...` to start a new one"
                )
            self.acct, self.meta = _load_account(self.params, d["account"]), meta
            self._on_disk = True
        except (ValueError, KeyError, TypeError) as exc:
            raise SessionStateError(f"unreadable perps session state: {exc}") from exc

    def _guard_archived(self) -> None:
        if self._on_disk and not self.state_path.exists():
            # Reason: the run was archived (or moved aside) while this process still held it
            # in memory; writing it back, or appending its events to the new run's log,
            # would silently resurrect the old run (ADR-041).
            raise SessionStateError(
                f"{self.state_path} was archived or moved while the session ran; "
                "restart the account to begin the new run"
            )

    def _save(self) -> None:
        assert self.acct is not None
        self._guard_archived()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "state_version": STATE_VERSION,
            "meta": self.meta,
            "account": _dump_account(self.acct),
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        # Reason: replace is atomic, so a crash never leaves a half-written state file.
        os.replace(tmp, self.state_path)
        self._on_disk = True

    def _flush_events(self) -> list[dict[str, Any]]:
        assert self.acct is not None
        events, self.acct.events = self.acct.events, []
        if events:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e, sort_keys=True) + "\n")
        return events

    def _append_equity(self, points: list[dict[str, Any]]) -> None:
        if self.equity_path is None or not points:
            return
        self.equity_path.parent.mkdir(parents=True, exist_ok=True)
        with self.equity_path.open("a", encoding="utf-8") as f:
            for p in points:
                f.write(json.dumps(p, sort_keys=True) + "\n")

    # --- one cycle -----------------------------------------------------------------------
    def due(self, now: datetime) -> bool:
        """
        Whether a new bar should have closed since the last one processed.

        Args:
            now (datetime): Wall time (UTC).

        Returns:
            bool: True on the first run, or once the next bar has closed (plus
            ``settle_seconds``, 90 by default, for the exchange to publish it).
        """
        last = self.meta.get("last_bar")
        if last is None:
            return True
        closes_at = datetime.fromisoformat(last) + 2 * TIMEFRAMES[self.timeframe]
        return now >= closes_at + timedelta(seconds=self.settle_seconds)

    def _bars(self, timeframe: str | None = None) -> dict[str, list[Bar]]:
        out: dict[str, list[Bar]] = {}
        for market, symbol in self.symbols.items():
            rows = self.fetch(symbol, timeframe or self.timeframe)
            if len(rows) < 2:
                raise ValueError(f"{market}: no completed candles")
            out[market] = [
                Bar(
                    datetime.fromtimestamp(r[0] / 1000, tz=UTC),
                    *(Decimal(str(x)) for x in r[1:5]),
                )
                for r in rows
            ]
        return out

    def _trend_view(
        self, candles: list[Bar], decided_at: datetime, latest: Decimal
    ) -> tuple[list[Decimal], Decimal | None]:
        """
        Closes for the signal and the typical daily move, from the trend timeframe.

        Args:
            candles (list[Bar]): Trend-timeframe candles of one market (last one forming).
            decided_at (datetime): Close time of the decision bar.
            latest (Decimal): The decision bar's close.

        Returns:
            tuple[list[Decimal], Decimal | None]: Completed trend closes up to the decision,
            plus ``latest`` when the decision falls inside a trend candle; and the move.
        """
        assert self.trend_timeframe is not None
        span = TIMEFRAMES[self.trend_timeframe]
        done = [b for b in candles if b.open_time_utc + span <= decided_at]
        closes = [b.close for b in done]
        move = typical_daily_move(closes, round(timedelta(days=1) / span))
        # Reason: at a trend-candle boundary its close already is the latest price.
        if not done or done[-1].open_time_utc + span != decided_at:
            closes = [*closes, latest]
        return closes, move

    def cycle(self, now: datetime) -> list[dict[str, Any]]:
        """
        Process every completed bar not yet seen and return the new account events.

        Args:
            now (datetime): Wall time (UTC).

        Returns:
            list[dict[str, Any]]: Events from this cycle (empty when no new bar closed).

        Raises:
            ValueError: If a market returns no completed candles.
            SessionStateError: If the run was archived while this session held it (ADR-041).
        """
        self._guard_archived()
        bars = self._bars()
        trend = self._bars(self.trend_timeframe) if self.trend_timeframe else None
        step = TIMEFRAMES[self.timeframe]
        by_time = {m: {b.open_time_utc: b for b in bs} for m, bs in bars.items()}
        # Reason: the last row of each market is the forming candle, so it is not "completed".
        done = sorted(set.intersection(*(set(list(d)[:-1]) for d in by_time.values())))
        if not done:
            return []
        first = self.acct is None
        if self.acct is None:
            self.acct = PaperPerpsAccount.start(self.params, now)
            self.meta = {
                "signal": self.signal_name,
                "timeframe": self.timeframe,
                "trend_timeframe": self.trend_timeframe,
                "markets": sorted(self.params.markets),
                "config_version": self.params.version,
                "started_at": _iso(now),
                "start_equity_usd": str(self.acct.cash_usd),
                "peak_equity_usd": str(self.acct.cash_usd),
                "max_drawdown_pct": "0",
                "cycles": 0,
                "last_bar": None,
            }
            new = done[-1:]
        else:
            last = datetime.fromisoformat(self.meta["last_bar"])
            new = [t for t in done if t > last]
        acct = self.acct
        equity_points: list[dict[str, Any]] = []
        for t in new:
            closes_at = t + step
            row = {m: by_time[m][t] for m in bars}
            if not first:
                adverse = {
                    m: (row[m].low if p.side == PerpSide.LONG else row[m].high)
                    for m, p in acct.positions.items()
                }
                favorable = {
                    m: (row[m].high if p.side == PerpSide.LONG else row[m].low)
                    for m, p in acct.positions.items()
                }
                acct.mark(
                    {**{m: b.close for m, b in row.items()}, **adverse},
                    closes_at,
                    opens={m: b.open for m, b in row.items()},
                    favorable=favorable,
                    closes={m: b.close for m, b in row.items()},
                )
            newest = t == done[-1]
            # Reason: a decision at this bar's close fills at the next bar's open; for the
            # newest bar that next bar is still forming, so its latest price is the fill.
            fills = {
                m: (bars[m][-1].close if newest else by_time[m][closes_at].open)
                for m in bars
                if newest or closes_at in by_time[m]
            }
            if len(fills) == len(bars):
                acct.halted = self.halted()
                per_day = round(timedelta(days=1) / step)
                for m in bars:
                    closes = [b.close for b in bars[m] if b.open_time_utc <= t]
                    move = typical_daily_move(closes, per_day)
                    if trend is not None:
                        closes, move = self._trend_view(trend[m], closes_at, row[m].close)
                    if move is None:
                        acct.daily_moves.pop(m, None)
                    else:
                        acct.daily_moves[m] = move
                    acct.apply_signal(m, self.signal(closes), fills, now if newest else closes_at)
                acct.check_day_loss(fills, now if newest else closes_at)
                equity = acct.equity(fills)
                peak = max(Decimal(self.meta["peak_equity_usd"]), equity)
                drop = (peak - equity) / peak * 100 if peak > 0 else Decimal(0)
                self.meta.update(
                    equity_usd=str(equity.quantize(Decimal("0.01"))),
                    peak_equity_usd=str(peak),
                    max_drawdown_pct=str(
                        max(Decimal(self.meta["max_drawdown_pct"]), drop).quantize(Decimal("0.01"))
                    ),
                    marks={m: str(v) for m, v in fills.items()},
                )
                equity_points.append(
                    {
                        "at_utc": _iso(closes_at),
                        "equity_usd": self.meta["equity_usd"],
                        "peak_equity_usd": str(peak),
                    }
                )
            self.meta["last_bar"] = _iso(t)
            self.meta["cycles"] += 1
            first = False
        if not new:
            return []
        self.meta["last_cycle_utc"] = _iso(now)
        events = self._flush_events()
        self._save()
        self._append_equity(equity_points)
        for e in events:
            if e["event"] in NOTIFY:
                self.notify(describe(e))
        return events


def read_status(state_path: Path) -> dict[str, Any] | None:
    """
    Read-only summary of a saved session for the CLI and the dashboard.

    Args:
        state_path (Path): Session state file.

    Returns:
        dict[str, Any] | None: Summary, or None when no session has run.
    """
    if not state_path.exists():
        return None
    d = json.loads(state_path.read_text(encoding="utf-8"))
    meta, acct = d["meta"], d["account"]
    return {
        "signal": meta["signal"],
        "timeframe": meta["timeframe"],
        "trend_timeframe": meta.get("trend_timeframe"),
        "started_at": meta["started_at"],
        "last_bar": meta["last_bar"],
        "last_cycle_utc": meta.get("last_cycle_utc"),
        "cycles": meta["cycles"],
        "start_equity_usd": meta["start_equity_usd"],
        "equity_usd": meta.get("equity_usd", acct["cash_usd"]),
        "max_drawdown_pct": meta["max_drawdown_pct"],
        "fees_paid_usd": acct["fees_paid_usd"],
        "positions": [
            {
                "market": m,
                **{k: p[k] for k in ("side", "size_usd", "collateral_usd", "entry_price")},
            }
            for m, p in acct["positions"].items()
        ],
    }
