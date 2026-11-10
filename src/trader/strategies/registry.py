"""Strategy registry: maps registry entries to vetted in-repo classes only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from trader.common.paths import configs_root as default_configs_root
from trader.profiles.loader import load_yaml

from .base import Strategy
from .mean_reversion import MeanReversion
from .random_entry import RandomEntry
from .sma_trend import SmaTrend
from .tsmom import Tsmom
from .volatility_breakout import VolatilityBreakout

# Reason: code_ref is checked against a fixed allowlist instead of importing arbitrary
# modules named in configuration.
_CLASSES: dict[str, Any] = {
    "trader.strategies.sma_trend:SmaTrend": SmaTrend,
    "trader.strategies.tsmom:Tsmom": Tsmom,
    "trader.strategies.mean_reversion:MeanReversion": MeanReversion,
    "trader.strategies.volatility_breakout:VolatilityBreakout": VolatilityBreakout,
    "trader.strategies.random_entry:RandomEntry": RandomEntry,
}
# Lifecycle states that may never run in a paper or live session.
RESEARCH_ONLY_STATES = frozenset({"control"})


class StrategyNotFoundError(KeyError):
    """Raised for an unknown or unregistered strategy."""


def load_entry(strategy_id: str, configs_root: Path | None = None) -> dict[str, Any]:
    """
    Load a strategy registry entry.

    Args:
        strategy_id (str): Strategy ID.
        configs_root (Path | None): Config root.
            Defaults to ``TRADER_CONFIGS_DIR`` or ``configs``.

    Returns:
        dict[str, Any]: Entry.

    Raises:
        StrategyNotFoundError: If the entry does not exist.
    """
    path = (configs_root or default_configs_root()) / "strategies" / f"{strategy_id}.yaml"
    if not path.exists():
        raise StrategyNotFoundError(strategy_id)
    entry: dict[str, Any] = load_yaml(path)
    return entry


def build_strategy(
    strategy_id: str,
    configs_root: Path | None = None,
    timeframe: str | None = None,
    forward_session: bool = False,
) -> Strategy:
    """
    Instantiate a registered strategy.

    Args:
        strategy_id (str): Strategy ID.
        configs_root (Path | None): Config root.
            Defaults to ``TRADER_CONFIGS_DIR`` or ``configs``.

        timeframe (str | None): Decision timeframe; must be listed in the registry entry.
        forward_session (bool): True for paper/live sessions, which refuse controls.

    Returns:
        Strategy: Strategy instance.

    Raises:
        StrategyNotFoundError: If not registered, not allowlisted, the timeframe is not
            supported, or a control strategy is requested for a forward session.
    """
    entry = load_entry(strategy_id, configs_root)
    if timeframe is not None and timeframe not in entry.get("timeframes", []):
        raise StrategyNotFoundError(f"{strategy_id} does not support timeframe {timeframe}")
    if forward_session and entry.get("lifecycle_state") in RESEARCH_ONLY_STATES:
        raise StrategyNotFoundError(f"{strategy_id} is a research-only control strategy")
    cls = _CLASSES.get(str(entry.get("code_ref")))
    if cls is None:
        raise StrategyNotFoundError(f"{strategy_id}: code_ref not allowlisted")
    strategy: Strategy = cls(**entry.get("parameters", {}))
    return strategy
