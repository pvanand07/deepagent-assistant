"""Pure workspace path containment helpers."""

from __future__ import annotations

from pathlib import Path


def resolve_under_workdir(workdir: Path, relative_path: str) -> Path | None:
    """Resolve a workspace-relative path, returning ``None`` on escape."""
    root = workdir.resolve()
    candidate = (root / relative_path.strip().lstrip("/")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
