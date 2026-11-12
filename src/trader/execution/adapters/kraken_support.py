"""Shared constants and helpers for the Kraken live adapter (ADR-023)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from trader.common.hashing import sha256_hex
from trader.domain.enums import ExecutionStatus
from trader.domain.execution import ExecutionReport
from trader.domain.orders import OrderIntent

ADAPTER_ID = "kraken_live"
# Reason: the only Kraken order parameters this adapter may send. "leverage" (margin) and
# anything else are impossible by construction; T-46 also scans for them.
_ALLOWED_PARAMS = frozenset({"oflags", "userref", "stopLossPrice", "validate"})
_OPEN = (ExecutionStatus.ACCEPTED, ExecutionStatus.OPEN)


class LiveAdapterError(RuntimeError):
    """Raised when the adapter is misconfigured (never for ordinary order rejections)."""


@dataclass
class _LiveOrder:
    """Adapter-side record of one exchange order."""

    intent: OrderIntent
    exchange_id: str | None
    report: ExecutionReport


def userref_for(intent: OrderIntent) -> int:
    """
    Deterministic Kraken ``userref`` (positive int32) from the idempotency key.

    Args:
        intent (OrderIntent): Intent.

    Returns:
        int: User reference used to find an order again after a timeout.
    """
    return int(sha256_hex(intent.idempotency_key)[:7], 16)


def _d(value: Any) -> Decimal:
    """
    Convert an exchange number to Decimal via text.

    Args:
        value (Any): Number or None.

    Returns:
        Decimal: Value (0 for None).
    """
    return Decimal(str(value)) if value is not None else Decimal(0)
