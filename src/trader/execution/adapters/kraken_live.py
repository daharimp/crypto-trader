"""Kraken spot adapter for the ``live`` environment (ADR-023). Real money.

Talks to Kraken through ``ccxt`` with the owner's API key, which must allow trading and
balance queries only (never withdrawals). Spot only: the order parameters this module can
send are allowlisted (no leverage, margin, or reduce-only flags), and every buy is capped by
the owner-approved ``max_capital_usd``. It mirrors the simulator's interface, so the decision
cycle code is the same in backtest, paper, and live (T-50).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from trader.common.ids import IdGenerator
from trader.domain.candles import Candle
from trader.domain.enums import (
    Environment,
    ExecutionStatus,
    OrderPurpose,
    OrderType,
    ReasonCode,
    Side,
)
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent

from .kraken_support import (  # noqa: F401  (re-exported for callers and tests)
    _ALLOWED_PARAMS,
    _OPEN,
    ADAPTER_ID,
    LiveAdapterError,
    _d,
    _LiveOrder,
    userref_for,
)


class KrakenLiveAdapter:
    """Real-money Kraken spot adapter."""

    adapter_id = ADAPTER_ID
    adapter_version = "1.0.0"
    venue = "kraken"

    def __init__(
        self,
        client: Any,
        symbols: dict[str, str],
        max_capital_usd: Decimal,
        fee_rate_pct: Decimal,
        poll_seconds: float = 2.0,
        poll_timeout_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """
        Create the adapter.

        Args:
            client (Any): Authenticated ``ccxt.kraken`` instance (tests inject a fake).
            symbols (dict[str, str]): Instrument ID -> ccxt symbol (e.g. ``BTC/USD``).
            max_capital_usd (Decimal): Owner-approved cap (UD-22); no buy may exceed it.
            fee_rate_pct (Decimal): Assumed fee rate for reports when Kraken omits the fee.
            poll_seconds (float): Delay between fill checks.
            poll_timeout_seconds (float): How long to wait for a market order to fill.
            sleep (Callable[[float], None]): Sleep function (tests pass a no-op).
        """
        if max_capital_usd <= 0:
            raise LiveAdapterError("max_capital_usd must be approved and > 0")
        self.client = client
        self.symbols = symbols
        self.max_capital_usd = max_capital_usd
        self.fee_rate_pct = fee_rate_pct
        self.poll_seconds = poll_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self.sleep = sleep
        self._orders: dict[str, _LiveOrder] = {}
        self._ids = IdGenerator()
        self.missing_stops: list[str] = []
        self.last_error: str | None = None
        self.markets: dict[str, Any] = client.load_markets()

    # --- helpers -----------------------------------------------------------------------
    def _symbol(self, instrument_id: str) -> str:
        """
        Map an instrument to its ccxt symbol.

        Args:
            instrument_id (str): Instrument.

        Returns:
            str: ccxt symbol.

        Raises:
            LiveAdapterError: If the instrument has no Kraken mapping.
        """
        if instrument_id not in self.symbols:
            raise LiveAdapterError(f"no Kraken symbol for {instrument_id}")
        return self.symbols[instrument_id]

    def min_amount(self, instrument_id: str) -> Decimal:
        """
        Kraken's minimum order amount for an instrument.

        Args:
            instrument_id (str): Instrument.

        Returns:
            Decimal: Minimum base quantity (0 if unknown).
        """
        m = self.markets.get(self._symbol(instrument_id), {})
        return _d(((m.get("limits") or {}).get("amount") or {}).get("min"))

    def lot_step(self, instrument_id: str) -> Decimal:
        """
        Quantity precision step (the approved reconciliation tolerance, UD-17).

        Args:
            instrument_id (str): Instrument.

        Returns:
            Decimal: Step, e.g. ``0.00000001``.
        """
        m = self.markets.get(self._symbol(instrument_id), {})
        p = (m.get("precision") or {}).get("amount")
        if p is None:
            return Decimal("0.00000001")
        # Reason: ccxt reports precision either as a step (0.0001) or as decimal places (4).
        pd = _d(p)
        return pd if pd < 1 else Decimal(1).scaleb(-int(pd))

    def _send(self, symbol: str, side: str, amount: Decimal, params: dict[str, Any]) -> Any:
        """
        Submit one spot market order with allowlisted parameters only.

        Args:
            symbol (str): ccxt symbol.
            side (str): ``buy`` or ``sell``.
            amount (Decimal): Base quantity.
            params (dict[str, Any]): Kraken parameters.

        Returns:
            Any: ccxt order structure.

        Raises:
            LiveAdapterError: If a parameter outside the allowlist is passed.
        """
        extra = set(params) - _ALLOWED_PARAMS
        if extra:
            raise LiveAdapterError(f"order parameters not allowed: {sorted(extra)}")
        return self.client.create_order(symbol, "market", side, float(amount), None, params)

    def _report(
        self,
        intent: OrderIntent,
        status: ExecutionStatus,
        *,
        reason: ReasonCode | None = None,
        qty: Decimal = Decimal(0),
        price: Decimal | None = None,
        fee: Decimal = Decimal(0),
        filled_at: datetime | None = None,
    ) -> ExecutionReport:
        """
        Build an execution report.

        Args:
            intent (OrderIntent): Intent.
            status (ExecutionStatus): Status.
            reason (ReasonCode | None): Reason code.
            qty (Decimal): Filled quantity.
            price (Decimal | None): Average fill price.
            fee (Decimal): Fee in USD.
            filled_at (datetime | None): Fill time.

        Returns:
            ExecutionReport: Report.
        """
        return ExecutionReport(
            schema_version="1.0.0",
            execution_report_id=self._ids.next("kxr"),
            order_intent_id=intent.order_intent_id,
            correlation_id=intent.correlation_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            venue=self.venue,
            status=status,
            reason_code=reason,
            filled_quantity=qty,
            average_fill_price=price,
            expected_price=intent.reference_price,
            fees_usd=fee,
            fee_rate_pct=self.fee_rate_pct,
            slippage_bps_assumed=Decimal(0),
            slippage_usd=abs(price - intent.reference_price) * qty if price else Decimal(0),
            submitted_at_utc=intent.created_at_utc,
            filled_at_utc=filled_at,
            fill_bar_open_time_utc=None,
            latency_ms=0,
        )

    def validate_only(
        self, instrument_id: str, side: str, amount: Decimal, stop_price: Decimal | None = None
    ) -> Any:
        """
        Ask Kraken to validate an order WITHOUT placing it (``validate=true``; preflight).

        Args:
            instrument_id (str): Instrument.
            side (str): ``buy`` or ``sell``.
            amount (Decimal): Base quantity.
            stop_price (Decimal | None): Stop-loss trigger for a stop-shape check.

        Returns:
            Any: Kraken's response (raises the ccxt error on rejection).
        """
        params: dict[str, Any] = {"validate": True, "oflags": "fciq"}
        if stop_price is not None:
            params["stopLossPrice"] = float(stop_price)
        return self._send(self._symbol(instrument_id), side, amount, params)

    # --- interface ---------------------------------------------------------------------
    def validate_order(self, intent: OrderIntent) -> list[str]:
        """
        Client-side checks before anything reaches Kraken.

        Args:
            intent (OrderIntent): Intent.

        Returns:
            list[str]: Problems (reason code names).
        """
        problems: list[str] = []
        if intent.funds != "real" or intent.environment != Environment.LIVE:
            problems.append(ReasonCode.ADAPTER_NOT_ALLOWED.value)
        if intent.instrument_id not in self.symbols:
            problems.append(ReasonCode.ASSET_NOT_SUPPORTED.value)
            return problems
        if intent.quantity < self.min_amount(intent.instrument_id):
            problems.append(ReasonCode.SIZE_BELOW_MINIMUM.value)
        if intent.side == Side.BUY and intent.notional_estimate_usd > self.max_capital_usd:
            problems.append(ReasonCode.EXCESSIVE_SIZE.value)
        step = self.lot_step(intent.instrument_id)
        if intent.quantity != intent.quantity.quantize(step, rounding=ROUND_DOWN):
            problems.append(ReasonCode.EXCESSIVE_SIZE.value)
        return problems

    def submit_order(self, intent: OrderIntent) -> ExecutionReport:
        """
        Send a market order (entry/exit) or a resting stop-loss (protective stop).

        Args:
            intent (OrderIntent): Gate-approved intent.

        Returns:
            ExecutionReport: ``accepted`` or ``rejected``.
        """
        problems = self.validate_order(intent)
        if problems:
            return self._report(intent, ExecutionStatus.REJECTED, reason=ReasonCode(problems[0]))
        symbol = self._symbol(intent.instrument_id)
        ref = userref_for(intent)
        params: dict[str, Any] = {"oflags": "fciq", "userref": ref}
        if intent.order_type == OrderType.STOP_MARKET:
            assert intent.stop_price is not None
            params["stopLossPrice"] = float(intent.stop_price)
        try:
            order = self._send(symbol, intent.side.value, intent.quantity, params)
            exchange_id = str(order.get("id")) if order.get("id") else None
        except Exception as exc:  # noqa: BLE001 - network errors must not crash the session
            exchange_id = self._find_by_userref(symbol, ref)
            if exchange_id is None:
                rep = self._report(
                    intent, ExecutionStatus.REJECTED, reason=ReasonCode.EXCHANGE_ERROR
                )
                self.last_error = f"{type(exc).__name__}: {exc}"
                return rep
        rep = self._report(intent, ExecutionStatus.ACCEPTED)
        self._orders[intent.order_intent_id] = _LiveOrder(intent, exchange_id, rep)
        return rep

    def _find_by_userref(self, symbol: str, ref: int) -> str | None:
        """
        Look for an order Kraken may have accepted despite a client-side error.

        Args:
            symbol (str): ccxt symbol.
            ref (int): userref.

        Returns:
            str | None: Exchange order ID if found.
        """
        for fetch in (self.client.fetch_open_orders, self.client.fetch_closed_orders):
            try:
                for o in fetch(symbol, None, None, {"userref": ref}):
                    if o.get("id"):
                        return str(o["id"])
            except Exception:  # noqa: BLE001, S112 - best effort only
                continue
        return None

    def cancel_order(self, order_intent_id: str) -> ExecutionReport:
        """
        Cancel an open order at Kraken.

        Args:
            order_intent_id (str): Order ID.

        Returns:
            ExecutionReport: ``canceled`` (or the existing final report).
        """
        o = self._orders[order_intent_id]
        if o.report.status in _OPEN and o.exchange_id:
            self.client.cancel_order(o.exchange_id, self._symbol(o.intent.instrument_id))
            o.report = self._report(o.intent, ExecutionStatus.CANCELED)
        return o.report

    def get_order(self, order_intent_id: str) -> ExecutionReport:
        """
        Latest report for an order.

        Args:
            order_intent_id (str): Order ID.

        Returns:
            ExecutionReport: Report.
        """
        return self._orders[order_intent_id].report

    def list_open_orders(self) -> list[ExecutionReport]:
        """
        Orders not yet final.

        Returns:
            list[ExecutionReport]: Open orders.
        """
        return [o.report for _, o in sorted(self._orders.items()) if o.report.status in _OPEN]

    def get_balances(self) -> dict[str, Decimal]:
        """
        Exchange balances keyed like the ledger (``USD`` and instrument IDs).

        Returns:
            dict[str, Decimal]: Balances.
        """
        total = self.client.fetch_balance().get("total", {})
        out = {"USD": _d(total.get("USD"))}
        for inst, sym in sorted(self.symbols.items()):
            qty = _d(total.get(sym.split("/")[0]))
            if qty != 0:
                out[inst] = qty
        return out

    # --- fill synchronisation (same call points as the simulator) -----------------------
    def _final_report(self, o: _LiveOrder, wait: bool) -> ExecutionReport | None:
        """
        Poll Kraken for an order's outcome.

        Args:
            o (_LiveOrder): Order.
            wait (bool): Keep polling until final or timeout.

        Returns:
            ExecutionReport | None: Final report, or None if still open.
        """
        if o.exchange_id is None:
            return self._report(o.intent, ExecutionStatus.ERROR, reason=ReasonCode.EXCHANGE_ERROR)
        deadline = time.monotonic() + (self.poll_timeout_seconds if wait else 0)
        symbol = self._symbol(o.intent.instrument_id)
        while True:
            info = self.client.fetch_order(o.exchange_id, symbol)
            status = info.get("status")
            if status in ("closed", "canceled", "expired", "rejected"):
                break
            if time.monotonic() >= deadline:
                return None
            self.sleep(self.poll_seconds)
        filled = _d(info.get("filled"))
        ts = info.get("timestamp")
        at = datetime.fromtimestamp(ts / 1000, tz=UTC) if ts else None
        if filled > 0:
            price = _d(info.get("average") or info.get("price"))
            fee_info = info.get("fee") or {}
            fee = (
                _d(fee_info.get("cost"))
                if fee_info.get("currency") in (None, "USD")
                else Decimal(0)
            )
            return self._report(
                o.intent, ExecutionStatus.FILLED, qty=filled, price=price, fee=fee, filled_at=at
            )
        mapped = {"canceled": ExecutionStatus.CANCELED, "expired": ExecutionStatus.EXPIRED}
        return self._report(
            o.intent,
            mapped.get(str(status), ExecutionStatus.REJECTED),
            reason=ReasonCode.EXCHANGE_ERROR,
        )

    def fill_market_orders(
        self, bars: dict[str, Candle | None], open_time: datetime
    ) -> list[tuple[OrderIntent, ExecutionReport]]:
        """
        Confirm fills of submitted market orders (exits first), waiting up to the timeout.

        Args:
            bars (dict[str, Candle | None]): Unused (fills come from Kraken).
            open_time (datetime): Unused; kept for interface parity with the simulator.

        Returns:
            list[tuple[OrderIntent, ExecutionReport]]: Final reports.
        """
        due = [
            o
            for o in self._orders.values()
            if o.report.status in _OPEN and o.intent.order_type == OrderType.MARKET
        ]
        due.sort(key=lambda o: (o.intent.side != Side.SELL, o.intent.order_intent_id))
        out = []
        for o in due:
            rep = self._final_report(o, wait=True)
            if rep is not None:
                o.report = rep
                out.append((o.intent, rep))
        return out

    def trigger_stops(
        self, bars: dict[str, Candle | None]
    ) -> list[tuple[OrderIntent, ExecutionReport]]:
        """
        Report resting stop-losses that Kraken has executed. A stop that disappeared
        without filling is recorded in ``missing_stops`` (the session halts on it).

        Args:
            bars (dict[str, Candle | None]): Unused.

        Returns:
            list[tuple[OrderIntent, ExecutionReport]]: Stop fills.
        """
        out = []
        for _, o in sorted(self._orders.items()):
            if o.report.status not in _OPEN or o.intent.order_type != OrderType.STOP_MARKET:
                continue
            rep = self._final_report(o, wait=False)
            if rep is None:
                continue
            o.report = rep
            if rep.status == ExecutionStatus.FILLED:
                out.append((o.intent, rep))
            elif o.intent.purpose == OrderPurpose.PROTECTIVE_STOP:
                self.missing_stops.append(o.intent.order_intent_id)
        return out

    # --- persistence across restarts ---------------------------------------------------
    def export_state(self) -> dict[str, Any]:
        """
        Serializable adapter state.

        Returns:
            dict[str, Any]: State.
        """
        return {
            "orders": {
                k: {
                    "intent": o.intent.model_dump(mode="json"),
                    "exchange_id": o.exchange_id,
                    "report": o.report.model_dump(mode="json"),
                }
                for k, o in self._orders.items()
            },
            "ids": dict(self._ids._counters),
        }

    def load_state(self, data: dict[str, Any]) -> None:
        """
        Restore adapter state saved by :meth:`export_state`.

        Args:
            data (dict[str, Any]): State.
        """
        for k, v in data.get("orders", {}).items():
            self._orders[k] = _LiveOrder(
                OrderIntent.model_validate(v["intent"]),
                v["exchange_id"],
                ExecutionReport.model_validate(v["report"]),
            )
        self._ids._counters.update(data.get("ids", {}))
