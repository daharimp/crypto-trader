"""SHA-256 helpers. Hashes are written as ``sha256:<hex>``."""

from __future__ import annotations

import hashlib
from typing import Any

from .canonical import canonical_json

GENESIS_HASH = "sha256:" + "0" * 64


def sha256_hex(data: str | bytes) -> str:
    """
    Compute the SHA-256 hex digest.

    Args:
        data (str | bytes): Input; strings are UTF-8 encoded.

    Returns:
        str: Hex digest.
    """
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def sha256_tag(data: str | bytes) -> str:
    """
    Compute a tagged SHA-256 hash.

    Args:
        data (str | bytes): Input data.

    Returns:
        str: ``sha256:<hex>``.
    """
    return "sha256:" + sha256_hex(data)


def hash_obj(value: Any) -> str:
    """
    Hash the canonical JSON form of a value.

    Args:
        value (Any): Value to hash.

    Returns:
        str: ``sha256:<hex>`` of its canonical JSON.
    """
    return sha256_tag(canonical_json(value))
