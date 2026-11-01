"""T-19: ``sma_trend`` signal contract."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.helpers import series
from trader.data.snapshots import SnapshotBuilder
from trader.data.store import DatasetStore
from trader.domain.enums import EnsembleAction, Side
from trader.domain.market import SourceRef
from trader.domain.signals import SignalCandidate
from trader.ensemble.passthrough import decide
from trader.features.definitions import FEATURE_WINDOW_BARS
from trader.features.pipeline import compute_features
from trader.regimes.null_classifier import assess
from trader.strategies.base import SignalIds
from trader.strategies.registry import StrategyNotFoundError, build_strategy
from trader.strategies.sma_trend import SmaTrend

SRC = SourceRef(provider_id="test", venue_id="sim", retrieved_at_utc=None)


def run_signals(closes: list[int]) -> list[tuple[int, list[SignalCandidate]]]:
    """Run features -> null regime -> sma_trend at every bar close."""
    candles = series(closes)
    store = DatasetStore()
    m = store.create(candles, "BTC-USD", "4h", SRC, "t19")
    b = SnapshotBuilder("4h")
    b.add(*store.load(m.dataset_id))
    strat = SmaTrend()
    out = []
    for i, c in enumerate(candles):
        t = c.close_time_utc
        snap = b.snapshot("BTC-USD", t, f"cyc-{i}", f"snp-{i}")
        fs = compute_features(
            b.window("BTC-USD", t, FEATURE_WINDOW_BARS),
            "BTC-USD",
            "4h",
            t,
            f"fs-{i}",
            [m.dataset_id],
        )
        rg = assess(snap, fs, f"rg-{i}")
        out.append((i, strat.generate(snap, fs, rg, SignalIds(f"sig-{i}", f"cor-{i}", f"cyc-{i}"))))
    return out


def test_t19_cross_up_then_sells() -> None:
    """T-19: one buy at the cross; sells while below; nothing else."""
    closes = [100] * 50 + [90] * 10 + [130] * 12 + [60] * 30
    res = run_signals(closes)
    buys = [i for i, s in res if s and s[0].side == Side.BUY]
    sells = [i for i, s in res if s and s[0].side == Side.SELL]
    assert len(buys) == 1
    b = buys[0]
    assert 60 <= b < 72 and res[b][1][0].rationale_codes == ["SMA_CROSS_UP"]
    later = [i for i in sells if i > b]
    assert later and all(i in sells for i in range(later[0], len(res)))
    assert all(res[i][1][0].rationale_codes == ["SMA_FAST_BELOW_SLOW"] for i in sells)
    # No signal before warm-up (51 bars).
    assert all(not s for i, s in res if i < 50)
    sig = res[b][1][0]
    for name in ("quantity", "notional_usd", "stop_price", "leverage"):
        assert name not in SignalCandidate.model_fields
    with pytest.raises(ValidationError):
        SignalCandidate(**sig.model_dump(), quantity=Decimal(1))


def test_t19_flat_series_no_signal() -> None:
    """Edge: equal SMAs produce no signal."""
    assert all(not s for _, s in run_signals([100] * 70))


def test_ensemble_mapping() -> None:
    """Pass-through ensemble: flat+buy enters; long+owner sell exits; others hold."""
    closes = [100] * 50 + [90] * 10 + [130] * 12 + [60] * 30
    res = run_signals(closes)
    buy = next(s[0] for _, s in res if s and s[0].side == Side.BUY)
    sell = next(s[0] for _, s in res if s and s[0].side == Side.SELL)
    from trader.domain.enums import DataState, RegimeMethod, TrendState, VolatilityState
    from trader.domain.regime import RegimeAssessment

    def rg(state: DataState) -> RegimeAssessment:
        return RegimeAssessment(
            schema_version="1.0.0",
            regime_assessment_id="rg",
            instrument_id="BTC-USD",
            timeframe="4h",
            as_of_utc=buy.decision_time_utc,
            trend_state=TrendState.UNKNOWN,
            volatility_state=VolatilityState.UNKNOWN,
            data_state=state,
            label="u",
            confidence=None,
            method=RegimeMethod.NOT_EVALUATED,
            classifier_id="n",
            classifier_version="1",
            model_version=None,
            feature_set_id=None,
        )

    ok = rg(DataState.OK)
    assert decide([buy], ok, "flat", [], "e", "c", "y").action == EnsembleAction.ENTER_LONG
    assert (
        decide([sell], ok, "long", ["sma_trend"], "e", "c", "y").action == EnsembleAction.EXIT_LONG
    )
    assert decide([sell], ok, "long", ["other"], "e", "c", "y").action == EnsembleAction.HOLD
    assert decide([sell], ok, "flat", [], "e", "c", "y").action == EnsembleAction.HOLD
    assert decide([buy], ok, "long", ["sma_trend"], "e", "c", "y").action == EnsembleAction.HOLD
    assert decide([], ok, "flat", [], "e", "c", "y").action == EnsembleAction.HOLD
    stale = decide([buy], rg(DataState.STALE), "flat", [], "e", "c", "y")
    assert stale.action == EnsembleAction.NO_TRADE and stale.no_trade_reason == "DATA_STALE"


def test_registry_builds_and_rejects() -> None:
    """Registry builds sma_trend; unknown strategies fail; wrong params fail."""
    assert build_strategy("sma_trend").strategy_id == "sma_trend"
    with pytest.raises(StrategyNotFoundError):
        build_strategy("nope")
    with pytest.raises(ValueError):
        SmaTrend(10, 30)
