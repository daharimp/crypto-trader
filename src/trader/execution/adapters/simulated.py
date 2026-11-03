"""Deterministic bar-replay simulator (handoff §7.9, R-03).

Market orders fill at the next bar's open with slippage, clamped to the bar range. Stops
fill at ``min(stop, open)`` with slippage when the bar's low touches the stop. No partial
fills in M1. Rejects anything that is not simulated funds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trader.common.ids import IdGenerator
from trader.domain.candles import Candle
from trader.domain.enums import ExecutionStatus, OrderPurpose, OrderType, ReasonCode, Side
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent
from trader.execution.costs import CostParams

_OPEN = (ExecutionStatus.ACCEPTED, ExecutionStatus.OPEN)


@dataclass
class _Order:
    """Adapter-side order state."""

    intent: OrderIntent
    report: ExecutionReport


class SimulatedExecutionAdapter:
    """In-memory simulated venue with its own balances (for reconciliation)."""

    adapter_id = "simulated"
    adapter_version = "1.0.0"
    venue = "sim"

    def __init__(self, capital: Decimal, costs: CostParams) -> None:
        """
        Create the simulator.

        Args:
            capital (Decimal): Starting simulated cash.
            costs (CostParams): Cost scenario.
        """
        self.costs = costs
        self.cash = capital
        self.holdings: dict[str, Decimal] = {}
        self._orders: dict[str, _Order] = {}
        self._ids = IdGenerator()

    # --- interface ---------------------------------------------------------------------
    def validate_order(self, intent: OrderIntent) -> list[str]:
        """
        Check simulator constraints.

        Args:
            intent (OrderIntent): Intent.

        Returns:
            list[str]: Problems (reason code names).
        """
        problems: list[str] = []
        if intent.funds != "simulated":
            problems.append(ReasonCode.ADAPTER_NOT_ALLOWED.value)
        if (
            intent.purpose != OrderPurpose.PROTECTIVE_STOP
            and intent.quantity * intent.reference_price < self.costs.min_notional_usd
        ):
            problems.append(ReasonCode.SIZE_BELOW_MINIMUM.value)
        return problems

    def submit_order(self, intent: OrderIntent) -> ExecutionReport:
        """
        Accept an order (fills happen when the runner feeds bars).

        Args:
            intent (OrderIntent): Gate-approved intent.

        Returns:
            ExecutionReport: ``accepted`` or ``rejected``.
        """
        problems = self.validate_order(intent)
        status = ExecutionStatus.REJECTED if problems else ExecutionStatus.ACCEPTED
        code = ReasonCode(problems[0]) if problems else None
        rep = self._report(intent, status, intent.created_at_utc, reason=code)
        if not problems:
            self._orders[intent.order_intent_id] = _Order(intent, rep)
        return rep

    def cancel_order(self, order_intent_id: str) -> ExecutionReport:
        """
        Cancel an open order.

        Args:
            order_intent_id (str): Order ID.

        Returns:
            ExecutionReport: ``canceled`` (or the existing final report).
        """
        o = self._orders[order_intent_id]
        if o.report.status in _OPEN:
            o.report = self._report(o.intent, ExecutionStatus.CANCELED, o.report.submitted_at_utc)
        return o.report

    def get_order(self, order_intent_id: str) -> ExecutionReport:
        """
        Return the latest report.

        Args:
            order_intent_id (str): Order ID.

        Returns:
            ExecutionReport: Report.
        """
        return self._orders[order_intent_id].report

    def list_open_orders(self) -> list[ExecutionReport]:
        """
        Return open orders sorted by ID.

        Returns:
            list[ExecutionReport]: Open orders.
        """
        return [o.report for k, o in sorted(self._orders.items()) if o.report.status in _OPEN]

    def get_balances(self) -> dict[str, Decimal]:
        """
        Return simulator balances.

        Returns:
            dict[str, Decimal]: ``USD`` cash and holdings per instrument.
        """
        return {"USD": self.cash, **{k: v for k, v in sorted(self.holdings.items()) if v != 0}}

    # --- bar-driven processing ---------------------------------------------------------
    def fill_market_orders(
        self, bars: dict[str, Candle | None], open_time: datetime
    ) -> list[tuple[OrderIntent, ExecutionReport]]:
        """
        Fill market orders decided at ``open_time`` at this bar's open (exits first).

        Args:
            bars (dict[str, Candle | None]): Bar opening at ``open_time`` per instrument.
            open_time (datetime): Fill bar open time.

        Returns:
            list[tuple[OrderIntent, ExecutionReport]]: Final reports.
        """
        due = [
            o
            for o in self._orders.values()
            if o.report.status in _OPEN
            and o.intent.order_type in (OrderType.MARKET, OrderType.LIMIT)
            and o.intent.decision_time_utc <= open_time
        ]
        # Reason: exits release cash before entries use it; ties break by instrument and ID.
        due.sort(
            key=lambda o: (
                o.intent.side != Side.SELL,
                o.intent.instrument_id,
                o.intent.order_intent_id,
            )
        )
        out = []
        for o in due:
            bar = bars.get(o.intent.instrument_id)
            if bar is None or o.intent.decision_time_utc != open_time:
                o.report = self._report(
                    o.intent,
                    ExecutionStatus.EXPIRED,
                    o.report.submitted_at_utc,
                    reason=ReasonCode.INTENT_EXPIRED,
                )
            elif o.intent.order_type == OrderType.LIMIT:
                o.report = self._fill_limit(o, bar)
            else:
                slip = self.costs.slippage
                raw = bar.open * (1 + slip) if o.intent.side == Side.BUY else bar.open * (1 - slip)
                o.report = self._fill(o.intent, o.report, self._clamp(raw, bar), bar)
            out.append((o.intent, o.report))
        return out

    def _fill_limit(self, o: _Order, bar: Candle) -> ExecutionReport:
        """
        Pessimistic post-only limit model for one bar.

        A buy limit fills only if the bar trades strictly below it; if the bar opens at or
        below the limit, a post-only order would have crossed, so it is treated as not
        filled (Kraken rejects crossing post-only orders). Sells mirror this. Fills happen at
        the limit price with the maker fee and no slippage.

        Args:
            o (_Order): Order.
            bar (Candle): The bar after the decision.

        Returns:
            ExecutionReport: ``filled`` or ``expired`` (``LIMIT_NOT_FILLED``).
        """
        lim = o.intent.limit_price
        assert lim is not None
        buy = o.intent.side == Side.BUY
        crossed = bar.open <= lim if buy else bar.open >= lim
        traded = bar.low < lim if buy else bar.high > lim
        if crossed or not traded:
            return self._report(
                o.intent,
                ExecutionStatus.EXPIRED,
                o.report.submitted_at_utc,
                reason=ReasonCode.LIMIT_NOT_FILLED,
            )
        return self._fill(o.intent, o.report, lim, bar, fee_rate=self.costs.maker_fee_rate)

    def trigger_stops(
        self, bars: dict[str, Candle | None]
    ) -> list[tuple[OrderIntent, ExecutionReport]]:
        """
        Fill resting protective stops whose bar low touches the stop price.

        Args:
            bars (dict[str, Candle | None]): Current bar per instrument.

        Returns:
            list[tuple[OrderIntent, ExecutionReport]]: Stop fills.
        """
        out = []
        for _, o in sorted(self._orders.items()):
            bar = bars.get(o.intent.instrument_id)
            sp = o.intent.stop_price
            if (
                o.report.status not in _OPEN
                or o.intent.order_type != OrderType.STOP_MARKET
                or bar is None
                or sp is None
                or bar.low > sp
            ):
                continue
            raw = min(sp, bar.open) * (1 - self.costs.slippage)
            o.report = self._fill(o.intent, o.report, self._clamp(raw, bar), bar)
            out.append((o.intent, o.report))
        return out

    # --- helpers -----------------------------------------------------------------------
    @staticmethod
    def _clamp(price: Decimal, bar: Candle) -> Decimal:
        """
        Clamp a fill price to the bar range.

        Args:
            price (Decimal): Raw price.
            bar (Candle): Bar.

        Returns:
            Decimal: Clamped price.
        """
        return min(max(price, bar.low), bar.high)

    def _fill(
        self,
        intent: OrderIntent,
        prev: ExecutionReport,
        price: Decimal,
        bar: Candle,
        fee_rate: Decimal | None = None,
    ) -> ExecutionReport:
        """
        Apply a fill to simulator balances, enforcing spot constraints.

        Args:
            intent (OrderIntent): Intent.
            prev (ExecutionReport): Previous report.
            price (Decimal): Fill price.
            bar (Candle): Fill bar.
            fee_rate (Decimal | None): Fee fraction override (maker fee for limit fills).

        Returns:
            ExecutionReport: ``filled`` or ``rejected``.
        """
        qty = intent.quantity
        notional = qty * price
        fee = notional * (self.costs.fee_rate if fee_rate is None else fee_rate)
        held = self.holdings.get(intent.instrument_id, Decimal(0))
        if (intent.side == Side.BUY and notional + fee > self.cash) or (
            intent.side == Side.SELL and qty > held
        ):
            return self._report(
                intent,
                ExecutionStatus.REJECTED,
                prev.submitted_at_utc,
                reason=ReasonCode.SPOT_CONSTRAINT_VIOLATION,
            )
        if intent.side == Side.BUY:
            self.cash -= notional + fee
            self.holdings[intent.instrument_id] = held + qty
        else:
            self.cash += notional - fee
            self.holdings[intent.instrument_id] = held - qty
        return self._report(
            intent,
            ExecutionStatus.FILLED,
            prev.submitted_at_utc,
            qty=qty,
            price=price,
            fee=fee,
            bar=bar,
        )

    def _report(
        self,
        intent: OrderIntent,
        status: ExecutionStatus,
        submitted: datetime,
        reason: ReasonCode | None = None,
        qty: Decimal = Decimal(0),
        price: Decimal | None = None,
        fee: Decimal = Decimal(0),
        bar: Candle | None = None,
    ) -> ExecutionReport:
        """
        Build an execution report.

        Args:
            intent (OrderIntent): Intent.
            status (ExecutionStatus): Status.
            submitted (datetime): Submission time.
            reason (ReasonCode | None): Reason code.
            qty (Decimal): Filled quantity.
            price (Decimal | None): Fill price.
            fee (Decimal): Fee.
            bar (Candle | None): Fill bar.

        Returns:
            ExecutionReport: Report.
        """
        expected = (
            intent.stop_price
            if intent.order_type == OrderType.STOP_MARKET and intent.stop_price is not None
            else (bar.open if bar else intent.reference_price)
        )
        limit = intent.order_type == OrderType.LIMIT
        return ExecutionReport(
            schema_version="1.0.0",
            execution_report_id=self._ids.next("exr"),
            order_intent_id=intent.order_intent_id,
            correlation_id=intent.correlation_id,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            venue=self.venue,
            status=status,
            reason_code=reason,
            filled_quantity=qty,
            average_fill_price=price,
            expected_price=expected,
            fees_usd=fee,
            fee_rate_pct=(self.costs.maker_fee_rate * 100 if limit else self.costs.fee_rate_pct),
            slippage_bps_assumed=self.costs.slippage_bps,
            # Reason: a limit fills at its own price by construction, so it has no slippage.
            slippage_usd=(
                abs(price - bar.open) * qty
                if price is not None and bar and not limit
                else Decimal(0)
            ),
            submitted_at_utc=submitted,
            filled_at_utc=bar.open_time_utc if bar and status == ExecutionStatus.FILLED else None,
            fill_bar_open_time_utc=bar.open_time_utc if bar else None,
            latency_ms=0,
        )

    # --- persistence across restarts (forward paper sessions) ---------------------------
    def export_state(self) -> dict[str, object]:
        """
        Serializable simulator state.

        Returns:
            dict[str, object]: State.
        """
        return {
            "cash": str(self.cash),
            "holdings": {k: str(v) for k, v in self.holdings.items()},
            "orders": {
                k: {
                    "intent": o.intent.model_dump(mode="json"),
                    "report": o.report.model_dump(mode="json"),
                }
                for k, o in self._orders.items()
            },
            "ids": dict(self._ids._counters),
        }

    def load_state(self, data: dict[str, object]) -> None:
        """
        Restore state saved by :meth:`export_state`.

        Args:
            data (dict[str, object]): State.
        """
        self.cash = Decimal(str(data["cash"]))
        holdings = data.get("holdings", {})
        assert isinstance(holdings, dict)
        self.holdings = {k: Decimal(str(v)) for k, v in holdings.items()}
        orders = data.get("orders", {})
        assert isinstance(orders, dict)
        for k, v in orders.items():
            self._orders[k] = _Order(
                OrderIntent.model_validate(v["intent"]), ExecutionReport.model_validate(v["report"])
            )
        ids = data.get("ids", {})
        assert isinstance(ids, dict)
        self._ids._counters.update(ids)
