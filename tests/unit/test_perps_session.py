"""Forward paper perps session (ADR-031): offline, fake candles, fixture parameters."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import SHIPPED_CONFIGS
from tests.perps_support import fixture_params
from trader.cli.main import app
from trader.perps.math import PerpSide
from trader.perps.session import (
    PerpsSession,
    SessionStateError,
    default_signal,
    describe,
    read_status,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
H4 = timedelta(hours=4)


def _rows(closes: list[float], wick: float = 0.002) -> list[list[float]]:
    """Kraken-style rows; the last close is the still-forming candle's latest price."""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        ms = int((T0 + i * H4).timestamp() * 1000)
        out.append([ms, prev, max(prev, c) * (1 + wick), min(prev, c) * (1 - wick), c, 1.0])
        prev = c
    return out


class Feed:
    """Candles per symbol that tests extend bar by bar."""

    def __init__(self, closes: list[float]) -> None:
        self.closes = list(closes)
        self.rows: list[list[float]] | None = None

    def __call__(self, symbol: str, timeframe: str) -> list[list[float]]:
        return self.rows if self.rows is not None else _rows(self.closes)

    def now(self) -> datetime:
        # Two minutes into the forming candle.
        return T0 + (len(self.closes) - 1) * H4 + timedelta(minutes=2)


def _session(tmp_path: Path, feed: Feed, **kw: object) -> tuple[PerpsSession, list[str]]:
    sent: list[str] = []
    s = PerpsSession(
        fixture_params(),
        feed,
        tmp_path / "state" / "perps-paper.json",
        tmp_path / "logs" / "events.jsonl",
        notify=sent.append,
        **kw,  # type: ignore[arg-type]
    )
    return s, sent


DOWN = [100 * 0.99**i for i in range(61)]  # 60 completed falling bars + the forming one


def test_downtrend_opens_shorts_at_the_latest_price_and_saves_state(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, sent = _session(tmp_path, feed)
    events = s.cycle(feed.now())
    assert [e["event"] for e in events] == ["ACCOUNT_STARTED", "OPENED", "OPENED"]
    assert s.acct is not None and set(s.acct.positions) == {"SOL", "ETH"}
    pos = s.acct.positions["SOL"]
    assert pos.side == PerpSide.SHORT
    assert pos.entry_price == Decimal(str(DOWN[-1]))  # the forming candle's latest price
    assert pos.size_usd == pos.collateral_usd * 3  # fixture target leverage
    assert len(sent) == 2 and sent[0].startswith("opened short SOL")
    status = read_status(s.state_path)
    assert status is not None and len(status["positions"]) == 2 and status["cycles"] == 1
    assert len((tmp_path / "logs" / "events.jsonl").read_text().splitlines()) == 3


def test_no_new_bar_is_a_no_op_and_due_waits_for_the_next_close(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, sent = _session(tmp_path, feed)
    assert s.due(feed.now())  # first run
    s.cycle(feed.now())
    before = s.state_path.read_text()
    assert s.cycle(feed.now() + timedelta(minutes=5)) == []
    assert s.state_path.read_text() == before and len(sent) == 2
    next_close = T0 + (len(DOWN) - 1) * H4 + H4
    assert not s.due(next_close + timedelta(seconds=30))
    assert s.due(next_close + timedelta(seconds=91))


def test_warm_up_starts_the_account_without_trading(tmp_path: Path) -> None:
    feed = Feed(DOWN[:30])
    s, sent = _session(tmp_path, feed)
    assert [e["event"] for e in s.cycle(feed.now())] == ["ACCOUNT_STARTED"]
    assert s.acct is not None and not s.acct.positions and sent == []


def test_restart_resumes_the_same_account_and_accrues_borrow(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, _ = _session(tmp_path, feed)
    s.cycle(feed.now())
    assert s.acct is not None
    cash = s.acct.cash_usd
    feed.closes.append(feed.closes[-1] * 0.99)
    again, _ = _session(tmp_path, feed)
    assert again.acct is not None and again.acct.cash_usd == cash
    assert again.acct.positions["SOL"].entry_price == s.acct.positions["SOL"].entry_price
    again.cycle(feed.now())
    assert again.acct.positions["SOL"].borrow_fees_usd > 0
    assert again.meta["cycles"] == 2


def test_trend_flip_closes_the_short_and_opens_a_long_at_the_next_open(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, sent = _session(tmp_path, feed)
    s.cycle(feed.now())
    # Rally until the signal flips, then two more bars; all processed in one catch-up cycle.
    closes = [Decimal(str(c)) for c in feed.closes[:-1]]
    while default_signal(closes) != PerpSide.LONG:
        feed.closes.append(feed.closes[-1] * 1.02)
        closes = [Decimal(str(c)) for c in feed.closes[:-1]]
    flip_bar = len(feed.closes) - 2  # index of the completed bar whose close flipped it
    feed.closes += [feed.closes[-1] * 1.01, feed.closes[-1] * 1.02]
    events = s.cycle(feed.now())
    kinds = [(e["event"], e.get("market"), e.get("side")) for e in events]
    assert ("CLOSED", "SOL", "short") in kinds and ("OPENED", "SOL", "long") in kinds
    assert s.acct is not None
    # Filled at the open of the bar after the flip (the flip bar's close in this feed).
    assert s.acct.positions["SOL"].entry_price == Decimal(str(feed.closes[flip_bar]))
    assert s.acct.positions["SOL"].side == PerpSide.LONG
    assert any(m.startswith("closed short") for m in sent)


def test_spike_through_the_liquidation_price_loses_the_collateral(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, sent = _session(tmp_path, feed)
    s.cycle(feed.now())
    assert s.acct is not None
    collateral = s.acct.positions["SOL"].collateral_usd
    rows = _rows([*feed.closes, feed.closes[-1]])
    rows[-2][2] = feed.closes[-1] * 2  # the newly completed bar's high doubles
    feed.closes.append(feed.closes[-1])
    feed.rows = rows
    events = s.cycle(feed.now())
    liq = [e for e in events if e["event"] == "LIQUIDATED"]
    assert {e["market"] for e in liq} == {"SOL", "ETH"}
    assert Decimal(liq[0]["collateral_lost_usd"]) == collateral
    assert any(m.startswith("LIQUIDATED short") for m in sent)


def test_kill_switch_blocks_new_positions(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, sent = _session(tmp_path, feed, halted=lambda: True)
    events = s.cycle(feed.now())
    rejected = [e for e in events if e["event"] == "OPEN_REJECTED"]
    assert len(rejected) == 2 and "PERP_KILL_SWITCH_ENGAGED" in rejected[0]["reasons"]
    assert s.acct is not None and not s.acct.positions and sent == []


def test_price_failure_raises_and_leaves_no_state(tmp_path: Path) -> None:
    def boom(symbol: str, timeframe: str) -> list[list[float]]:
        raise OSError("network down")

    s, _ = _session(tmp_path, boom)  # type: ignore[arg-type]
    with pytest.raises(OSError, match="network down"):
        s.cycle(T0)
    assert not s.state_path.exists()
    short, _ = _session(tmp_path, Feed([100.0]))
    with pytest.raises(ValueError, match="no completed candles"):
        short.cycle(T0)


def test_saved_state_must_match_the_configuration(tmp_path: Path) -> None:
    feed = Feed(DOWN)
    s, _ = _session(tmp_path, feed)
    s.cycle(feed.now())
    with pytest.raises(SessionStateError, match="different signal"):
        _session(tmp_path, feed, signal_name="other")
    s.state_path.write_text("{not json")
    with pytest.raises(SessionStateError, match="unreadable"):
        _session(tmp_path, feed)
    with pytest.raises(ValueError, match="timeframe"):
        _session(tmp_path / "x", feed, timeframe="5m")


def test_describe_is_plain_language() -> None:
    assert describe({"event": "DAY_ROLLED"}) == "DAY_ROLLED"
    text = describe(
        {
            "event": "CLOSED",
            "market": "BTC",
            "side": "long",
            "exit": "75000",
            "pnl_usd": "12.50",
            "fees_usd": "3.10",
        }
    )
    assert text == "closed long BTC at 75000: $12.50 before $3.10 fees"


def test_cli_status_and_one_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trader.ui.data as ui_data

    monkeypatch.setenv("TRADER_DATA_DIR", str(tmp_path))
    r = CliRunner().invoke(app, ["perps", "paper", "status"])
    assert r.exit_code == 0 and "no perps paper session" in r.output
    # Reason: the shipped config assesses leverage from 30 days of candles (181 closes).
    long_down = [100 * 0.995**i for i in range(200)]
    monkeypatch.setattr(ui_data, "kraken_public_ohlc", lambda symbol, tf: _rows(long_down))
    # The test fixture config leaves every perps value TBD: the session must fail closed.
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once"])
    assert r.exit_code == 3 and "PERPS_CONFIG_UNRESOLVED" in r.output
    assert not (tmp_path / "state" / "perps-paper.json").exists()
    monkeypatch.setenv("TRADER_CONFIGS_DIR", str(SHIPPED_CONFIGS))
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once"])
    assert r.exit_code == 0, r.output
    state = json.loads((tmp_path / "state" / "perps-paper.json").read_text())
    assert state["meta"]["markets"] == ["BTC", "ETH", "SOL"]
    r = CliRunner().invoke(app, ["perps", "paper", "status"])
    assert "perps paper (consensus_sma_tsmom, 4h)" in r.output and "short" in r.output
    assert "not guaranteed" in r.output
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--timeframe", "5m"])
    assert r.exit_code == 2
    # A saved session cannot silently continue under a different signal, and an unknown
    # signal name is refused.
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--signal", "tsmom_30d"])
    assert r.exit_code == 2 and "different signal" in r.output
    r = CliRunner().invoke(app, ["perps", "paper", "run", "--once", "--signal", "nope"])
    assert r.exit_code == 2 and "unknown signal" in r.output


def test_assessed_leverage_follows_each_markets_volatility(tmp_path: Path) -> None:
    # 200 falling bars with small alternating noise: enough history, and a downtrend.
    closes = [100 * 0.997**i * (1.004 if i % 2 else 0.996) for i in range(200)]
    feed = Feed(closes)
    sent: list[str] = []
    s = PerpsSession(
        fixture_params(liquidation_buffer_daily_moves="4", min_liquidation_distance_pct="5"),
        feed,
        tmp_path / "state.json",
        tmp_path / "events.jsonl",
        notify=sent.append,
    )
    opened = [e for e in s.cycle(feed.now()) if e["event"] == "OPENED"]
    assert len(opened) == 2
    lev = Decimal(opened[0]["leverage"])
    assert Decimal(1) <= lev <= Decimal(3)  # never above the fixture's target leverage
    assert f"at {lev}x" in sent[0]
    # With too little history the session refuses to open rather than guess.
    short = Feed(DOWN)
    s2 = PerpsSession(
        fixture_params(liquidation_buffer_daily_moves="4"),
        short,
        tmp_path / "s2.json",
        tmp_path / "e2.jsonl",
    )
    events = s2.cycle(short.now())
    assert {e["event"] for e in events} == {"ACCOUNT_STARTED", "OPEN_REJECTED"}
    assert events[-1]["reasons"] == ["PERP_VOLATILITY_UNAVAILABLE"]
