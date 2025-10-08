"""Stable hashing helpers."""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    """Return the hex digest of SHA-256 for the given bytes."""

    return hashlib.sha256(data).hexdigest()

