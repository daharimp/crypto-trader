"""Code revision lookup recorded in every journal event."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def code_revision() -> str:
    """
    Return the current code revision.

    Uses ``TRADER_CODE_REVISION`` if set, else ``git rev-parse HEAD``, else ``unversioned``.

    Returns:
        str: Revision identifier.
    """
    env = os.environ.get("TRADER_CODE_REVISION")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unversioned"
    rev = out.stdout.strip()
    return rev if out.returncode == 0 and rev else "unversioned"
