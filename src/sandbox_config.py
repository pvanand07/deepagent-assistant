"""Environment-driven microsandbox configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root (parent of src/), independent of process cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_app_env() -> Path:
    """Load ``.env`` then ``.env.local`` from the repo root.

    ``.env`` does not override existing process env. ``.env.local`` overrides
    both ``.env`` and the process env so machine-local knobs win.
    Safe to call more than once.
    """
    load_dotenv(_REPO_ROOT / ".env", override=False)
    load_dotenv(_REPO_ROOT / ".env.local", override=True)
    return _REPO_ROOT


load_app_env()


SANDBOX_NAME = "deepagent"
SANDBOX_ROOT = "/workspace"
DEFAULT_IMAGE = "python:3.12-slim"
DEFAULT_MEMORY_MIB = 1024
DEFAULT_CPUS = 2
DEFAULT_IDLE_TIMEOUT = 300
DEFAULT_LOCK_WAIT = 120
DEFAULT_EXEC_TIMEOUT = 120
LOG_PREVIEW_LINES = 100
LOG_RETENTION_DAYS = 7
LOG_RETENTION_BYTES = 100 * 1024 * 1024
LOG_DIR_REL = ".deepagent/logs"
# Windows host resolver auto-detect often breaks msb's DNS proxy; pin public resolvers.
DEFAULT_DNS_NAMESERVERS = ("1.1.1.1", "8.8.8.8")


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


def sandbox_dns_nameservers() -> tuple[str, ...]:
    """Upstream DNS for the guest interceptor when network is enabled.

    ``DEEPAGENT_DNS_NAMESERVERS`` is a comma-separated list. Unset → Cloudflare
    + Google. Set to empty / ``host`` to use microsandbox host auto-detect.
    """
    raw = os.environ.get("DEEPAGENT_DNS_NAMESERVERS")
    if raw is None:
        return DEFAULT_DNS_NAMESERVERS
    stripped = raw.strip()
    if not stripped or stripped.lower() == "host":
        return ()
    return tuple(part.strip() for part in stripped.split(",") if part.strip())


def guest_network():
    """Build microsandbox ``Network`` for the shared sandbox."""
    from microsandbox import Network
    from microsandbox.types import DnsConfig

    if not default_network():
        return Network.none()
    nameservers = sandbox_dns_nameservers()
    if not nameservers:
        return Network.public_only()
    return Network(
        policy="public_only",
        dns=DnsConfig(nameservers=nameservers),
    )


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
