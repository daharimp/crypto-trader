"""Strategy registry: maps registry entries to vetted in-repo classes only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trader.profiles.loader import load_yaml

from .base import Strategy
from .sma_trend import SmaTrend

# Reason: code_ref is checked against a fixed allowlist instead of importing arbitrary
# modules named in configuration.
_CLASSES: dict[str, Any] = {"trader.strategies.sma_trend:SmaTrend": SmaTrend}


class StrategyNotFoundError(KeyError):
    """Raised for an unknown or unregistered strategy."""


def load_entry(strategy_id: str, configs_root: Path = Path("configs")) -> dict[str, Any]:
    """
    Load a strategy registry entry.

    Args:
        strategy_id (str): Strategy ID.
        configs_root (Path): Config root.

    Returns:
        dict[str, Any]: Entry.

    Raises:
        StrategyNotFoundError: If the entry does not exist.
    """
    path = configs_root / "strategies" / f"{strategy_id}.yaml"
    if not path.exists():
        raise StrategyNotFoundError(strategy_id)
    entry: dict[str, Any] = load_yaml(path)
    return entry


def build_strategy(strategy_id: str, configs_root: Path = Path("configs")) -> Strategy:
    """
    Instantiate a registered strategy.

    Args:
        strategy_id (str): Strategy ID.
        configs_root (Path): Config root.

    Returns:
        Strategy: Strategy instance.

    Raises:
        StrategyNotFoundError: If not registered or the class is not allowlisted.
    """
    entry = load_entry(strategy_id, configs_root)
    cls = _CLASSES.get(str(entry.get("code_ref")))
    if cls is None:
        raise StrategyNotFoundError(f"{strategy_id}: code_ref not allowlisted")
    strategy: Strategy = cls(**entry.get("parameters", {}))
    return strategy
