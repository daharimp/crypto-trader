"""Loss state: high-water mark, drawdown, UTC-day start equity, loss scaling (D-12)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trader.domain.risk import LossState

from .params import RiskParams

HUNDRED = Decimal(100)


def loss_multiplier(params: RiskParams, drawdown_pct: Decimal) -> Decimal:
    """
    Size multiplier from the size-reduction schedule (RR-13).

    Args:
        params (RiskParams): Risk parameters.
        drawdown_pct (Decimal): Current drawdown in percent.

    Returns:
        Decimal: Multiplier in [0, 1]; 0 once drawdown reaches the breaker.
    """
    frac = drawdown_pct / params.breaker_pct
    if params.schedule_method == "linear_to_breaker":
        return max(Decimal(0), Decimal(1) - frac)
    for below, mult in params.schedule_steps:
        if frac < below:
            return mult
    return Decimal(0)


class LossTracker:
    """Tracks equity marks at bar closes."""

    def __init__(self, initial_equity: Decimal) -> None:
        """
        Start tracking.

        Args:
            initial_equity (Decimal): Starting equity.
        """
        self.equity = initial_equity
        self.hwm = initial_equity
        self.day_start = initial_equity

    def mark(self, t: datetime, equity: Decimal) -> None:
        """
        Record equity at a bar close; 00:00 UTC closes set day-start equity.

        Args:
            t (datetime): Bar close time.
            equity (Decimal): Marked equity.
        """
        self.equity = equity
        self.hwm = max(self.hwm, equity)
        if t.hour == 0 and t.minute == 0 and t.second == 0:
            self.day_start = equity

    @property
    def drawdown_pct(self) -> Decimal:
        """
        Drawdown from the high-water mark in percent.

        Returns:
            Decimal: Drawdown (>= 0).
        """
        return (self.hwm - self.equity) / self.hwm * HUNDRED if self.hwm > 0 else Decimal(0)

    @property
    def daily_pnl_pct(self) -> Decimal:
        """
        PnL since the UTC day start in percent.

        Returns:
            Decimal: Daily PnL (negative for a loss).
        """
        if self.day_start <= 0:
            return Decimal(0)
        return (self.equity - self.day_start) / self.day_start * HUNDRED

    def state(
        self, params: RiskParams | None, breaker_open: bool, lockout_active: bool
    ) -> LossState:
        """
        Build the LossState contract.

        Args:
            params (RiskParams | None): Parameters (multiplier is 0 if unresolved).
            breaker_open (bool): Breaker state.
            lockout_active (bool): Lockout state.

        Returns:
            LossState: Loss state.
        """
        mult = loss_multiplier(params, self.drawdown_pct) if params else Decimal(0)
        return LossState(
            equity_usd=self.equity,
            hwm_equity_usd=self.hwm,
            drawdown_pct=self.drawdown_pct,
            day_start_equity_usd=self.day_start,
            daily_pnl_pct=self.daily_pnl_pct,
            loss_scaling_multiplier=mult,
            breaker_open=breaker_open,
            daily_lockout_active=lockout_active,
        )
