"""Idempotency keys and order-intent construction (journaled before any action)."""

from __future__ import annotations

from datetime import datetime

from trader.common.hashing import hash_obj
from trader.domain.enums import OrderPurpose, Side


def idempotency_key(
    config_hash: str, instrument_id: str, side: Side, purpose: OrderPurpose, decision_time: datetime
) -> str:
    """
    Deterministic idempotency key (§7.3).

    Args:
        config_hash (str): Compiled profile hash.
        instrument_id (str): Instrument.
        side (Side): Side.
        purpose (OrderPurpose): Purpose.
        decision_time (datetime): Decision time.

    Returns:
        str: ``sha256:<hex>``.
    """
    return hash_obj([config_hash, instrument_id, side.value, purpose.value, decision_time])
