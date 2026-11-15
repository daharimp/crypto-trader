"""Paper perps account: simulated opens, closes, borrow fees, and liquidations (ADR-025).

Nothing here talks to a venue. Prices are passed in by the caller. Every state change is
appended to ``events`` so a run can be journaled and replayed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .math import PerpSide, fee_usd, is_liquidatable, pnl_usd, remaining_collateral
from .params import PerpsParams
from .risk import AccountView, PerpRiskDecision, check_open, size_open

HUNDRED = Decimal(100)
CENT = Decimal("0.01")


@dataclass
class PerpPosition:
    """An open simulated position."""

    market: str
    side: PerpSide
    size_usd: Decimal
    collateral_usd: Decimal
    entry_price: Decimal
    opened_at: datetime
    borrow_fees_usd: Decimal = Decimal(0)
    last_accrual: datetime | None = None


@dataclass
class PaperPerpsAccount:
    """A simulated perps account funded with paper collateral."""

    params: PerpsParams
    cash_usd: Decimal
    day_start_equity_usd: Decimal
    day: str
    positions: dict[str, PerpPosition] = field(default_factory=dict)
    realized_pnl_usd: Decimal = Decimal(0)
    fees_paid_usd: Decimal = Decimal(0)
    halted: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    # Typical daily move per market, set by the caller before signals are applied; used
    # only when leverage is assessed from volatility (ADR-032).
    daily_moves: dict[str, Decimal] = field(default_factory=dict)

    @classmethod
    def start(cls, params: PerpsParams, now: datetime) -> PaperPerpsAccount:
        """
        Open a fresh account with the configured starting collateral.

        Args:
            params (PerpsParams): Resolved parameters.
            now (datetime): Start time (UTC).

        Returns:
            PaperPerpsAccount: Account.
        """
        cash = params.starting_collateral_usd
        acct = cls(params, cash, cash, now.date().isoformat())
        acct._log(now, "ACCOUNT_STARTED", cash_usd=str(cash))
        return acct

    def _log(self, now: datetime, kind: str, **data: Any) -> None:
        self.events.append({"at_utc": now.isoformat(), "event": kind, **data})

    def equity(self, marks: dict[str, Decimal]) -> Decimal:
        """
        Cash plus what every open position would return if closed now.

        Args:
            marks (dict[str, Decimal]): Mark price per market.

        Returns:
            Decimal: Equity in USD.
        """
        total = self.cash_usd
        for p in self.positions.values():
            total += max(
                remaining_collateral(
                    p.side,
                    p.size_usd,
                    p.collateral_usd,
                    p.entry_price,
                    marks[p.market],
                    self.params.close_fee_bps,
                    p.borrow_fees_usd,
                ),
                Decimal(0),
            )
        return total

    def view(self, marks: dict[str, Decimal]) -> AccountView:
        """
        Snapshot for the risk checks.

        Args:
            marks (dict[str, Decimal]): Mark price per market.

        Returns:
            AccountView: View.
        """
        return AccountView(
            free_cash_usd=self.cash_usd,
            equity_usd=self.equity(marks),
            day_start_equity_usd=self.day_start_equity_usd,
            open_markets=frozenset(self.positions),
            gross_size_usd=sum((p.size_usd for p in self.positions.values()), Decimal(0)),
            halted=self.halted,
        )

    def mark(self, marks: dict[str, Decimal], now: datetime) -> None:
        """
        Accrue borrow fees, liquidate positions past maintenance, and roll the day.

        Args:
            marks (dict[str, Decimal]): Mark price per market.
            now (datetime): Current time (UTC).
        """
        for m in list(self.positions):
            p = self.positions[m]
            since = p.last_accrual or p.opened_at
            hours = Decimal(int((now - since) / timedelta(seconds=1))) / Decimal(3600)
            if hours > 0:
                fee = p.size_usd * self.params.borrow_rate_pct_per_hour / HUNDRED * hours
                p.borrow_fees_usd += fee.quantize(CENT)
                p.last_accrual = now
            if is_liquidatable(
                p.side,
                p.size_usd,
                p.collateral_usd,
                p.entry_price,
                marks[m],
                self.params.close_fee_bps,
                p.borrow_fees_usd,
                self.params.maintenance_bps,
            ):
                # Reason: conservative paper model, the whole collateral is lost on liquidation.
                self.realized_pnl_usd -= p.collateral_usd
                del self.positions[m]
                self._log(
                    now,
                    "LIQUIDATED",
                    market=m,
                    side=p.side.value,
                    mark=str(marks[m]),
                    collateral_lost_usd=str(p.collateral_usd),
                )
        today = now.date().isoformat()
        if today != self.day:
            self.day, self.day_start_equity_usd = today, self.equity(marks)
            self._log(now, "DAY_ROLLED", day=today, equity_usd=str(self.day_start_equity_usd))

    def open(
        self, market: str, side: PerpSide, marks: dict[str, Decimal], now: datetime
    ) -> PerpRiskDecision:
        """
        Size and risk-check an open; apply it only if approved.

        Args:
            market (str): Market.
            side (PerpSide): Direction.
            marks (dict[str, Decimal]): Mark prices.
            now (datetime): Current time (UTC).

        Returns:
            PerpRiskDecision: The decision.
        """
        view = self.view(marks)
        decision = check_open(
            self.params,
            view,
            size_open(self.params, view, market, side, marks[market], self.daily_moves.get(market)),
        )
        if not decision.approved or decision.proposal is None:
            self._log(
                now, "OPEN_REJECTED", market=market, side=side.value, reasons=decision.reasons
            )
            return decision
        pr = decision.proposal
        open_fee = fee_usd(pr.size_usd, self.params.open_fee_bps).quantize(CENT)
        self.cash_usd -= pr.collateral_usd + open_fee
        self.fees_paid_usd += open_fee
        self.realized_pnl_usd -= open_fee
        self.positions[market] = PerpPosition(
            market, side, pr.size_usd, pr.collateral_usd, pr.entry_price, now, last_accrual=now
        )
        self._log(
            now,
            "OPENED",
            market=market,
            side=side.value,
            size_usd=str(pr.size_usd),
            collateral_usd=str(pr.collateral_usd),
            entry=str(pr.entry_price),
            leverage=str(pr.leverage),
            liquidation_price=str(pr.liquidation_price.quantize(CENT)),
            fee_usd=str(open_fee),
        )
        return decision

    def close(self, market: str, marks: dict[str, Decimal], now: datetime, reason: str) -> bool:
        """
        Close an open position at the mark.

        Args:
            market (str): Market.
            marks (dict[str, Decimal]): Mark prices.
            now (datetime): Current time (UTC).
            reason (str): Why it closes (journaled).

        Returns:
            bool: True if a position was closed.
        """
        p = self.positions.pop(market, None)
        if p is None:
            return False
        close_fee = fee_usd(p.size_usd, self.params.close_fee_bps).quantize(CENT)
        pnl = pnl_usd(p.side, p.size_usd, p.entry_price, marks[market]).quantize(CENT)
        returned = max(p.collateral_usd + pnl - close_fee - p.borrow_fees_usd, Decimal(0))
        self.cash_usd += returned
        self.fees_paid_usd += close_fee + p.borrow_fees_usd
        self.realized_pnl_usd += returned - p.collateral_usd
        self._log(
            now,
            "CLOSED",
            market=market,
            side=p.side.value,
            exit=str(marks[market]),
            pnl_usd=str(pnl),
            fees_usd=str(close_fee + p.borrow_fees_usd),
            reason=reason,
        )
        return True

    def apply_signal(
        self, market: str, target: PerpSide | None, marks: dict[str, Decimal], now: datetime
    ) -> None:
        """
        Move toward a strategy's target: long, short, or flat (None).

        An opposite position is closed before a new one is considered.

        Args:
            market (str): Market.
            target (PerpSide | None): Desired direction; None means flat.
            marks (dict[str, Decimal]): Mark prices.
            now (datetime): Current time (UTC).
        """
        current = self.positions.get(market)
        if current is not None and current.side != target:
            self.close(market, marks, now, reason="SIGNAL_CHANGED")
        if target is not None and market not in self.positions:
            self.open(market, target, marks, now)
