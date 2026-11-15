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
NOTIFY = {"OPENED", "CLOSED", "LIQUIDATED"}

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
        "positions": {
            m: {
                "side": p.side.value,
                "size_usd": str(p.size_usd),
                "collateral_usd": str(p.collateral_usd),
                "entry_price": str(p.entry_price),
                "opened_at": _iso(p.opened_at),
                "borrow_fees_usd": str(p.borrow_fees_usd),
                "last_accrual": _iso(p.last_accrual) if p.last_accrual else None,
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
    symbols: dict[str, str] = field(default_factory=dict)
    acct: PaperPerpsAccount | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the timeframe, default the symbols, and load any saved state."""
        if self.timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of {sorted(TIMEFRAMES)}")
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
            same = (meta["signal"], meta["timeframe"], meta["markets"]) == (
                self.signal_name,
                self.timeframe,
                sorted(self.params.markets),
            )
            if not same:
                raise SessionStateError(
                    "saved perps session used a different signal, timeframe, or market list; "
                    f"move {self.state_path} aside to start a new one"
                )
            self.acct, self.meta = _load_account(self.params, d["account"]), meta
        except (ValueError, KeyError, TypeError) as exc:
            raise SessionStateError(f"unreadable perps session state: {exc}") from exc

    def _save(self) -> None:
        assert self.acct is not None
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

    def _flush_events(self) -> list[dict[str, Any]]:
        assert self.acct is not None
        events, self.acct.events = self.acct.events, []
        if events:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as f:
                for e in events:
                    f.write(json.dumps(e, sort_keys=True) + "\n")
        return events

    # --- one cycle -----------------------------------------------------------------------
    def due(self, now: datetime) -> bool:
        """
        Whether a new bar should have closed since the last one processed.

        Args:
            now (datetime): Wall time (UTC).

        Returns:
            bool: True on the first run, or once the next bar has closed (plus 90 seconds
            for the exchange to publish it).
        """
        last = self.meta.get("last_bar")
        if last is None:
            return True
        closes_at = datetime.fromisoformat(last) + 2 * TIMEFRAMES[self.timeframe]
        return now >= closes_at + timedelta(seconds=90)

    def _bars(self) -> dict[str, list[Bar]]:
        out: dict[str, list[Bar]] = {}
        for market, symbol in self.symbols.items():
            rows = self.fetch(symbol, self.timeframe)
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

    def cycle(self, now: datetime) -> list[dict[str, Any]]:
        """
        Process every completed bar not yet seen and return the new account events.

        Args:
            now (datetime): Wall time (UTC).

        Returns:
            list[dict[str, Any]]: Events from this cycle (empty when no new bar closed).

        Raises:
            ValueError: If a market returns no completed candles.
        """
        bars = self._bars()
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
        for t in new:
            closes_at = t + step
            row = {m: by_time[m][t] for m in bars}
            if not first:
                adverse = {
                    m: (row[m].low if p.side == PerpSide.LONG else row[m].high)
                    for m, p in acct.positions.items()
                }
                acct.mark({**{m: b.close for m, b in row.items()}, **adverse}, closes_at)
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
                    if move is None:
                        acct.daily_moves.pop(m, None)
                    else:
                        acct.daily_moves[m] = move
                    acct.apply_signal(m, self.signal(closes), fills, now if newest else closes_at)
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
            self.meta["last_bar"] = _iso(t)
            self.meta["cycles"] += 1
            first = False
        if not new:
            return []
        self.meta["last_cycle_utc"] = _iso(now)
        events = self._flush_events()
        self._save()
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
