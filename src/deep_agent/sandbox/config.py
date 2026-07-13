"""Environment-driven microsandbox configuration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from deep_agent.sandbox.env import env_bool

# Repo root (parent of src/), independent of process cwd.
_REPO_ROOT = Path(__file__).resolve().parents[3]

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
    """Prepare data dir and load JSON settings.

    User LLM/sandbox prefs live only in ``settings.json`` + ``secrets.json``.
    Repo / AppData ``.env`` files are **not** loaded for those keys (avoids
    ``pnpm tauri`` reseeding Setup from a leftover project ``.env``).
    Process env from the parent (Tauri / CI) still applies for paths/backends.
    """
    root = env_dir()
    root.mkdir(parents=True, exist_ok=True)
    from deep_agent.settings.store import load_settings

    load_settings()
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
    """Backward-compatible flat view of settings (masked API key)."""
    from deep_agent.settings.store import active_platform, load_settings, platform_api_key

    cfg = load_settings()
    platform = active_platform(cfg)
    key = platform_api_key(platform["id"])
    out: dict[str, str] = {
        "DEEPAGENT_LLM_PROVIDER": str(platform.get("kind") or "openrouter"),
        "DEEPAGENT_LLM_BASE_URL": (
            ""
            if platform.get("kind") == "openrouter"
            else str(platform.get("base_url") or "")
        ),
        "OPENROUTER_MODEL": str(cfg.get("default_model") or ""),
        "OPENROUTER_TEMPERATURE": str(cfg.get("temperature", 0.3)),
        "OPENROUTER_SITE_URL": str(platform.get("site_url") or ""),
        "OPENROUTER_SITE_NAME": str(platform.get("site_name") or ""),
        "DEEPAGENT_NETWORK_ACCESS": (
            "true" if (cfg.get("sandbox") or {}).get("network") else "false"
        ),
        "DEEPAGENT_SANDBOX_MEMORY": str(
            (cfg.get("sandbox") or {}).get("memory_mib", DEFAULT_MEMORY_MIB)
        ),
        "DEEPAGENT_SANDBOX_CPUS": str((cfg.get("sandbox") or {}).get("cpus", DEFAULT_CPUS)),
        "DEEPAGENT_DNS_NAMESERVERS": str(
            (cfg.get("sandbox") or {}).get("dns_nameservers", "")
        ),
        "DEEPAGENT_EXEC_TIMEOUT": str(
            (cfg.get("sandbox") or {}).get("exec_timeout", DEFAULT_EXEC_TIMEOUT)
        ),
        "DEEPAGENT_SANDBOX_IDLE_TIMEOUT": str(
            (cfg.get("sandbox") or {}).get("idle_timeout", DEFAULT_IDLE_TIMEOUT)
        ),
    }
    if key:
        out["OPENROUTER_API_KEY"] = (
            f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "••••••••"
        )
        out["OPENROUTER_API_KEY_set"] = "true"
    else:
        out["OPENROUTER_API_KEY"] = ""
        out["OPENROUTER_API_KEY_set"] = "false"
    return out


def write_settings_env(updates: dict[str, str | None]) -> Path:
    """Map flat Settings form values into the JSON settings store."""
    from deep_agent.settings.store import settings_path, update_from_ui

    kind = (updates.get("DEEPAGENT_LLM_PROVIDER") or "openrouter").strip().lower()
    payload: dict = {
        "default_model": updates.get("OPENROUTER_MODEL") or "",
        "temperature": updates.get("OPENROUTER_TEMPERATURE") or 0.3,
        "platform": {
            "id": kind,
            "kind": kind,
            "name": kind.title(),
            "base_url": updates.get("DEEPAGENT_LLM_BASE_URL") or "",
            "site_url": updates.get("OPENROUTER_SITE_URL") or "",
            "site_name": updates.get("OPENROUTER_SITE_NAME") or "",
            "api_key": updates.get("OPENROUTER_API_KEY") or "",
        },
        "sandbox": {},
    }
    if "DEEPAGENT_NETWORK_ACCESS" in updates:
        payload["sandbox"]["network"] = str(updates.get("DEEPAGENT_NETWORK_ACCESS") or "").lower() in {
            "1",
            "true",
            "yes",
        }
    for src, dst in (
        ("DEEPAGENT_SANDBOX_MEMORY", "memory_mib"),
        ("DEEPAGENT_SANDBOX_CPUS", "cpus"),
        ("DEEPAGENT_EXEC_TIMEOUT", "exec_timeout"),
        ("DEEPAGENT_SANDBOX_IDLE_TIMEOUT", "idle_timeout"),
    ):
        if src in updates and updates.get(src) not in (None, ""):
            payload["sandbox"][dst] = updates.get(src)
    if "DEEPAGENT_DNS_NAMESERVERS" in updates:
        payload["sandbox"]["dns_nameservers"] = updates.get("DEEPAGENT_DNS_NAMESERVERS") or ""
    if not payload["sandbox"]:
        del payload["sandbox"]
    # Saving from Settings implies setup is done when a model is present.
    if (updates.get("OPENROUTER_MODEL") or "").strip() or kind == "ollama":
        payload["setup_complete"] = True
    update_from_ui(payload)
    return settings_path()


# Load dotenv as soon as this module is imported (matches prior behavior).
load_app_env()
configure_file_logging()
