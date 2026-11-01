"""Builders for RiskContext and RunState using labelled fixture values (handoff §9.1).

Risk tests build contexts directly; they never edit ``configs/risk/*.yaml``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from tests.conftest import EXP_FIXTURE, PROFILE
from tests.helpers import T0, series
from trader.common.ids import IdGenerator
from trader.data.frames import candles_to_frame
from trader.data.snapshots import SnapshotBuilder
from trader.domain.candles import Candle
from trader.domain.ensemble import Conflict, EnsembleDecision
from trader.domain.enums import (
    EnsembleAction,
    Environment,
    OrderPurpose,
    OrderType,
    Side,
    Sleeve,
)
from trader.domain.market import DatasetManifest, SourceRef
from trader.domain.orders import OrderIntent
from trader.domain.signals import Invalidation, SignalCandidate
from trader.domain.universe import AssetEligibility, UniverseSnapshot
from trader.execution.adapters.simulated import SimulatedExecutionAdapter
from trader.execution.costs import CostParams
from trader.execution.service import ExecutionService
from trader.features.definitions import FEATURE_WINDOW_BARS
from trader.features.pipeline import compute_features
from trader.journal.store import JournalStore
from trader.pipeline.state import RunState
from trader.portfolio.ledger import Ledger
from trader.profiles.compiler import CompileBundle, compile_bundle
from trader.risk.context import RiskContext
from trader.risk.controls import RunControls
from trader.risk.loss_state import LossTracker
from trader.risk.params import RiskParams, risk_params_from_compiled
from trader.strategies.sma_trend import SmaTrend
from trader.universe.eligibility import EligibilityEvaluator
from trader.universe.registry import Registry

BASE_COSTS = CostParams("base", Decimal("0.40"), Decimal("10"), Decimal("10"))
STEP = Decimal("0.00000001")
_BUNDLE: dict[str, CompileBundle] = {}


def fixture_bundle() -> CompileBundle:
    """Compile the shipped profile with the EXP-0000-001 fixture experiment (cached)."""
    if "b" not in _BUNDLE:
        b = compile_bundle(PROFILE, Environment.BACKTEST, EXP_FIXTURE)
        assert b.compiled.runnable, b.compiled.errors
        _BUNDLE["b"] = b
    return _BUNDLE["b"]


def manifest(inst: str, candles: list[Candle], venue: str = "sim") -> DatasetManifest:
    """A minimal manifest for in-memory builders."""
    return DatasetManifest(
        schema_version="1.0.0",
        dataset_id=f"ds-{inst}",
        instrument_id=inst,
        timeframe="4h",
        source=SourceRef(provider_id="t", venue_id=venue, retrieved_at_utc=None),
        source_label="t",
        row_count=len(candles),
        first_open_time_utc=candles[0].open_time_utc,
        last_open_time_utc=candles[-1].open_time_utc,
        content_hash="x",
        parquet_sha256="x",
        quality_status="ok",
        quality_issues=[],
        gaps=[],
    )


def flat_candles(n: int = 60, price: int = 100, start: datetime = T0) -> list[Candle]:
    """Constant closes with high/low = close +/- 1, so ATR(14) = 2."""
    return series([price] * n, start=start)


def signal(
    inst: str,
    t: datetime,
    side: Side = Side.BUY,
    sleeve: Sleeve = Sleeve.CORE,
    sid: str = "sig-1",
    strategy: str = "sma_trend",
) -> SignalCandidate:
    """A fixture signal."""
    return SignalCandidate(
        schema_version="1.0.0",
        signal_id=sid,
        correlation_id="cor-1",
        cycle_id="cyc-1",
        instrument_id=inst,
        timeframe="4h",
        decision_time_utc=t,
        strategy_id=strategy,
        strategy_version="1.0.0",
        sleeve=sleeve,
        side=side,
        strength=Decimal(1),
        confidence=None,
        expected_horizon=None,
        entry_reference_price=Decimal(100),
        invalidation=Invalidation(kind="x", level=None, reason="x"),
        feature_set_id="fs-1",
        regime_assessment_id="rg-1",
        model_id=None,
        model_version=None,
        rationale_codes=["X"],
    )


def decision(
    inst: str, t: datetime, action: EnsembleAction = EnsembleAction.ENTER_LONG
) -> EnsembleDecision:
    """A fixture ensemble decision."""
    return EnsembleDecision(
        schema_version="1.0.0",
        ensemble_decision_id="ens-1",
        correlation_id="cor-1",
        cycle_id="cyc-1",
        instrument_id=inst,
        decision_time_utc=t,
        action=action,
        position_state="flat" if action == EnsembleAction.ENTER_LONG else "long",
        contributing_signal_ids=["sig-1"],
        ignored_signals=[],
        combined_score=None,
        confidence=None,
        conflict=Conflict(detected=False, buy_votes=1, sell_votes=0),
        no_trade_reason=None,
        ensemble_id="e",
        ensemble_version="1",
        weighting_method="s",
        regime_assessment_id="rg-1",
    )


def eligible_universe(
    t: datetime, insts: list[str], eligible: bool = True, reason: str | None = None
) -> UniverseSnapshot:
    """A hand-built universe snapshot."""
    return UniverseSnapshot(
        schema_version="1.0.0",
        universe_snapshot_id="uni-1",
        as_of_utc=t,
        assets={
            i: AssetEligibility(
                instrument_id=i,
                asset_id=i.split("-")[0],
                tier="core",
                eligible=eligible,
                criteria=[],
                reason=reason,
            )
            for i in insts
        },
    )


def make_ctx(
    inst: str = "BTC-USD",
    candles: list[Candle] | None = None,
    t: datetime | None = None,
    cash: Decimal = Decimal(2500),
    holdings: dict[str, tuple[Decimal, Decimal]] | None = None,
    pending: list[OrderIntent] | None = None,
    params: RiskParams | None | str = "fixture",
    controls: RunControls | None = None,
    loss: LossTracker | None = None,
    profile_update: dict[str, Any] | None = None,
    registry: Registry | None = None,
    universe: UniverseSnapshot | None = None,
    signals: list[SignalCandidate] | None = None,
    used_keys: set[str] | None = None,
    costs: CostParams = BASE_COSTS,
    compiled: Any = None,
    environment: Environment = Environment.BACKTEST,
) -> RiskContext:
    """Build a RiskContext. ``holdings`` maps instrument -> (quantity, mark price)."""
    b = fixture_bundle()
    candles = candles or flat_candles()
    t = t or candles[-1].close_time_utc
    builder = SnapshotBuilder("4h")
    builder.add(manifest(inst, candles), candles_to_frame(candles))
    snap = builder.snapshot(inst, t, "cyc-1", "snp-1")
    fs = (
        compute_features(
            builder.window(inst, t, FEATURE_WINDOW_BARS), inst, "4h", t, "fs-1", ["ds"]
        )
        if builder.window(inst, t, 1)
        else None
    )
    reg = registry or Registry(b.registry)  # type: ignore[arg-type]
    led = Ledger(cash=cash)
    for i, (q, px) in (holdings or {}).items():
        from trader.portfolio.ledger import _Position

        led.positions[i] = _Position(
            q, px, q * px, T0, reg.tier_of(i) or "core", ["sma_trend"], mark=px
        )
    tracker = loss or LossTracker(led.equity)
    ctl = controls or RunControls()
    pend = pending or []
    committed = sum(
        (o.notional_estimate_usd * (1 + costs.fee_rate) for o in pend if o.side == Side.BUY),
        Decimal(0),
    )
    pos = led.snapshot(
        "pos-1",
        t,
        committed,
        tracker.hwm,
        tracker.day_start,
        ctl.breaker.open,
        ctl.lockout.until,
        {},
    )
    prof = b.profile
    assert prof is not None
    if profile_update:
        prof = prof.model_copy(update=profile_update)
    comp = compiled or b.compiled
    rp = risk_params_from_compiled(comp) if params == "fixture" else params
    return RiskContext(
        compiled=comp,
        profile=prof,
        params=rp,  # type: ignore[arg-type]
        registry=reg,
        costs=costs,
        environment=environment,
        timeframe="4h",
        decision_time=t,
        position=pos,
        snapshot=snap,
        features=fs,
        universe=universe or eligible_universe(t, [inst]),
        signals=signals if signals is not None else [signal(inst, t)],
        controls=ctl,
        loss=tracker.state(
            rp if isinstance(rp, RiskParams) else None, ctl.breaker.open, ctl.lockout.active(t)
        ),
        ids=IdGenerator(),
        used_idempotency_keys=used_keys or set(),
        pending=pend,
    )


def params_with(**changes: Any) -> RiskParams:
    """Fixture RiskParams with overrides."""
    p = risk_params_from_compiled(fixture_bundle().compiled)
    assert p is not None
    return replace(p, **changes)


def market_intent(
    inst: str,
    t: datetime,
    side: Side = Side.BUY,
    qty: str = "1",
    rd_id: str = "rsk-000001",
    purpose: OrderPurpose | None = None,
    key: str = "k1",
    oid: str = "ord-1",
    notional: str | None = None,
) -> OrderIntent:
    """A fixture market intent."""
    purpose = purpose or (OrderPurpose.ENTRY if side == Side.BUY else OrderPurpose.EXIT)
    return OrderIntent(
        schema_version="1.0.0",
        order_intent_id=oid,
        correlation_id="cor-1",
        cycle_id="cyc-1",
        idempotency_key=key,
        risk_decision_id=rd_id,
        ensemble_decision_id="ens-1",
        signal_ids=["sig-1"],
        strategy_versions=[{"id": "sma_trend", "version": "1.0.0"}],
        model_versions=[],
        instrument_id=inst,
        side=side,
        purpose=purpose,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        reference_price=Decimal(100),
        stop_price=None,
        attached_stop_distance_pct=Decimal(4) if side == Side.BUY else None,
        parent_order_intent_id=None,
        notional_estimate_usd=Decimal(notional) if notional else Decimal(qty) * 100,
        valid_until_utc=t + timedelta(hours=4),
        environment=Environment.BACKTEST,
        funds="simulated",
        config_hash="sha256:x",
        market_data_timestamp_utc=t,
        decision_time_utc=t,
        created_at_utc=t,
    )


def make_state(
    candles: dict[str, list[Candle]], run_id: str = "run-test", journal: JournalStore | None = None
) -> RunState:
    """Build a RunState over in-memory candles with fixture values."""
    b = fixture_bundle()
    assert b.profile is not None and b.registry is not None
    builder = SnapshotBuilder("4h")
    for inst, c in candles.items():
        builder.add(manifest(inst, c), candles_to_frame(c))
    reg = Registry(b.registry)
    capital = b.profile.capital.paper_capital_usd
    adapter = SimulatedExecutionAdapter(capital, BASE_COSTS)
    j = journal or JournalStore(run_id)
    j.config_hash = b.compiled.config_hash
    j.append(
        __import__("trader.domain.enums", fromlist=["EventType"]).EventType.PROFILE_COMPILED,
        T0,
        b.compiled,
    )
    elig = EligibilityEvaluator(
        b.compiled, b.profile, reg, dict(candles), {i: "sim" for i in candles}, timedelta(hours=4)
    )
    return RunState(
        compiled=b.compiled,
        profile=b.profile,
        params=risk_params_from_compiled(b.compiled),
        registry=reg,
        costs=BASE_COSTS,
        environment=Environment.BACKTEST,
        timeframe="4h",
        builder=builder,
        eligibility=elig,
        strategy=SmaTrend(),
        adapter=adapter,
        execution=ExecutionService(adapter),
        ledger=Ledger(cash=capital),
        loss=LossTracker(capital),
        journal=j,
    )


def stop_intent(
    inst: str,
    t: datetime,
    stop_price: str,
    qty: str = "1",
    parent: str = "ord-1",
    oid: str = "stop",
) -> OrderIntent:
    """A fixture protective stop intent."""
    base = market_intent(inst, t, Side.SELL, qty=qty, oid=oid, key=f"k-{oid}")
    return OrderIntent.model_validate(
        base.model_dump()
        | {
            "purpose": OrderPurpose.PROTECTIVE_STOP,
            "order_type": OrderType.STOP_MARKET,
            "stop_price": Decimal(stop_price),
            "reference_price": Decimal(stop_price),
            "parent_order_intent_id": parent,
        }
    )
