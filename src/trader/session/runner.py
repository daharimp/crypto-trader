"""Forward session runner (BL-027): the same decision pipeline as backtests, on the clock.

Paper: simulated fills against live Kraken candles. Live: real Kraken orders (ADR-023).
Each 4h bar close (+ the approved grace) runs: config re-check, kill-switch sync, clock-skew
check, market refresh, fill/stop sync, mark-to-market, decision cycle, (live) fill
confirmation with protective stops, staleness tracking, and a state save.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trader.common.clock import Clock, WallClock, format_utc, parse_utc, timeframe_delta
from trader.common.logging import configure_logging, get_logger, set_log_context
from trader.common.opstore import OperationalStore
from trader.common.paths import data_root
from trader.data.frames import candles_to_frame
from trader.data.snapshots import SnapshotBuilder
from trader.domain.enums import Environment, EventType
from trader.execution.adapters.simulated import SimulatedExecutionAdapter
from trader.execution.costs import CostParams
from trader.execution.service import ExecutionService
from trader.journal.store import JournalStore
from trader.pipeline import cycle as cyc
from trader.pipeline.state import RunState
from trader.portfolio.ledger import Ledger
from trader.profiles.compiler import CompileBundle, compile_bundle, exit_code
from trader.risk.controls import PersistedKillSwitch
from trader.risk.loss_state import LossTracker
from trader.risk.params import risk_params_from_compiled
from trader.strategies.registry import build_strategy
from trader.universe.eligibility import EligibilityEvaluator
from trader.universe.registry import Registry

from .alerts import Alerter
from .config import SessionConfig, SessionError, _eff
from .flatten import flatten_all
from .market_data import KrakenMarketData, MarketDataError, live_manifest
from .state_store import load_state, save_state, state_path

log = get_logger("session")
PAPER_CATCHUP_BARS = 6
STALE_RETRIES = 3


class SessionRunner:
    """Runs a paper or live session."""

    def __init__(
        self,
        cfg: SessionConfig,
        data: KrakenMarketData,
        adapter_factory: Callable[[CompileBundle, Registry], Any] | None = None,
        clock: Clock | None = None,
        store: OperationalStore | None = None,
        alerter: Alerter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Prepare a session (call :meth:`start` next).

        Args:
            cfg (SessionConfig): Session configuration.
            data (KrakenMarketData): Market data source.
            adapter_factory (Callable | None): Builds the live adapter (required for live).
            clock (Clock | None): Clock (tests inject a simulated one).
            store (OperationalStore | None): Operational store.
            alerter (Alerter | None): Owner alerts.
            sleep (Callable[[float], None]): Sleep function.
        """
        if cfg.environment == Environment.BACKTEST:
            raise SessionError(2, "sessions run in paper or live; use `trader backtest run`")
        if cfg.environment == Environment.LIVE and adapter_factory is None:
            raise SessionError(2, "live sessions need the Kraken adapter")
        self.cfg, self.data, self.factory = cfg, data, adapter_factory
        self.clock = clock or WallClock()
        self.store = store or OperationalStore()
        self.kill = PersistedKillSwitch(self.store)
        tag = "[LIVE]" if cfg.environment == Environment.LIVE else "[paper]"
        self.alerter = alerter or Alerter.from_env(tag)
        self.sleep = sleep
        self.delta = timeframe_delta(cfg.timeframe)
        self.meta: dict[str, Any] = {}
        self.state: RunState
        self.bundle: CompileBundle

    # --- start ---------------------------------------------------------------------------
    def _compile(self) -> CompileBundle:
        """
        Compile for this session's environment.

        Returns:
            CompileBundle: Bundle.
        """
        return compile_bundle(
            self.cfg.profile, self.cfg.environment, None, self.cfg.configs_root, None, self.store
        )

    def start(self) -> None:
        """
        Compile, apply every gate, build or restore state, and journal the start.

        Raises:
            SessionError: If the profile is not runnable or the account is not as required.
        """
        b = self._compile()
        if not b.compiled.runnable or b.profile is None or b.registry is None:
            msg = "; ".join(b.compiled.errors) or "unresolved: " + ", ".join(
                sorted({x.ref for x in b.compiled.blockers})
            )
            raise SessionError(exit_code(b.compiled) or 2, msg)
        if self.cfg.timeframe not in b.profile.horizon.primary_decision_timeframes:
            raise SessionError(2, f"timeframe {self.cfg.timeframe} not permitted")
        self.bundle = b
        registry = Registry(b.registry)
        costs = CostParams.from_scenario(b.compiled.cost_scenario)
        live = self.cfg.environment == Environment.LIVE
        if live:
            assert self.factory is not None
            adapter = self.factory(b, registry)
            capital = Decimal(0)  # set below from the exchange balance and the cap
        else:
            capital = b.profile.capital.paper_capital_usd
            adapter = SimulatedExecutionAdapter(capital, costs)
        run_id = (
            f"ses-{self.cfg.environment.value}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-"
            f"{secrets.token_hex(3)}"
        )
        configure_logging(data_root() / "logs" / f"{run_id}.jsonl")
        set_log_context(run_id=run_id)
        journal = JournalStore(run_id)
        journal.config_hash = b.compiled.config_hash
        empty: dict[str, list[Any]] = {}
        self.state = RunState(
            compiled=b.compiled,
            profile=b.profile,
            params=risk_params_from_compiled(b.compiled),
            registry=registry,
            costs=costs,
            environment=self.cfg.environment,
            timeframe=self.cfg.timeframe,
            builder=SnapshotBuilder(self.cfg.timeframe),
            eligibility=EligibilityEvaluator(
                b.compiled, b.profile, registry, empty, {}, timedelta(days=1)
            ),
            strategy=build_strategy(self.cfg.strategy, self.cfg.configs_root),
            adapter=adapter,
            execution=ExecutionService(adapter),
            ledger=Ledger(cash=capital),
            loss=LossTracker(capital),
            journal=journal,
        )
        self.state.on_kill_switch = self._persist_kill
        self.state.on_event = self.alerter.on_event
        self.path = state_path(self.cfg.environment, b.profile.profile_id)
        restored = load_state(self.path, self.state)
        if live:
            self.state.reconcile_fn = self._live_reconcile
            if restored is None:
                self._init_live_cash()
        self.meta = restored or {"last_t1": None, "stale_cycles": 0}
        now = self.clock.now()
        journal.append(
            EventType.RUN_STARTED,
            now,
            {
                "session": self.cfg.environment.value,
                "profile": str(self.cfg.profile),
                "restored": restored is not None,
                "cash_usd": str(self.state.ledger.cash),
                "kill_switch_engaged": self.kill.is_engaged(),
            },
            payload_type="SessionStart",
        )
        journal.append(EventType.PROFILE_COMPILED, now, b.compiled)
        self.alerter.send(
            f"session started ({'restored' if restored else 'new'}); "
            f"cash ${self.state.ledger.cash:.2f}; "
            f"positions {sorted(self.state.ledger.positions)}"
        )

    def _init_live_cash(self) -> None:
        """
        First live start: require a clean account for BTC/ETH and cap the managed cash.

        Raises:
            SessionError: If the account already holds BTC or ETH.
        """
        assert self.bundle.live is not None
        bal = self.state.adapter.get_balances()
        held = {k: v for k, v in bal.items() if k != "USD" and v > self.state.adapter.lot_step(k)}
        if held:
            raise SessionError(
                2,
                f"live account already holds {held}; the bot needs an "
                "account (or sub-account) with no BTC/ETH at first start",
            )
        cap = _eff(self.bundle, "live.max_capital_usd")
        cash = min(bal.get("USD", Decimal(0)), cap)
        if cash <= 0:
            raise SessionError(2, "no USD balance on the Kraken account")
        self.state.ledger.cash = cash
        self.state.loss = LossTracker(cash)

    # --- hooks ---------------------------------------------------------------------------
    def _persist_kill(self, reason: str, trigger: str) -> None:
        """
        Persist an automatic kill-switch engagement and alert the owner.

        Args:
            reason (str): Reason.
            trigger (str): Trigger.
        """
        if not self.kill.is_engaged():
            self.kill.engage(reason, self.clock.now(), trigger=trigger)

    def _live_reconcile(self, ledger: Ledger, balances: dict[str, Decimal]) -> list[str]:
        """
        Compare the ledger with Kraken (quantity tolerance = lot size, UD-17).

        Args:
            ledger (Ledger): Ledger.
            balances (dict[str, Decimal]): Exchange balances.

        Returns:
            list[str]: Differences.
        """
        diffs = []
        if balances.get("USD", Decimal(0)) + Decimal("0.01") < ledger.cash:
            diffs.append(f"USD exchange={balances.get('USD')} < ledger cash={ledger.cash}")
        insts = set(ledger.positions) | {k for k in balances if k != "USD"}
        for iid in sorted(insts):
            mine = ledger.positions[iid].quantity if iid in ledger.positions else Decimal(0)
            theirs = balances.get(iid, Decimal(0))
            if abs(mine - theirs) > self.state.adapter.lot_step(iid):
                diffs.append(f"{iid} ledger={mine} exchange={theirs}")
        return diffs

    # --- per-cycle steps -----------------------------------------------------------------
    def _refresh_market(self, t1: datetime, now: datetime) -> list[str]:
        """
        Fetch candles and rebuild the snapshot builder and eligibility evaluator.

        Args:
            t1 (datetime): Decision time.
            now (datetime): Retrieval time.

        Returns:
            list[str]: Instruments that are stale at ``t1``.
        """
        st, b = self.state, self.bundle
        builder = SnapshotBuilder(self.cfg.timeframe)
        daily: dict[str, list[Any]] = {}
        insts = b.profile.universe.instruments_in_scope if b.profile else []
        for iid in insts:
            try:
                bars = self.data.candles(iid, self.cfg.timeframe, now)
                days = self.data.candles(iid, "1d", now)
            except MarketDataError as exc:
                log.error(f"market data: {exc}")
                continue
            if bars:
                builder.add(
                    live_manifest(iid, self.cfg.timeframe, bars, now), candles_to_frame(bars)
                )
            daily[iid] = days
        st.builder = builder
        assert b.profile is not None
        # Reason: Kraken serves 720 candles per timeframe (120 days of 4h), so eligibility
        # history and liquidity (UD-18: 365 days, 30-day median volume) use daily candles.
        st.eligibility = EligibilityEvaluator(
            b.compiled,
            b.profile,
            st.registry,
            daily,
            {i: "kraken" for i in daily},
            timedelta(days=1),
        )
        return [i for i in insts if not builder.snapshot(i, t1, "chk", "chk").is_fresh]

    def _check_clock(self, now: datetime) -> None:
        """
        Engage the kill switch if the local clock drifts from Kraken's (UD-17: 5 s).

        Args:
            now (datetime): Local time.
        """
        tol = _eff(self.bundle, "risk.data_and_execution_faults.clock_skew_tolerance_seconds")
        try:
            skew = abs((self.data.server_time() - now).total_seconds())
        except Exception as exc:  # noqa: BLE001 - counted as stale data instead
            log.error(f"server time unavailable: {exc}")
            return
        if Decimal(str(skew)) > tol:
            cyc.engage(self.state, now, f"clock skew {skew:.1f}s > {tol}s", "clock_skew_exceeded")

    def run_cycle(self, t1: datetime) -> None:
        """
        Run one bar-close cycle at decision time ``t1``.

        Args:
            t1 (datetime): Bar close being processed.
        """
        st = self.state
        now = self.clock.now()
        live = self.cfg.environment == Environment.LIVE
        # FM-15: a profile or risk-config change mid-session halts new orders.
        latest = self._compile()
        if not latest.compiled.runnable or latest.compiled.config_hash != st.compiled.config_hash:
            cyc.engage(
                st,
                now,
                "risk configuration changed or invalid mid-session",
                "risk_config_invalid_mid_session",
            )
        # The persisted kill switch is the source of truth (owner CLI or automation).
        persisted = self.kill.state()
        if persisted is not None and persisted.state == "engaged":
            st.controls.kill_switch.engage(persisted.reason, "persisted")
        elif st.controls.kill_switch.engaged:
            st.controls.kill_switch.disengage("owner disengaged persisted switch", by_owner=True)
        self._check_clock(now)
        stale = self._refresh_market(t1, now)
        for _ in range(STALE_RETRIES):
            if not stale:
                break
            self.sleep(30)
            stale = self._refresh_market(t1, self.clock.now())
        t0 = t1 - self.delta
        if live:
            cyc.process_stops(st, t0)
            if st.adapter.missing_stops:
                cyc.engage(
                    st,
                    now,
                    f"protective stop missing at Kraken: {st.adapter.missing_stops}",
                    "reconciliation_mismatch",
                )
                st.adapter.missing_stops.clear()
            cyc.process_open(st, t0)
            cyc.reconcile(st, t1)
        else:
            cyc.process_open(st, t0)
            cyc.process_stops(st, t0)
        cyc.mark_to_market(st, t1)
        cyc.run_cycle(st, t1)
        if live:
            cyc.process_open(st, t1)  # confirm fills now and place protective stops
        self.meta["stale_cycles"] = self.meta.get("stale_cycles", 0) + 1 if stale else 0
        esc = _eff(
            self.bundle,
            "risk.data_and_execution_faults.stale_data.escalate_to_kill_switch_after_stale_cycles",
        )
        if self.meta["stale_cycles"] >= esc:
            cyc.engage(
                st,
                now,
                f"stale data for {self.meta['stale_cycles']} cycles: {stale}",
                "persistent_stale_data",
            )
        if not live and st.profile is not None:
            self.store.record_paper_cycle(st.profile.profile_id, st.profile.version, t1)
        self.meta["last_t1"] = format_utc(t1)
        self.meta["last_cycle_wall_utc"] = format_utc(now)
        self.meta["equity_usd"] = str(st.ledger.equity)
        self._save()

    def _save(self) -> None:
        """Persist session state."""
        self.meta["environment"] = self.cfg.environment.value
        self.meta["kill_switch_engaged"] = self.state.controls.kill_switch.engaged
        save_state(self.path, self.state, self.meta)

    # --- scheduling ----------------------------------------------------------------------
    def due_times(self, now: datetime) -> list[datetime]:
        """
        Bar closes to process now (paper catches up a few bars; live only the latest).

        Args:
            now (datetime): Wall time.

        Returns:
            list[datetime]: Decision times, oldest first.
        """
        grace = timedelta(
            seconds=float(
                _eff(self.bundle, "risk.data_and_execution_faults.stale_data.paper_grace_seconds")
            )
        )
        step = int(self.delta.total_seconds())
        avail = now - grace
        latest = datetime.fromtimestamp(int(avail.timestamp()) // step * step, tz=UTC)
        last = self.meta.get("last_t1")
        if last is None:
            return [latest]
        prev = parse_utc(last)
        if latest <= prev:
            return []
        if self.cfg.environment == Environment.LIVE:
            return [latest]
        times = []
        t = prev + self.delta
        while t <= latest:
            times.append(t)
            t += self.delta
        return times[-PAPER_CATCHUP_BARS:]

    def handle_owner_requests(self) -> None:
        """Execute queued owner commands (flatten, breaker reset)."""
        now = self.clock.now()
        req = self.store.pending_request("reset_breaker")
        if req is not None:
            self.state.controls.breaker.reset(req[1], by_owner=True)
            self.store.mark_request_handled(req[0], now, "breaker reset")
            self.alerter.send(f"circuit breaker reset by owner: {req[1]}")
            self._save()
        req = self.store.pending_request("flatten")
        if req is None:
            return
        last = self.meta.get("last_t1")
        if last is None:
            self.store.mark_request_handled(req[0], now, "no cycle processed yet")
            return
        t = parse_utc(last)
        self._refresh_market(t, now)
        outcomes = flatten_all(self.state, t, req[1])
        if self.cfg.environment == Environment.LIVE:
            cyc.process_open(self.state, t)
        self.store.mark_request_handled(req[0], now, "; ".join(outcomes))
        self.alerter.send("owner flatten: " + "; ".join(outcomes))
        self._save()

    def tick(self) -> None:
        """Process owner requests and any due cycles."""
        self.handle_owner_requests()
        for t1 in self.due_times(self.clock.now()):
            set_log_context(cycle_id=None, correlation_id=None)
            self.run_cycle(t1)

    def run_forever(
        self, should_stop: Callable[[], bool] = lambda: False, tick_seconds: float = 30.0
    ) -> None:
        """
        Main loop. Errors inside a tick engage the kill switch and keep the loop alive.

        Args:
            should_stop (Callable[[], bool]): Stop condition (signals set it).
            tick_seconds (float): Seconds between checks.
        """
        while not should_stop():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - halt trading, keep monitoring
                log.exception("session tick failed")
                self._persist_kill(
                    f"session error: {type(exc).__name__}: {exc}", "repeated_execution_errors"
                )
                self.state.controls.kill_switch.engage(str(exc), "session_error")
                self.alerter.send(f"ERROR, kill switch engaged: {type(exc).__name__}: {exc}")
            self.sleep(tick_seconds)
        self.state.journal.close()
