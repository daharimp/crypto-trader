"""Shared builders for forward-session tests (paper and live on a fake Kraken)."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from tests.conftest import SHIPPED_CONFIGS
from tests.fake_kraken import FakeKraken
from tests.helpers import series
from trader.common.clock import SimulatedClock
from trader.common.opstore import OperationalStore
from trader.domain.candles import Candle
from trader.domain.enums import Environment
from trader.profiles.compiler import compile_bundle
from trader.session.config import SessionConfig
from trader.session.factory import kraken_adapter_factory
from trader.session.market_data import KrakenMarketData
from trader.session.runner import SessionRunner

SYMBOLS = {f"{a}-USD": f"{a}/USD" for a in ("BTC", "ETH", "SOL", "XRP", "SUI")}
START = datetime(2026, 1, 1, tzinfo=UTC)
# Flat, dip, rally (SMA cross up -> entry), then a gap down (stop-out) and a long slide.
BTC_CLOSES = [100] * 300 + [90] * 10 + [130] * 12 + [60] * 30
FIRST_TICK_BAR = 290


def candles() -> tuple[dict[str, list[Candle]], dict[str, list[Candle]]]:
    """4h and daily candles keyed by ccxt symbol."""
    btc = series(BTC_CLOSES, start=START)
    eth = series([100] * len(BTC_CLOSES), start=START)
    day0 = START - timedelta(days=800)
    daily = {
        s: series([100] * 900, start=day0, tf="1d", volume="1000000") for s in SYMBOLS.values()
    }
    flat = {
        s: series([100] * len(BTC_CLOSES), start=START) for s in ("SOL/USD", "XRP/USD", "SUI/USD")
    }
    return {"BTC/USD": btc, "ETH/USD": eth, **flat}, daily


def configs(tmp: Path, cap: str | None = "500", cycles: int | None = 1, ack: bool = True) -> Path:
    """Copy the shipped configs and write a live authorization (approved unless None)."""
    root = tmp / "configs"
    shutil.copytree(SHIPPED_CONFIGS, root)
    auth = yaml.safe_load((root / "live" / "authorization.yaml").read_text())
    who = {"status": "approved", "approved_by": "Test Owner", "approved_on": "2026-11-01"}
    tbd = {"value": "TBD", "status": "unresolved", "ref": "UD-22"}
    # Reason: None means "unresolved" explicitly, independent of the shipped approved values.
    auth["max_capital_usd"] = {"value": float(cap), "ref": "UD-22", **who} if cap else tbd
    auth["min_paper_cycles_before_live"] = (
        {"value": cycles, "ref": "UD-22", **who} if cycles is not None else tbd
    )
    if ack:
        auth["acknowledgement"] = {
            "acknowledged_by": "Test Owner",
            "acknowledged_at_utc": "2026-11-01T00:00:00Z",
            "statement": "I accept that real money can be lost and nothing is guaranteed.",
        }
    (root / "live" / "authorization.yaml").write_text(yaml.safe_dump(auth))
    return root


def activate(root: Path, env: Environment, store: OperationalStore) -> Path:
    """Record an owner activation for the profile in ``root``."""
    profile = root / "profiles" / "balanced-paper.yaml"
    b = compile_bundle(profile, env, None, root, None, store, assume_activated=True)
    assert b.compiled.runnable, (b.compiled.errors, b.compiled.blockers)
    assert b.profile is not None
    store.record_activation(
        b.profile.profile_id,
        b.profile.version,
        b.compiled.trading_profile_hash,
        env.value,
        START,
        "test",
    )
    return profile


def make_runner(
    root: Path,
    env: Environment,
    store: OperationalStore,
    fake: FakeKraken | None = None,
    clock: SimulatedClock | None = None,
) -> tuple[SessionRunner, FakeKraken, SimulatedClock]:
    """Build a runner (and fake exchange) positioned just after bar FIRST_TICK_BAR closes."""
    c4, daily = candles()
    clock = clock or SimulatedClock(START + timedelta(hours=4 * (FIRST_TICK_BAR + 1), minutes=3))
    fake = fake or FakeKraken(c4, daily, clock.now)
    data = KrakenMarketData(fake, SYMBOLS)
    profile = root / "profiles" / "balanced-paper.yaml"

    def factory(b: Any, r: Any) -> Any:
        return kraken_adapter_factory(b, r, client=fake)

    runner = SessionRunner(
        SessionConfig(profile, env, configs_root=root),
        data,
        adapter_factory=factory if env == Environment.LIVE else None,
        clock=clock,
        store=store,
        sleep=lambda s: None,
    )
    return runner, fake, clock


def run_ticks(runner: SessionRunner, clock: SimulatedClock, n: int) -> None:
    """Advance one 4h bar per tick."""
    for _ in range(n):
        runner.tick()
        clock.set(clock.now() + timedelta(hours=4))


def balances(fake: FakeKraken) -> dict[str, Decimal]:
    """Exchange balances."""
    return dict(fake.balances)
