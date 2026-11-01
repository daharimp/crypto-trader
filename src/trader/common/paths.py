"""Locations of runtime data (git-ignored ``data/`` tree)."""

from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    """
    Return the data directory (``TRADER_DATA_DIR`` or ``./data``).

    Returns:
        Path: Data root.
    """
    return Path(os.environ.get("TRADER_DATA_DIR", "data"))


def data_path(*parts: str) -> Path:
    """
    Build a path under the data root and create its parent directory.

    Args:
        *parts (str): Path components, e.g. ``"state", "operational.sqlite"``.

    Returns:
        Path: The joined path.
    """
    p = data_root().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
