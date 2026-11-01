"""Execution adapter interface. Only simulated adapters exist (D-02)."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent


class ExecutionAdapter(Protocol):
    """Order handling boundary. Implementations must never touch real funds."""

    adapter_id: str
    adapter_version: str

    def validate_order(self, intent: OrderIntent) -> list[str]:
        """Return validation problems (empty if acceptable)."""
        ...

    def submit_order(self, intent: OrderIntent) -> ExecutionReport:
        """Accept an order."""
        ...

    def cancel_order(self, order_intent_id: str) -> ExecutionReport:
        """Cancel an open order."""
        ...

    def get_order(self, order_intent_id: str) -> ExecutionReport:
        """Return the latest report for an order."""
        ...

    def list_open_orders(self) -> list[ExecutionReport]:
        """Return open orders."""
        ...

    def get_balances(self) -> dict[str, Decimal]:
        """Return balances keyed by ``USD`` and instrument ID."""
        ...
