"""Portfolio ledger, mark-to-market, PositionSnapshot, reconciliation (§7.10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from trader.domain.enums import ExecutionStatus, Side, Sleeve
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent
from trader.domain.positions import PositionLine, PositionSnapshot

HUNDRED = Decimal(100)


class SpotConstraintError(ValueError):
    """Raised if a fill would make cash or a holding negative (never allowed)."""


@dataclass
class _Position:
    """Open position state."""

    quantity: Decimal
    avg_entry_price: Decimal
    cost_basis_usd: Decimal  # includes entry fees
    opened_at: datetime
    tier: str
    owners: list[str]
    stop_price: Decimal | None = None
    mark: Decimal = Decimal(0)


@dataclass
class ClosedTrade:
    """A round trip for metrics and cooldowns."""

    instrument_id: str
    strategy_ids: list[str]
    opened_at: datetime
    closed_at: datetime
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    pnl_usd: Decimal


@dataclass
class Ledger:
    """Cash and positions as the system believes them to be."""

    cash: Decimal
    positions: dict[str, _Position] = field(default_factory=dict)
    realized_pnl: dict[str, Decimal] = field(default_factory=dict)
    trades: list[ClosedTrade] = field(default_factory=list)
    fees_usd: Decimal = Decimal(0)
    slippage_usd: Decimal = Decimal(0)

    def apply_fill(
        self, intent: OrderIntent, report: ExecutionReport, tier: str
    ) -> ClosedTrade | None:
        """
        Apply a filled execution report.

        Args:
            intent (OrderIntent): The order.
            report (ExecutionReport): Its fill.
            tier (str): Instrument tier.

        Returns:
            ClosedTrade | None: The closed trade if this fill closed a position.

        Raises:
            SpotConstraintError: If cash or holdings would go negative.
        """
        if report.status != ExecutionStatus.FILLED or report.average_fill_price is None:
            return None
        qty, price, fee = report.filled_quantity, report.average_fill_price, report.fees_usd
        iid = intent.instrument_id
        self.fees_usd += fee
        self.slippage_usd += report.slippage_usd
        pos = self.positions.get(iid)
        if intent.side == Side.BUY:
            cost = qty * price + fee
            if cost > self.cash:
                raise SpotConstraintError("buy beyond available cash")
            self.cash -= cost
            owners = [v.id for v in intent.strategy_versions]
            if pos is None:
                self.positions[iid] = _Position(
                    qty,
                    price,
                    cost,
                    report.filled_at_utc or intent.decision_time_utc,
                    tier,
                    owners,
                    mark=price,
                )
            else:
                total = pos.quantity + qty
                pos.avg_entry_price = (pos.avg_entry_price * pos.quantity + price * qty) / total
                pos.quantity, pos.cost_basis_usd = total, pos.cost_basis_usd + cost
                pos.owners = sorted(set(pos.owners) | set(owners))
            return None
        if pos is None or qty > pos.quantity:
            raise SpotConstraintError("sell beyond held quantity")
        proceeds = qty * price - fee
        basis = pos.cost_basis_usd * qty / pos.quantity
        pnl = proceeds - basis
        self.cash += proceeds
        self.realized_pnl[iid] = self.realized_pnl.get(iid, Decimal(0)) + pnl
        pos.quantity -= qty
        pos.cost_basis_usd -= basis
        trade = ClosedTrade(
            iid,
            list(pos.owners),
            pos.opened_at,
            report.filled_at_utc or intent.decision_time_utc,
            qty,
            pos.avg_entry_price,
            price,
            pnl,
        )
        self.trades.append(trade)
        if pos.quantity == 0:
            del self.positions[iid]
        return trade

    def set_stop(self, instrument_id: str, stop_price: Decimal | None) -> None:
        """
        Record the resting stop price for a position.

        Args:
            instrument_id (str): Instrument.
            stop_price (Decimal | None): Stop price.
        """
        if instrument_id in self.positions:
            self.positions[instrument_id].stop_price = stop_price

    def mark(self, closes: dict[str, Decimal]) -> None:
        """
        Update mark prices.

        Args:
            closes (dict[str, Decimal]): Latest close per instrument.
        """
        for iid, pos in self.positions.items():
            if iid in closes:
                pos.mark = closes[iid]

    @property
    def equity(self) -> Decimal:
        """
        Cash plus marked market value.

        Returns:
            Decimal: Equity.
        """
        return self.cash + sum((p.quantity * p.mark for p in self.positions.values()), Decimal(0))

    def reconcile(self, balances: dict[str, Decimal]) -> list[str]:
        """
        Compare ledger cash and quantities with adapter balances (exact match).

        Args:
            balances (dict[str, Decimal]): Adapter balances.

        Returns:
            list[str]: Mismatch descriptions (empty when reconciled).
        """
        out = []
        if balances.get("USD") != self.cash:
            out.append(f"cash ledger={self.cash} adapter={balances.get('USD')}")
        insts = set(self.positions) | {k for k in balances if k != "USD"}
        for iid in sorted(insts):
            mine = self.positions[iid].quantity if iid in self.positions else Decimal(0)
            theirs = balances.get(iid, Decimal(0))
            if mine != theirs:
                out.append(f"{iid} ledger={mine} adapter={theirs}")
        return out

    def snapshot(
        self,
        snapshot_id: str,
        t: datetime,
        committed_cash: Decimal,
        hwm: Decimal,
        day_start: Decimal,
        breaker_open: bool,
        lockout_until: datetime | None,
        cooldowns: dict[str, datetime],
    ) -> PositionSnapshot:
        """
        Build a PositionSnapshot.

        Args:
            snapshot_id (str): ID.
            t (datetime): Time.
            committed_cash (Decimal): Committed cash for pending buys.
            hwm (Decimal): High-water mark.
            day_start (Decimal): Day-start equity.
            breaker_open (bool): Breaker state.
            lockout_until (datetime | None): Lockout end.
            cooldowns (dict[str, datetime]): Active cooldowns.

        Returns:
            PositionSnapshot: Snapshot.
        """
        eq = self.equity
        lines = [
            PositionLine(
                instrument_id=iid,
                tier=p.tier,
                sleeve=Sleeve.CORE,
                quantity=p.quantity,
                avg_entry_price=p.avg_entry_price,
                mark_price=p.mark,
                market_value_usd=p.quantity * p.mark,
                unrealized_pnl_usd=p.quantity * p.mark - p.cost_basis_usd,
                realized_pnl_usd=self.realized_pnl.get(iid, Decimal(0)),
                stop_price=p.stop_price,
                opened_at_utc=p.opened_at,
                owner_strategy_ids=p.owners,
            )
            for iid, p in sorted(self.positions.items())
        ]
        by_inst = (
            {ln.instrument_id: ln.market_value_usd / eq * HUNDRED for ln in lines} if eq else {}
        )
        by_tier: dict[str, Decimal] = {}
        for ln in lines:
            by_tier[ln.tier] = by_tier.get(ln.tier, Decimal(0)) + by_inst.get(
                ln.instrument_id, Decimal(0)
            )
        return PositionSnapshot(
            schema_version="1.0.0",
            position_snapshot_id=snapshot_id,
            as_of_utc=t,
            cash_usd=self.cash,
            committed_cash_usd=committed_cash,
            equity_usd=eq,
            hwm_equity_usd=hwm,
            drawdown_pct=(hwm - eq) / hwm * HUNDRED if hwm else Decimal(0),
            day_start_equity_usd=day_start,
            daily_pnl_pct=(eq - day_start) / day_start * HUNDRED if day_start else Decimal(0),
            positions=lines,
            exposure_by_instrument_pct=by_inst,
            exposure_by_tier_pct=by_tier,
            total_exposure_pct=sum(by_inst.values(), Decimal(0)),
            open_positions_count=len(lines),
            breaker_open=breaker_open,
            daily_lockout_until_utc=lockout_until,
            cooldowns=cooldowns,
        )
