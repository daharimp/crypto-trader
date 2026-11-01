"""Adapter registry with a hard allowlist (EG-04, T-46)."""

from __future__ import annotations

from decimal import Decimal

from trader.execution.costs import CostParams

from .simulated import SimulatedExecutionAdapter

ALLOWED_ADAPTERS = frozenset({"simulated"})


class AdapterNotAllowedError(PermissionError):
    """Raised for any adapter outside the allowlist (``ADAPTER_NOT_ALLOWED``)."""


def build_adapter(
    adapter_id: str, capital: Decimal, costs: CostParams
) -> SimulatedExecutionAdapter:
    """
    Build an allowlisted adapter.

    Args:
        adapter_id (str): Adapter ID from the environment config.
        capital (Decimal): Starting simulated cash.
        costs (CostParams): Cost scenario.

    Returns:
        SimulatedExecutionAdapter: The simulator.

    Raises:
        AdapterNotAllowedError: For anything other than ``simulated``.
    """
    if adapter_id not in ALLOWED_ADAPTERS:
        raise AdapterNotAllowedError(f"ADAPTER_NOT_ALLOWED: {adapter_id}")
    return SimulatedExecutionAdapter(capital, costs)
