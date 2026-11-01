"""YAML loading with exact Decimal numbers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


class ConfigLoadError(ValueError):
    """Raised when a configuration file cannot be read or parsed."""


def decimalize(value: Any) -> Any:
    """
    Recursively convert floats to Decimal via their shortest text form.

    Reason: ``Decimal(0.3333)`` carries binary noise; ``Decimal("0.3333")`` does not. All
    configuration numbers must be exact so hashes and limits are reproducible (ADR-017).

    Args:
        value (Any): Parsed YAML data.

    Returns:
        Any: Same structure with floats replaced.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: decimalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimalize(v) for v in value]
    return value


def load_yaml(path: Path) -> Any:
    """
    Load one YAML document with ``safe_load`` and exact decimals.

    Args:
        path (Path): YAML file.

    Returns:
        Any: Parsed data.

    Raises:
        ConfigLoadError: If the file is missing or not valid YAML.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigLoadError(f"cannot read {path}: {exc}") from exc
    try:
        return decimalize(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"invalid YAML in {path}: {exc}") from exc
