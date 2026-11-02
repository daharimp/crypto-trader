"""Adapter registry with a hard allowlist (EG-04, T-46)."""

from __future__ import annotations

from decimal import Decimal

from trader.execution.costs import CostParams

from .simulated import SimulatedExecutionAdapter

# Reason (ADR-023): "kraken_live" is the only real-money adapter; the gate pairs it with
# funds "real" in the live environment and pairs "simulated" with simulated funds.
ALLOWED_ADAPTERS = frozenset({"simulated", "kraken_live"})


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
    if adapter_id != "simulated":
        # Reason: the real-money adapter is built only by the gated live-session factory
        # (trader.session.factory), never by this generic builder.
        raise AdapterNotAllowedError(f"ADAPTER_NOT_ALLOWED: {adapter_id} only via live session")
    return SimulatedExecutionAdapter(capital, costs)
