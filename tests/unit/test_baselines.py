"""BL-022 baselines: features-m2 and the tsmom, mean_reversion, volatility_breakout,
random_entry strategies."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.conftest import SHIPPED_CONFIGS
from tests.factories import fixture_bundle
from tests.helpers import series
from trader.data.frames import candles_to_frame
from trader.data.snapshots import SnapshotBuilder
from trader.domain.candles import Candle
from trader.domain.enums import Side
from trader.domain.market import DatasetManifest, SourceRef
from trader.features.definitions import FEATURE_SET_VERSION, FEATURE_WINDOW_BARS
from trader.features.pipeline import bollinger, compute_features, trailing_return, wilder_rsi
from trader.regimes.null_classifier import assess
from trader.strategies.base import SignalIds
from trader.strategies.mean_reversion import MeanReversion
from trader.strategies.random_entry import RandomEntry
from trader.strategies.registry import StrategyNotFoundError, build_strategy
from trader.strategies.sma_trend import SmaTrend
from trader.strategies.tsmom import Tsmom
from trader.strategies.volatility_breakout import VolatilityBreakout

D = Decimal


def _manifest(c: list[Candle]) -> DatasetManifest:
    return DatasetManifest(
        schema_version="1.0.0",
        dataset_id="ds-t",
        instrument_id="BTC-USD",
        timeframe="4h",
        source=SourceRef(provider_id="t", venue_id="sim", retrieved_at_utc=None),
        source_label="t",
        row_count=len(c),
        first_open_time_utc=c[0].open_time_utc,
        last_open_time_utc=c[-1].open_time_utc,
        content_hash="x",
        parquet_sha256="x",
        quality_status="ok",
        quality_issues=[],
        gaps=[],
    )


def run(strategy, closes: list[int]) -> list[tuple[int, Side]]:  # type: ignore[no-untyped-def]
    """Signals (bar index, side) emitted at every bar close."""
    c = series(closes)
    b = SnapshotBuilder("4h")
    b.add(_manifest(c), candles_to_frame(c))
    out = []
    for i, bar in enumerate(c):
        t = bar.close_time_utc
        snap = b.snapshot("BTC-USD", t, "c", "s")
        fs = compute_features(
            b.window("BTC-USD", t, FEATURE_WINDOW_BARS), "BTC-USD", "4h", t, "f", ["ds"]
        )
        for s in strategy.generate(snap, fs, assess(snap, fs, "r"), SignalIds("s", "c", "c")):
            out.append((i, s.side))
            assert s.strategy_id == strategy.strategy_id and s.strategy_version == "1.0.0"
    return out


def test_indicator_values() -> None:
    """Hand-checkable values: RSI extremes, flat Bollinger bands, trailing return."""
    up = [D(i) for i in range(1, 30)]
    assert wilder_rsi(up) == 100 and wilder_rsi(list(reversed(up))) == 0
    assert wilder_rsi([D(5)] * 20) == 50 and wilder_rsi([D(1)] * 5) is None
    assert bollinger([D(10)] * 20) == (D(10), D(10), D(10)) and bollinger([D(1)]) is None
    assert trailing_return([D(100), D(110)], 1) == D("0.1") and trailing_return([D(1)], 1) is None
    assert FEATURE_SET_VERSION == "features-m2-1.0.0"


def test_tsmom_turns_positive_then_sells() -> None:
    """Buy once when the 7-day return turns positive; sell while it is not positive."""
    closes = [100] * 50 + list(range(100, 60, -2)) + list(range(62, 140, 3))
    sig = run(Tsmom(), closes)
    buys = [i for i, s in sig if s == Side.BUY]
    assert len(buys) == 1 and any(s == Side.SELL and i < buys[0] for i, s in sig)
    with pytest.raises(ValueError):
        Tsmom(lookback_days=3)


def test_mean_reversion_entry_and_exit() -> None:
    """Oversold below the lower band -> buy; reversion to the middle band -> sell."""
    closes = [100] * 40 + [96, 92, 88, 84, 80, 76] + [80, 86, 92, 98, 104]
    sig = run(MeanReversion(), closes)
    first_buy = next(i for i, s in sig if s == Side.BUY)
    assert first_buy >= 40 and any(s == Side.SELL and i > first_buy for i, s in sig)


def test_mean_reversion_strength() -> None:
    """Strength = (30 - RSI) / 30, within [0, 1]."""
    closes = [100] * 40 + [96, 92, 88, 84, 80, 76]
    c = series(closes)
    b = SnapshotBuilder("4h")
    b.add(_manifest(c), candles_to_frame(c))
    t = c[-1].close_time_utc
    fs = compute_features(b.window("BTC-USD", t, 200), "BTC-USD", "4h", t, "f", ["d"])
    snap = b.snapshot("BTC-USD", t, "c", "s")
    [s] = MeanReversion().generate(snap, fs, assess(snap, fs, "r"), SignalIds("s", "c", "c"))
    rsi = fs.values["rsi_14"]
    assert rsi is not None and s.strength == (30 - rsi) / 30 and 0 < s.strength <= 1


def test_breakout_channels() -> None:
    """Close above the prior 20-bar high -> buy; below the prior 10-bar low -> sell."""
    closes = [100] * 30 + [110] + [100] * 5 + [80]
    sig = run(VolatilityBreakout(), closes)
    assert (30, Side.BUY) in sig and (36, Side.SELL) in sig
    assert not [x for x in sig if x[0] < 30]


def test_random_entry_deterministic_and_seeded() -> None:
    """Same seed -> identical signals; different seed -> different timing; rates honoured."""
    closes = [100] * 600
    a = run(RandomEntry(seed=1, p_entry=0.05, p_exit=0.1), closes)
    b = run(RandomEntry(seed=1, p_entry=0.05, p_exit=0.1), closes)
    c = run(RandomEntry(seed=2, p_entry=0.05, p_exit=0.1), closes)
    assert a == b and a != c
    buys = sum(1 for _, s in a if s == Side.BUY)
    assert 10 <= buys <= 50  # about 5% of ~550 post-warm-up bars
    for bad in ((0, 0.1), (0.1, 1)):
        with pytest.raises(ValueError):
            RandomEntry(p_entry=bad[0], p_exit=bad[1])


def test_registry_guards() -> None:
    """All baselines build; breakout is 4h-only; the control is refused in sessions."""
    root = SHIPPED_CONFIGS  # the frozen M1 fixture configs predate these strategies
    for sid in ("sma_trend", "tsmom", "mean_reversion", "volatility_breakout", "random_entry"):
        assert build_strategy(sid, root, timeframe="4h").strategy_id == sid
    with pytest.raises(StrategyNotFoundError, match="timeframe"):
        build_strategy("volatility_breakout", root, timeframe="1h")
    with pytest.raises(StrategyNotFoundError, match="control"):
        build_strategy("random_entry", root, timeframe="4h", forward_session=True)
    assert build_strategy("sma_trend", root, timeframe="4h", forward_session=True)
    _ = fixture_bundle


@settings(max_examples=15, deadline=None)
@given(
    base=st.lists(st.integers(50, 150), min_size=90, max_size=90),
    noise=st.lists(st.integers(5, 400), min_size=90, max_size=90),
    cut=st.integers(55, 88),
)
def test_no_lookahead_any_baseline(base: list[int], noise: list[int], cut: int) -> None:
    """LA-01 for every baseline: changing the future never changes past signals."""
    pert = base[: cut + 1] + noise[cut + 1 :]
    for strat in (Tsmom(), MeanReversion(), VolatilityBreakout(), RandomEntry(seed=3), SmaTrend()):
        a = [x for x in run(strat, base) if x[0] <= cut]
        b = [x for x in run(strat, pert) if x[0] <= cut]
        assert a == b, strat.strategy_id
