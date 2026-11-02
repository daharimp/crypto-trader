"""Bar-replay backtest runner (handoff §5.2, §7.13)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trader import __version__
from trader.common.clock import timeframe_delta
from trader.common.decimal_utils import fmt_usd
from trader.common.logging import configure_logging, get_logger, set_log_context
from trader.common.paths import data_root
from trader.common.revision import code_revision
from trader.data.snapshots import SnapshotBuilder
from trader.data.store import DatasetIntegrityError, DatasetNotFoundError, DatasetStore
from trader.domain.enums import Environment, EventType
from trader.evaluation.benchmarks import compute_benchmarks
from trader.evaluation.metrics import compute_metrics
from trader.evaluation.report import (
    DISCLAIMER,
    REPORT_SCHEMA_VERSION,
    comparison,
    non_approved_values,
    write_report,
)
from trader.execution.adapters.registry import build_adapter
from trader.execution.costs import CostParams
from trader.execution.service import ExecutionService
from trader.journal.store import JournalStore
from trader.pipeline.cycle import (
    RunFailedError,
    mark_to_market,
    process_open,
    process_stops,
    run_cycle,
)
from trader.pipeline.state import RunState
from trader.portfolio.ledger import Ledger
from trader.profiles.compiler import compile_bundle, exit_code
from trader.research.experiments import write_run_record
from trader.risk.controls import PersistedKillSwitch
from trader.risk.loss_state import LossTracker
from trader.risk.params import risk_params_from_compiled
from trader.strategies.registry import StrategyNotFoundError, build_strategy
from trader.universe.eligibility import EligibilityEvaluator
from trader.universe.registry import Registry

log = get_logger("backtest")


@dataclass
class RunResult:
    """Outcome of a backtest run."""

    exit_code: int
    run_id: str
    report_path: Path | None
    message: str


def new_run_id() -> str:
    """
    Build ``run-<UTC wall time>-<6 hex>`` (metadata only; excluded from hashes).

    Returns:
        str: Run ID.
    """
    return f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def _run_backtest(
    profile: Path,
    datasets: list[str],
    strategy: str,
    timeframe: str,
    experiment: Path | None,
    cost_scenario: str | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
    configs_root: Path | None = None,
    command: str = "",
    journal_factory: Any = JournalStore,
    eligibility_datasets: list[str] | None = None,
) -> RunResult:
    """
    Run one backtest end to end and write the report (implementation).

    Args:
        profile (Path): TradingProfile YAML.
        datasets (list[str]): Dataset IDs.
        strategy (str): Strategy ID.
        timeframe (str): Decision timeframe.
        experiment (Path | None): Experiment parameter set (required while values are TBD).
        cost_scenario (str | None): Cost scenario override.
        start_utc (datetime | None): First decision time (warm-up uses earlier candles).
        end_utc (datetime | None): Last decision time.
        configs_root (Path | None): Config root.
            Defaults to ``TRADER_CONFIGS_DIR`` or ``configs``.
        command (str): Command line for the reproduction record.
        journal_factory (Any): Journal constructor (tests inject failing journals).
        eligibility_datasets (list[str] | None): Optional daily (``1d``) datasets used for
            eligibility history and liquidity, as live sessions do (Kraken serves only 720
            candles per timeframe). Defaults to the decision-timeframe datasets.

    Returns:
        RunResult: Exit code (0, 1, 2, 3, or 4), run ID, report path, and message.
    """
    run_id = new_run_id()
    configure_logging(data_root() / "logs" / f"{run_id}.jsonl")
    set_log_context(run_id=run_id, cycle_id=None, correlation_id=None)
    journal = journal_factory(run_id)
    t_now = start_utc or datetime(1970, 1, 1, tzinfo=UTC)
    ks = PersistedKillSwitch().state()
    journal.append(
        EventType.RUN_STARTED,
        t_now,
        {
            "profile": str(profile),
            "datasets": datasets,
            "strategy": strategy,
            "timeframe": timeframe,
            "experiment": str(experiment) if experiment else None,
            "cost_scenario": cost_scenario,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "persisted_kill_switch": ks.model_dump(mode="json") if ks else {"state": "disengaged"},
            "persisted_kill_switch_note": "recorded, not obeyed in backtests (architecture §8.5)",
            "trader_version": __version__,
        },
        payload_type="RunInputs",
    )
    log.info("run started")
    bundle = compile_bundle(profile, Environment.BACKTEST, experiment, configs_root, cost_scenario)
    compiled = bundle.compiled
    journal.config_hash = compiled.config_hash
    journal.append(EventType.PROFILE_COMPILED, t_now, compiled)
    if not compiled.runnable:
        journal.append(
            EventType.RUN_BLOCKED,
            t_now,
            {
                "errors": compiled.errors,
                "blockers": [b.model_dump() for b in compiled.blockers],
                "unresolved_decisions": sorted({b.ref for b in compiled.blockers}),
            },
            payload_type="RunBlocked",
        )
        refs = ", ".join(sorted({b.ref for b in compiled.blockers}))
        msg = "; ".join(compiled.errors) or f"RISK_CONFIG_UNRESOLVED: {refs}"
        return RunResult(exit_code(compiled), run_id, None, msg)
    assert bundle.profile and bundle.registry and bundle.risk
    prof = bundle.profile

    def fail(code: int, msg: str, kill_switch_engaged: bool | None = None) -> RunResult:
        journal.append(
            EventType.RUN_FAILED,
            t_now,
            {"exit_code": code, "message": msg, "kill_switch_engaged": kill_switch_engaged},
            payload_type="RunFailed",
        )
        log.error(msg)
        return RunResult(code, run_id, None, msg)

    if timeframe not in prof.horizon.primary_decision_timeframes:
        return fail(2, f"timeframe {timeframe} not permitted by the profile")
    store = DatasetStore()
    builder = SnapshotBuilder(timeframe)
    for ds in datasets:
        try:
            manifest, df = store.load(ds)
        except DatasetIntegrityError as exc:
            return fail(4, str(exc))
        except DatasetNotFoundError:
            return fail(2, f"dataset not found: {ds}")
        if manifest.timeframe != timeframe:
            return fail(2, f"{ds} timeframe {manifest.timeframe} != {timeframe}")
        builder.add(manifest, df)
        journal.append(EventType.DATASET_VALIDATED, t_now, manifest)
    missing = sorted(set(prof.universe.instruments_in_scope) - set(builder.instruments))
    if missing:
        return fail(2, f"no dataset for in-scope instruments: {missing}")
    try:
        strat = build_strategy(strategy, configs_root)
    except (StrategyNotFoundError, ValueError) as exc:
        return fail(2, f"strategy unavailable: {exc}")

    registry = Registry(bundle.registry)
    costs = CostParams.from_scenario(compiled.cost_scenario)
    capital = prof.capital.paper_capital_usd
    adapter = build_adapter("simulated", capital, costs)
    delta = timeframe_delta(timeframe)
    elig_hist = {
        i: builder.history(i, datetime.max.replace(tzinfo=UTC)) for i in builder.instruments
    }
    elig_venue = {i: builder.manifest(i).source.venue_id for i in builder.instruments}
    elig_delta = delta
    if eligibility_datasets:
        elig_hist, elig_venue = {}, {}
        elig_delta = timeframe_delta("1d")
        for ds in eligibility_datasets:
            try:
                em, edf = store.load(ds)
            except DatasetIntegrityError as exc:
                return fail(4, str(exc))
            except DatasetNotFoundError:
                return fail(2, f"eligibility dataset not found: {ds}")
            if em.timeframe != "1d":
                return fail(2, f"eligibility dataset {ds} must be 1d, not {em.timeframe}")
            from trader.data.frames import frame_to_candles

            elig_hist[em.instrument_id] = frame_to_candles(edf, "1d")
            elig_venue[em.instrument_id] = em.source.venue_id
            journal.append(EventType.DATASET_VALIDATED, t_now, em)
    elig = EligibilityEvaluator(compiled, prof, registry, elig_hist, elig_venue, elig_delta)
    state = RunState(
        compiled=compiled,
        profile=prof,
        params=risk_params_from_compiled(compiled),
        registry=registry,
        costs=costs,
        environment=Environment.BACKTEST,
        timeframe=timeframe,
        builder=builder,
        eligibility=elig,
        strategy=strat,
        adapter=adapter,
        execution=ExecutionService(adapter),
        ledger=Ledger(cash=capital),
        loss=LossTracker(capital),
        journal=journal,
    )
    grid = decision_grid(builder, delta, start_utc, end_utc)
    if not grid:
        return fail(2, "INSUFFICIENT_HISTORY: no decision times in the evaluation window")
    try:
        for t1 in grid:
            t0 = t1 - delta
            process_open(state, t0)
            process_stops(state, t0)
            mark_to_market(state, t1)
            run_cycle(state, t1)
            state.equity_curve.append((t1, state.ledger.equity))
            snap = state.position_snapshot(t1)
            state.exposure_curve.append(snap.total_exposure_pct)
    except RunFailedError as exc:
        try:
            return fail(1, str(exc), state.controls.kill_switch.engaged)
        except Exception:  # noqa: BLE001 - journal itself is failing
            return RunResult(1, run_id, None, str(exc))
    return _finish(state, run_id, datasets, grid, strategy, bundle.experiment, command)


def run_backtest(
    profile: Path,
    datasets: list[str],
    strategy: str,
    timeframe: str,
    experiment: Path | None,
    cost_scenario: str | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
    configs_root: Path | None = None,
    command: str = "",
    journal_factory: Any = JournalStore,
    eligibility_datasets: list[str] | None = None,
) -> RunResult:
    """
    Run one backtest end to end and write the report (handoff §7.13 signature).

    Args:
        profile (Path): TradingProfile YAML.
        datasets (list[str]): Dataset IDs.
        strategy (str): Strategy ID.
        timeframe (str): Decision timeframe.
        experiment (Path | None): Experiment parameter set (required while values are TBD).
        cost_scenario (str | None): Cost scenario override.
        start_utc (datetime | None): First decision time (warm-up uses earlier candles).
        end_utc (datetime | None): Last decision time.
        configs_root (Path | None): Config root.
            Defaults to ``TRADER_CONFIGS_DIR`` or ``configs``.
        command (str): Command line for the reproduction record.
        journal_factory (Any): Journal constructor (tests inject failing journals).
        eligibility_datasets (list[str] | None): Optional daily (``1d``) datasets used for
            eligibility history and liquidity, as live sessions do (Kraken serves only 720
            candles per timeframe). Defaults to the decision-timeframe datasets.

    Returns:
        RunResult: Exit code (0, 1, 2, 3, or 4), run ID, report path, and message.
    """
    opened: list[Any] = []

    def factory(run_id: str) -> Any:
        j = journal_factory(run_id)
        opened.append(j)
        return j

    try:
        return _run_backtest(
            profile,
            datasets,
            strategy,
            timeframe,
            experiment,
            cost_scenario,
            start_utc,
            end_utc,
            configs_root,
            command,
            factory,
            eligibility_datasets,
        )
    finally:
        for j in opened:
            j.close()


def decision_grid(
    builder: SnapshotBuilder, delta: Any, start: datetime | None, end: datetime | None
) -> list[datetime]:
    """
    Regular grid of decision closes; missing bars stay in the grid (stale cycles).

    Args:
        builder (SnapshotBuilder): Candle access.
        delta (Any): Bar length (timedelta).
        start (datetime | None): First decision time (default: first close).
        end (datetime | None): Last decision time (default: last close).

    Returns:
        list[datetime]: Decision times.
    """
    closes = [
        c.close_time_utc
        for i in builder.instruments
        for c in builder.history(i, datetime.max.replace(tzinfo=UTC))
    ]
    if not closes:
        return []
    first, last = min(closes), max(closes)
    lo = max(first, start) if start else first
    hi = min(last, end) if end else last
    # Reason: align lo up to the bar grid so cycles happen exactly at bar closes.
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    steps = -(-int((lo - epoch).total_seconds()) // int(delta.total_seconds()))
    t = epoch + steps * delta
    out = []
    while t <= hi:
        out.append(t)
        t += delta
    return out


def _finish(
    state: RunState,
    run_id: str,
    datasets: list[str],
    grid: list[datetime],
    strategy: str,
    exp: Any,
    command: str,
) -> RunResult:
    """
    Compute benchmarks, metrics, report, and experiment record.

    Args:
        state (RunState): Final state.
        run_id (str): Run ID.
        datasets (list[str]): Dataset IDs.
        grid (list[datetime]): Decision times.
        strategy (str): Strategy ID.
        exp (Any): ExperimentDefinition or None.
        command (str): Reproduction command.

    Returns:
        RunResult: Success.
    """
    compiled, led = state.compiled, state.ledger
    capital = state.profile.capital.paper_capital_usd
    steps = {i.instrument_id: i.quantity_step for i in state.registry.data.instruments}
    bms = compute_benchmarks(state.builder, grid, capital, state.costs, steps)
    curve = list(state.equity_curve)
    strat_m = compute_metrics(
        curve, led.trades, state.exposure_curve, led.fees_usd, led.slippage_usd
    )
    bm_m = {k: compute_metrics(v) for k, v in bms.items()}
    trading = {
        "order_intents": state.counts["order_intents"],
        "fills": state.counts["fills"],
        "closed_trades": len(led.trades),
        "fees_usd": fmt_usd(led.fees_usd),
        "slippage_cost_usd": fmt_usd(led.slippage_usd),
        "rejections_by_reason": dict(sorted(state.rejections.items())),
    }
    state.journal.append(
        EventType.RUN_COMPLETED,
        grid[-1],
        {
            "strategy_metrics": strat_m,
            "benchmarks": bm_m,
            "trading": trading,
        },
        payload_type="RunSummary",
    )
    report: dict[str, Any] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "run_metadata": {
            "run_id": run_id,
            "created_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code_revision": code_revision(),
        },
        "disclaimer": DISCLAIMER,
        "provenance": {
            "config_hash": compiled.config_hash,
            "trading_profile": {
                "id": compiled.trading_profile.id,
                "version": compiled.trading_profile.version,
            },
            "risk_profile": {
                "id": compiled.risk_profile.id,
                "version": compiled.risk_profile.version,
            },
            "experiment_id": compiled.experiment_id,
            "non_approved_values": non_approved_values(compiled),
        },
        "data": {
            "datasets": datasets,
            "timeframe": state.timeframe,
            "evaluation_start_utc": grid[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evaluation_end_utc": grid[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "costs": {
            k: compiled.cost_scenario[k]
            for k in ("scenario_id", "fee_rate_pct", "slippage_bps", "min_notional_usd")
        },
        "strategy": {
            "strategy_id": strategy,
            "version": state.strategy.version,
            "metrics": strat_m,
        },
        "benchmarks": bm_m,
        "comparison": comparison(strat_m, bm_m),
        "trading": trading,
        "journal": {"root_hash": state.journal.prev_hash, "event_count": state.journal.seq},
    }
    report["costs"]["scenario"] = report["costs"].pop("scenario_id")
    path = write_report(report, data_root() / "reports" / run_id)
    if exp is not None:
        write_run_record(
            exp,
            compiled,
            run_id,
            report["data"],
            {"strategy": strat_m, "benchmarks": bm_m, "trading": trading},
            command or "trader backtest run ...",
        )
    log.info("run completed")
    return RunResult(0, run_id, path, f"report: {path}")
