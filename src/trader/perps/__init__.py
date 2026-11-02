"""Paper-only perpetual futures on Jupiter Perps (ADR-024).

This package is isolated from the spot pipeline: it has its own position model, its own
deterministic risk checks, and its own paper simulator. It never submits transactions,
never reads a wallet key, and only reads public prices. Leverage and shorting exist here
and nowhere else in ``src/`` (T-46 as amended by ADR-024).
"""

from .math import PerpSide

__all__ = ["PerpSide"]
