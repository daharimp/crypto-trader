"""Session configuration, errors, and credential loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from trader.domain.enums import Environment
from trader.profiles.compiler import CompileBundle


class SessionError(RuntimeError):
    """A session cannot start; ``exit_code`` follows the CLI convention (2, 3, 4)."""

    def __init__(self, code: int, message: str) -> None:
        """
        Store the exit code.

        Args:
            code (int): Exit code.
            message (str): Message.
        """
        super().__init__(message)
        self.exit_code = code


@dataclass
class SessionConfig:
    """What to run."""

    profile: Path
    environment: Environment
    strategy: str = "sma_trend"
    timeframe: str = "4h"
    configs_root: Path | None = None


def _eff(bundle: CompileBundle, key: str) -> Decimal:
    """
    Read an approved effective value (forward sessions have no blockers).

    Args:
        bundle (CompileBundle): Compiled bundle.
        key (str): Effective key.

    Returns:
        Decimal: Value.
    """
    return Decimal(str(bundle.compiled.effective[key].value))


def api_keys_from_env(key_var: str, secret_var: str) -> tuple[str, str]:
    """
    Read Kraken credentials from the environment (never from files in the repo).

    Args:
        key_var (str): Variable name holding the key.
        secret_var (str): Variable name holding the secret.

    Returns:
        tuple[str, str]: Key and secret.

    Raises:
        SessionError: If either is missing.
    """
    key, secret = os.environ.get(key_var, ""), os.environ.get(secret_var, "")
    if not key or not secret:
        raise SessionError(2, f"set {key_var} and {secret_var} (in the server's .env file)")
    return key, secret
