"""Environment-driven microsandbox configuration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from env_values import env_bool

# Repo root (parent of src/), independent of process cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Editable via Settings API / AppData ``.env``.
SETTINGS_ENV_KEYS = (
    "DEEPAGENT_LLM_PROVIDER",
    "DEEPAGENT_LLM_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_TEMPERATURE",
    "OPENROUTER_SITE_URL",
    "OPENROUTER_SITE_NAME",
    # Shared sandbox (AppData-persisted on desktop builds)
    "DEEPAGENT_NETWORK_ACCESS",
    "DEEPAGENT_SANDBOX_MEMORY",
    "DEEPAGENT_SANDBOX_CPUS",
    "DEEPAGENT_DNS_NAMESERVERS",
    "DEEPAGENT_SANDBOX_IDLE_TIMEOUT",
    "DEEPAGENT_EXEC_TIMEOUT",
)

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

_logging_configured = False


def is_desktop_mode() -> bool:
    """True when running as the Tauri-packaged sidecar (or desktop-flagged)."""
    return env_bool("DEEPAGENT_DESKTOP")


def default_appdata_dir() -> Path:
    """Platform AppData root for Deep Agent (``%APPDATA%\\DeepAgent`` on Windows)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "DeepAgent"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DeepAgent"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "DeepAgent"
    return Path.home() / ".config" / "DeepAgent"


def resolve_data_dir() -> Path:
    """Config/DB/logs root: ``DEEPAGENT_DATA_DIR``, else AppData when desktop, else repo ``data/``."""
    env = os.environ.get("DEEPAGENT_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if is_desktop_mode():
        return default_appdata_dir().resolve()
    return (_REPO_ROOT / "data").resolve()


def env_dir() -> Path:
    """Directory that holds ``.env`` / ``.env.local`` for the current mode."""
    if os.environ.get("DEEPAGENT_DATA_DIR") or is_desktop_mode():
        return resolve_data_dir()
    return _REPO_ROOT


def load_app_env() -> Path:
    """Load ``.env`` then ``.env.local``.

    Desktop / ``DEEPAGENT_DATA_DIR``: load from the data dir (AppData).
    Dev/browser: load from the repo root (today's defaults).

    ``.env`` does not override existing process env. ``.env.local`` overrides
    both ``.env`` and the process env so machine-local knobs win.
    Safe to call more than once.
    """
    root = env_dir()
    root.mkdir(parents=True, exist_ok=True)
    load_dotenv(root / ".env", override=False)
    load_dotenv(root / ".env.local", override=True)
    # When desktop also loads AppData, still allow a repo ``.env`` as a
    # non-overriding fallback for developers running the sidecar locally.
    if root != _REPO_ROOT:
        load_dotenv(_REPO_ROOT / ".env", override=False)
    return root


def configure_file_logging() -> Path | None:
    """When desktop, log to ``{data_dir}/logs/deepagent.log`` (+ stderr)."""
    global _logging_configured
    if _logging_configured:
        return None
    if not (is_desktop_mode() or os.environ.get("DEEPAGENT_DATA_DIR")):
        return None
    log_dir = resolve_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "deepagent.log"
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            handlers=[
                logging.FileHandler(log_path, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
    else:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root.addHandler(fh)
    _logging_configured = True
    return log_path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def default_workdir() -> Path:
    raw = os.environ.get("DEEPAGENT_WORKDIR") or os.environ.get("CODEX_GUI_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    if is_desktop_mode():
        docs = Path.home() / "Documents" / "DeepAgent" / "workspace"
        return docs.expanduser().resolve()
    return (Path.cwd() / "workspace").resolve()


def default_network() -> bool:
    return env_bool("DEEPAGENT_NETWORK_ACCESS") or env_bool("CODEX_GUI_NETWORK_ACCESS")


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


def sandbox_recreate_fingerprint() -> tuple[Any, ...]:
    """Effective VM settings; changes imply microVM recreate."""
    return (
        default_network(),
        sandbox_memory_mib(),
        sandbox_cpus(),
        sandbox_dns_nameservers(),
        sandbox_idle_timeout(),
    )


def normalize_settings_value(key: str, value: str) -> str:
    """Canonicalize a settings value before writing to ``.env``."""
    if key == "DEEPAGENT_NETWORK_ACCESS":
        return "true" if value.lower() in {"1", "true", "yes"} else "false"
    return value


def read_settings_env() -> dict[str, str]:
    """Return editable settings keys from process env (API key masked)."""
    out: dict[str, str] = {}
    for key in SETTINGS_ENV_KEYS:
        val = os.environ.get(key, "")
        if key == "OPENROUTER_API_KEY" and val:
            if len(val) <= 8:
                out[key] = "••••••••"
            else:
                out[key] = f"{val[:4]}…{val[-4:]}"
            out[f"{key}_set"] = "true"
        else:
            out[key] = val
            if key == "OPENROUTER_API_KEY":
                out[f"{key}_set"] = "false"
    return out


def write_settings_env(updates: dict[str, str | None]) -> Path:
    """Merge ``updates`` into ``{env_dir}/.env`` and refresh ``os.environ``.

    Keys with value ``None`` are left unchanged. Empty string removes the key
    from the file and process env for non-secret fields (API key empty means
    "leave as-is"). Network access is always stored as ``true`` / ``false``.
    """
    path = env_dir() / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    order: list[str] = []
    other_lines: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                other_lines.append(line)
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in SETTINGS_ENV_KEYS:
                existing[key] = value
                if key not in order:
                    order.append(key)
            else:
                other_lines.append(line)

    for key, raw in updates.items():
        if key not in SETTINGS_ENV_KEYS:
            continue
        if raw is None:
            continue
        value = str(raw).strip()
        if key == "OPENROUTER_API_KEY" and (not value or "…" in value or value.startswith("••••")):
            # Masked / empty payload — keep existing secret.
            continue
        if key == "DEEPAGENT_NETWORK_ACCESS":
            # Checkbox always persists explicitly (never "unset").
            value = normalize_settings_value(key, value or "false")
        if key not in order:
            order.append(key)
        if value:
            existing[key] = value
            os.environ[key] = value
        else:
            # Omit blank optional keys from the file so dotenv does not reload
            # them as "" (which breaks float/int parsers that only default on unset).
            existing.pop(key, None)
            if key in os.environ and key != "OPENROUTER_API_KEY":
                del os.environ[key]

    lines: list[str] = []
    if other_lines:
        lines.extend(other_lines)
        if lines and lines[-1] != "":
            lines.append("")
    for key in order:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
    for key in SETTINGS_ENV_KEYS:
        if key in existing and key not in order:
            lines.append(f"{key}={existing[key]}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


# Load dotenv as soon as this module is imported (matches prior behavior).
load_app_env()
configure_file_logging()
