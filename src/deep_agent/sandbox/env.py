"""Side-effect-free environment value parsing."""

from __future__ import annotations

import os

_TRUE_VALUES = frozenset({"1", "true", "yes"})


def env_bool(name: str, default: bool = False) -> bool:
    """Read a conventional boolean environment variable."""
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in _TRUE_VALUES
