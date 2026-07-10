"""Environment-driven microsandbox configuration."""

from __future__ import annotations

import os
from pathlib import Path


SANDBOX_NAME = "deepagent"
SANDBOX_ROOT = "/workspace"
DEFAULT_IMAGE = "deepagent-workspace:dev"
DEFAULT_MEMORY_MIB = 1024
DEFAULT_CPUS = 2
DEFAULT_IDLE_TIMEOUT = 300
DEFAULT_LOCK_WAIT = 120
DEFAULT_EXEC_TIMEOUT = 120
LOG_PREVIEW_LINES = 100
LOG_RETENTION_DAYS = 7
LOG_RETENTION_BYTES = 100 * 1024 * 1024
LOG_DIR_REL = ".deepagent/logs"


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def default_workdir() -> Path:
    raw = os.environ.get("DEEPAGENT_WORKDIR") or os.environ.get("CODEX_GUI_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.cwd() / "workspace").resolve()


def default_network() -> bool:
    return _env_bool("DEEPAGENT_NETWORK_ACCESS") or _env_bool("CODEX_GUI_NETWORK_ACCESS")


def sandbox_image() -> str:
    return os.environ.get("DEEPAGENT_SANDBOX_IMAGE") or DEFAULT_IMAGE


def sandbox_memory_mib() -> int:
    return _env_int("DEEPAGENT_SANDBOX_MEMORY", DEFAULT_MEMORY_MIB)


def sandbox_cpus() -> int:
    return _env_int("DEEPAGENT_SANDBOX_CPUS", DEFAULT_CPUS)


def sandbox_idle_timeout() -> int:
    """Seconds; 0 disables idle auto-stop."""
    return _env_int("DEEPAGENT_SANDBOX_IDLE_TIMEOUT", DEFAULT_IDLE_TIMEOUT)


def sandbox_lock_wait() -> int:
    return _env_int("DEEPAGENT_SANDBOX_LOCK_WAIT", DEFAULT_LOCK_WAIT)


def exec_timeout() -> int:
    """Default command timeout seconds; 0 means no limit."""
    return _env_int("DEEPAGENT_EXEC_TIMEOUT", DEFAULT_EXEC_TIMEOUT)


def use_stub_backend() -> bool:
    return os.environ.get("DEEPAGENT_SANDBOX_BACKEND", "microsandbox").lower() == "stub"
