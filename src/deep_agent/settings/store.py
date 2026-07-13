"""JSON settings + secrets store (replaces .env for app configuration).

Layout under ``resolve_data_dir()``:
  settings.json  — platforms, models, sandbox, setup flag (non-secret)
  secrets.json   — API keys per platform (mode 0600 when possible)

Process env remains an override for CI/tests (``DEEPAGENT_*`` / keys already set).
Legacy ``.env`` is migrated once into JSON, then ignored for settings keys.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any

from deep_agent.sandbox.config import (
    DEFAULT_CPUS,
    DEFAULT_DNS_NAMESERVERS,
    DEFAULT_EXEC_TIMEOUT,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_MEMORY_MIB,
    resolve_data_dir,
)

logger = logging.getLogger(__name__)

SETTINGS_VERSION = 1
SETTINGS_FILENAME = "settings.json"
SECRETS_FILENAME = "secrets.json"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"

KIND_OPENROUTER = "openrouter"
KIND_OLLAMA = "ollama"
KIND_CUSTOM = "custom"
PLATFORM_KINDS = (KIND_OPENROUTER, KIND_OLLAMA, KIND_CUSTOM)

_cache: dict[str, Any] | None = None
_secrets_cache: dict[str, Any] | None = None


def settings_path() -> Path:
    return resolve_data_dir() / SETTINGS_FILENAME


def secrets_path() -> Path:
    return resolve_data_dir() / SECRETS_FILENAME


def _default_platform(kind: str) -> dict[str, Any]:
    if kind == KIND_OLLAMA:
        return {
            "id": "ollama",
            "name": "Ollama",
            "kind": KIND_OLLAMA,
            "base_url": OLLAMA_BASE_URL,
            "enabled": True,
            "site_url": "",
            "site_name": "",
            "models": [{"id": "gemma4", "enabled": True}],
        }
    if kind == KIND_CUSTOM:
        return {
            "id": "custom",
            "name": "Custom",
            "kind": KIND_CUSTOM,
            "base_url": "",
            "enabled": True,
            "site_url": "",
            "site_name": "",
            "models": [{"id": "gpt-4o", "enabled": True}],
        }
    return {
        "id": "openrouter",
        "name": "OpenRouter",
        "kind": KIND_OPENROUTER,
        "base_url": OPENROUTER_BASE_URL,
        "enabled": True,
        "site_url": "http://localhost",
        "site_name": "deep-agent",
        "models": [{"id": "anthropic/claude-sonnet-4.5", "enabled": True}],
    }


def default_settings() -> dict[str, Any]:
    platform = _default_platform(KIND_OPENROUTER)
    return {
        "version": SETTINGS_VERSION,
        "setup_complete": False,
        "active_platform_id": platform["id"],
        "default_model": platform["models"][0]["id"],
        "temperature": 0.3,
        "platforms": [platform],
        "sandbox": {
            "network": False,
            "memory_mib": DEFAULT_MEMORY_MIB,
            "cpus": DEFAULT_CPUS,
            "dns_nameservers": ",".join(DEFAULT_DNS_NAMESERVERS),
            "exec_timeout": DEFAULT_EXEC_TIMEOUT,
            "idle_timeout": DEFAULT_IDLE_TIMEOUT,
        },
    }


def default_secrets() -> dict[str, Any]:
    return {"platforms": {}}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any], *, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    if secret:
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def _normalize_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_settings()
    if not raw:
        return base
    out = deepcopy(base)
    out["setup_complete"] = bool(raw.get("setup_complete", False))
    out["active_platform_id"] = str(raw.get("active_platform_id") or out["active_platform_id"])
    out["default_model"] = str(raw.get("default_model") or out["default_model"])
    try:
        out["temperature"] = float(raw.get("temperature", out["temperature"]))
    except (TypeError, ValueError):
        pass
    platforms = raw.get("platforms")
    if isinstance(platforms, list) and platforms:
        normalized: list[dict[str, Any]] = []
        for item in platforms:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or KIND_CUSTOM).lower()
            if kind not in PLATFORM_KINDS:
                kind = KIND_CUSTOM
            pid = str(item.get("id") or kind).strip() or kind
            models_in = item.get("models") or []
            models: list[dict[str, Any]] = []
            if isinstance(models_in, list):
                for m in models_in:
                    if isinstance(m, dict) and m.get("id"):
                        models.append(
                            {"id": str(m["id"]).strip(), "enabled": bool(m.get("enabled", True))}
                        )
                    elif isinstance(m, str) and m.strip():
                        models.append({"id": m.strip(), "enabled": True})
            if not models:
                models = _default_platform(kind)["models"]
            base_url = str(item.get("base_url") or "").strip().rstrip("/")
            if kind == KIND_OPENROUTER and not base_url:
                base_url = OPENROUTER_BASE_URL
            if kind == KIND_OLLAMA and not base_url:
                base_url = OLLAMA_BASE_URL
            normalized.append(
                {
                    "id": pid,
                    "name": str(item.get("name") or pid),
                    "kind": kind,
                    "base_url": base_url,
                    "enabled": bool(item.get("enabled", True)),
                    "site_url": str(item.get("site_url") or ""),
                    "site_name": str(item.get("site_name") or ""),
                    "models": models,
                }
            )
        if normalized:
            out["platforms"] = normalized
    sandbox_in = raw.get("sandbox")
    if isinstance(sandbox_in, dict):
        sb = out["sandbox"]
        if "network" in sandbox_in:
            sb["network"] = bool(sandbox_in["network"])
        for key in ("memory_mib", "cpus", "exec_timeout", "idle_timeout"):
            if key in sandbox_in:
                try:
                    sb[key] = int(sandbox_in[key])
                except (TypeError, ValueError):
                    pass
        if "dns_nameservers" in sandbox_in:
            sb["dns_nameservers"] = str(sandbox_in["dns_nameservers"] or "")
    # Ensure active platform exists.
    ids = {p["id"] for p in out["platforms"]}
    if out["active_platform_id"] not in ids:
        out["active_platform_id"] = out["platforms"][0]["id"]
    return out


def _normalize_secrets(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = default_secrets()
    if not raw or not isinstance(raw.get("platforms"), dict):
        return out
    for pid, entry in raw["platforms"].items():
        if not isinstance(entry, dict):
            continue
        keys = entry.get("api_keys") or []
        if isinstance(keys, str):
            keys = [keys]
        cleaned = [str(k).strip() for k in keys if str(k).strip()]
        if cleaned:
            out["platforms"][str(pid)] = {"api_keys": cleaned}
    return out


def load_settings(*, force: bool = False) -> dict[str, Any]:
    global _cache, _secrets_cache
    if _cache is not None and not force:
        return deepcopy(_cache)

    path = settings_path()
    secrets_file = secrets_path()
    raw = _read_json(path)
    secrets_raw = _read_json(secrets_file)

    if raw is None:
        # No settings.json yet — start fresh (Setup UI). Do not seed from .env.
        settings = default_settings()
        secrets = default_secrets()
        _cache = settings
        _secrets_cache = secrets
        apply_runtime_env(settings, secrets)
        return deepcopy(settings)

    settings = _normalize_settings(raw)
    secrets = _normalize_secrets(secrets_raw)
    _cache = settings
    _secrets_cache = secrets
    apply_runtime_env(settings, secrets)
    return deepcopy(settings)


def load_secrets(*, force: bool = False) -> dict[str, Any]:
    global _secrets_cache
    if _secrets_cache is not None and not force:
        return deepcopy(_secrets_cache)
    load_settings(force=force)
    assert _secrets_cache is not None
    return deepcopy(_secrets_cache)


def save_settings(settings: dict[str, Any], secrets: dict[str, Any] | None = None) -> dict[str, Any]:
    global _cache, _secrets_cache
    normalized = _normalize_settings(settings)
    if secrets is None:
        secrets = _secrets_cache or default_secrets()
    secrets_norm = _normalize_secrets(secrets)
    _write_json(settings_path(), normalized)
    _write_json(secrets_path(), secrets_norm, secret=True)
    _cache = normalized
    _secrets_cache = secrets_norm
    apply_runtime_env(normalized, secrets_norm)
    return deepcopy(normalized)


def reset_settings_cache() -> None:
    global _cache, _secrets_cache
    _cache = None
    _secrets_cache = None


def setup_required() -> bool:
    return not bool(load_settings().get("setup_complete"))


def active_platform(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings or load_settings()
    pid = cfg.get("active_platform_id")
    for platform in cfg.get("platforms") or []:
        if platform.get("id") == pid:
            return platform
    platforms = cfg.get("platforms") or []
    return platforms[0] if platforms else _default_platform(KIND_OPENROUTER)


def platform_api_key(platform_id: str, secrets: dict[str, Any] | None = None) -> str:
    sec = secrets if secrets is not None else load_secrets()
    entry = (sec.get("platforms") or {}).get(platform_id) or {}
    keys = entry.get("api_keys") or []
    return str(keys[0]).strip() if keys else ""


def has_api_key_for_active() -> bool:
    cfg = load_settings()
    platform = active_platform(cfg)
    if platform.get("kind") == KIND_OLLAMA:
        return True
    return bool(platform_api_key(platform["id"]))


def apply_runtime_env(settings: dict[str, Any], secrets: dict[str, Any] | None = None) -> None:
    """Push active settings into ``os.environ`` for legacy readers."""
    platform = active_platform(settings)
    kind = platform.get("kind") or KIND_OPENROUTER
    os.environ["DEEPAGENT_LLM_PROVIDER"] = kind
    base_url = str(platform.get("base_url") or "").strip().rstrip("/")
    if kind == KIND_OPENROUTER:
        # OpenRouter never uses a leftover local base URL.
        os.environ.pop("DEEPAGENT_LLM_BASE_URL", None)
    elif base_url:
        os.environ["DEEPAGENT_LLM_BASE_URL"] = base_url
    else:
        os.environ.pop("DEEPAGENT_LLM_BASE_URL", None)

    model = str(settings.get("default_model") or "").strip()
    if model:
        os.environ["OPENROUTER_MODEL"] = model
    os.environ["OPENROUTER_TEMPERATURE"] = str(settings.get("temperature", 0.3))
    if platform.get("site_url"):
        os.environ["OPENROUTER_SITE_URL"] = str(platform["site_url"])
    if platform.get("site_name"):
        os.environ["OPENROUTER_SITE_NAME"] = str(platform["site_name"])

    key = platform_api_key(platform["id"], secrets)
    if key:
        os.environ["OPENROUTER_API_KEY"] = key
    elif kind == KIND_OLLAMA:
        os.environ.setdefault("OPENROUTER_API_KEY", "ollama")
    else:
        # Do not delete a process-level override set by the test harness before load.
        pass

    sandbox = settings.get("sandbox") or {}
    os.environ["DEEPAGENT_NETWORK_ACCESS"] = "true" if sandbox.get("network") else "false"
    os.environ["DEEPAGENT_SANDBOX_MEMORY"] = str(sandbox.get("memory_mib", DEFAULT_MEMORY_MIB))
    os.environ["DEEPAGENT_SANDBOX_CPUS"] = str(sandbox.get("cpus", DEFAULT_CPUS))
    os.environ["DEEPAGENT_EXEC_TIMEOUT"] = str(sandbox.get("exec_timeout", DEFAULT_EXEC_TIMEOUT))
    os.environ["DEEPAGENT_SANDBOX_IDLE_TIMEOUT"] = str(
        sandbox.get("idle_timeout", DEFAULT_IDLE_TIMEOUT)
    )
    dns = sandbox.get("dns_nameservers")
    if dns is None:
        os.environ.pop("DEEPAGENT_DNS_NAMESERVERS", None)
    else:
        os.environ["DEEPAGENT_DNS_NAMESERVERS"] = str(dns)


def public_settings_view() -> dict[str, Any]:
    """Settings payload safe for the Settings / Setup UI (keys masked)."""
    cfg = load_settings()
    secrets = load_secrets()
    platforms_out: list[dict[str, Any]] = []
    for platform in cfg.get("platforms") or []:
        pid = platform["id"]
        key = platform_api_key(pid, secrets)
        masked = ""
        if key:
            masked = f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "••••••••"
        platforms_out.append(
            {
                **platform,
                "api_key_set": bool(key),
                "api_key_masked": masked,
            }
        )
    return {
        "version": cfg.get("version", SETTINGS_VERSION),
        "setup_complete": bool(cfg.get("setup_complete")),
        "setup_required": not bool(cfg.get("setup_complete")),
        "active_platform_id": cfg.get("active_platform_id"),
        "default_model": cfg.get("default_model"),
        "temperature": cfg.get("temperature"),
        "platforms": platforms_out,
        "sandbox": cfg.get("sandbox"),
        "settings_path": str(settings_path()),
        "secrets_path": str(secrets_path()),
    }


def update_from_ui(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Settings / Setup form payload and persist.

    Expected keys (all optional except when completing setup):
      active_platform_id, default_model, temperature, setup_complete,
      platform: { id, name, kind, base_url, site_url, site_name, api_key },
      sandbox: { network, memory_mib, cpus, dns_nameservers, exec_timeout, idle_timeout }
    """
    cfg = load_settings()
    secrets = load_secrets()

    platform_in = payload.get("platform") if isinstance(payload.get("platform"), dict) else {}
    kind = str(platform_in.get("kind") or active_platform(cfg).get("kind") or KIND_OPENROUTER).lower()
    if kind not in PLATFORM_KINDS:
        kind = KIND_OPENROUTER
    pid = str(platform_in.get("id") or kind).strip() or kind

    existing = None
    for p in cfg["platforms"]:
        if p["id"] == pid:
            existing = p
            break
    if existing is None:
        existing = _default_platform(kind)
        existing["id"] = pid
        cfg["platforms"].append(existing)

    existing["kind"] = kind
    existing["name"] = str(platform_in.get("name") or existing.get("name") or pid)
    base_url = str(platform_in.get("base_url") or existing.get("base_url") or "").strip().rstrip("/")
    if kind == KIND_OPENROUTER:
        existing["base_url"] = OPENROUTER_BASE_URL
    elif kind == KIND_OLLAMA:
        existing["base_url"] = base_url or OLLAMA_BASE_URL
    else:
        existing["base_url"] = base_url
    if "site_url" in platform_in:
        existing["site_url"] = str(platform_in.get("site_url") or "")
    if "site_name" in platform_in:
        existing["site_name"] = str(platform_in.get("site_name") or "")
    existing["enabled"] = True

    model = str(payload.get("default_model") or cfg.get("default_model") or "").strip()
    if model:
        cfg["default_model"] = model
        # Keep a single enabled model entry for the active platform for now.
        existing["models"] = [{"id": model, "enabled": True}]

    cfg["active_platform_id"] = pid
    if "temperature" in payload and payload["temperature"] is not None:
        try:
            cfg["temperature"] = float(payload["temperature"])
        except (TypeError, ValueError):
            pass

    api_key = platform_in.get("api_key")
    if isinstance(api_key, str):
        cleaned = api_key.strip()
        if cleaned and "…" not in cleaned and not cleaned.startswith("••••"):
            secrets.setdefault("platforms", {})[pid] = {"api_keys": [cleaned]}

    sandbox_in = payload.get("sandbox") if isinstance(payload.get("sandbox"), dict) else None
    if sandbox_in:
        sb = cfg["sandbox"]
        if "network" in sandbox_in:
            sb["network"] = bool(sandbox_in["network"])
        for key in ("memory_mib", "cpus", "exec_timeout", "idle_timeout"):
            if key in sandbox_in and sandbox_in[key] is not None and str(sandbox_in[key]) != "":
                try:
                    sb[key] = int(sandbox_in[key])
                except (TypeError, ValueError):
                    pass
        if "dns_nameservers" in sandbox_in:
            sb["dns_nameservers"] = str(sandbox_in["dns_nameservers"] or "")

    if payload.get("setup_complete") is True:
        cfg["setup_complete"] = True
    elif payload.get("setup_complete") is False:
        cfg["setup_complete"] = False

    # Completing setup requires a usable provider.
    if cfg.get("setup_complete"):
        if kind != KIND_OLLAMA and not platform_api_key(pid, secrets):
            # Allow if process env still has a key (tests).
            if not (os.environ.get("OPENROUTER_API_KEY") or "").strip():
                raise ValueError("API key is required to finish setup for this provider.")
        if not (cfg.get("default_model") or "").strip():
            raise ValueError("Model is required to finish setup.")

    return save_settings(cfg, secrets)
