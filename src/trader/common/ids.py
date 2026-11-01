"""Deterministic, run-scoped ID generation (R-06)."""

from __future__ import annotations

from collections import defaultdict


class IdGenerator:
    """Generates prefixed sequential IDs such as ``sig-000001``.

    Reason: backtests use run-scoped counters so two identical runs produce identical IDs,
    which keeps journal hashes reproducible (NFR-01, T-43).
    """

    def __init__(self) -> None:
        """Create a generator with all counters at zero."""
        self._counters: dict[str, int] = defaultdict(int)

    def next(self, prefix: str) -> str:
        """
        Return the next ID for a prefix.

        Args:
            prefix (str): ID prefix, e.g. ``sig`` or ``rsk``.

        Returns:
            str: ID such as ``sig-000001``.
        """
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]:06d}"
