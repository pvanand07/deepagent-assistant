"""Fetch available models from OpenRouter / Ollama / OpenAI-compatible APIs."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from deep_agent.settings.store import (
    KIND_OLLAMA,
    KIND_OPENROUTER,
    get_platform_by_id,
    load_secrets,
    load_settings,
    platform_api_key,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}

CATALOG_TIMEOUT_S = 30.0
TEST_TIMEOUT_S = 45.0


def _ollama_host(base_url: str) -> str:
    """Strip trailing /v1 so we can hit native Ollama /api/tags."""
    raw = (base_url or "").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    return raw or "http://127.0.0.1:11434"


def clear_catalog_cache(platform_id: str | None = None) -> None:
    if platform_id is None:
        _cache.clear()
    else:
        _cache.pop(platform_id, None)


def list_available_models(
    platform_id: str,
    *,
    query: str = "",
    force: bool = False,
) -> list[dict[str, str]]:
    """Return ``[{id, name}]`` for a configured platform."""
    cfg = load_settings()
    platform = get_platform_by_id(platform_id, cfg)
    if platform is None:
        raise KeyError(f"Unknown platform: {platform_id}")

    now = time.monotonic()
    if not force and platform_id in _cache:
        cached_at, models = _cache[platform_id]
        if now - cached_at < _CACHE_TTL_S:
            return _filter_models(models, query)

    kind = str(platform.get("kind") or "").lower()
    base_url = str(platform.get("base_url") or "").strip().rstrip("/")
    key = platform_api_key(platform_id, load_secrets())

    if kind == KIND_OPENROUTER:
        models = _fetch_openrouter_models(key)
    elif kind == KIND_OLLAMA:
        models = _fetch_ollama_models(base_url or "http://127.0.0.1:11434/v1")
    else:
        if not base_url:
            raise ValueError("Custom platform requires a base URL.")
        if not key:
            raise ValueError("API key is required to list models for this platform.")
        models = _fetch_openai_models(base_url, key)

    _cache[platform_id] = (now, models)
    return _filter_models(models, query)


def _filter_models(models: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    q = (query or "").strip().lower()
    if not q:
        return list(models)
    return [m for m in models if q in m["id"].lower() or q in (m.get("name") or "").lower()]


def _fetch_openrouter_models(api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError("OpenRouter API key is required to list models.")
    url = "https://openrouter.ai/api/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=CATALOG_TIMEOUT_S) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    out: list[dict[str, str]] = []
    for item in data.get("data") or []:
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        name = str(item.get("name") or mid).strip()
        out.append({"id": mid, "name": name})
    out.sort(key=lambda m: m["id"].lower())
    return out


def _fetch_ollama_models(base_url: str) -> list[dict[str, str]]:
    host = _ollama_host(base_url)
    url = f"{host}/api/tags"
    with httpx.Client(timeout=CATALOG_TIMEOUT_S) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[dict[str, str]] = []
    for item in data.get("models") or []:
        mid = str(item.get("name") or item.get("model") or "").strip()
        if not mid:
            continue
        out.append({"id": mid, "name": mid})
    out.sort(key=lambda m: m["id"].lower())
    return out


def _fetch_openai_models(base_url: str, api_key: str) -> list[dict[str, str]]:
    root = base_url.rstrip("/")
    url = f"{root}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=CATALOG_TIMEOUT_S) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    raw = data.get("data") if isinstance(data, dict) else data
    out: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append({"id": item.strip(), "name": item.strip()})
            elif isinstance(item, dict):
                mid = str(item.get("id") or "").strip()
                if mid:
                    out.append({"id": mid, "name": str(item.get("name") or mid)})
    out.sort(key=lambda m: m["id"].lower())
    return out


def test_model(platform_id: str, model: str) -> dict[str, Any]:
    """Run a tiny chat completion against the platform; return ok/latency/error."""
    cfg = load_settings()
    platform = get_platform_by_id(platform_id, cfg)
    if platform is None:
        raise KeyError(f"Unknown platform: {platform_id}")

    mid = (model or "").strip()
    if not mid:
        raise ValueError("model is required")

    kind = str(platform.get("kind") or "").lower()
    base_url = str(platform.get("base_url") or "").strip().rstrip("/")
    if kind == KIND_OPENROUTER:
        base_url = "https://openrouter.ai/api/v1"
    elif kind == KIND_OLLAMA:
        base_url = base_url or "http://127.0.0.1:11434/v1"
    elif not base_url:
        raise ValueError("Custom platform requires a base URL.")

    key = platform_api_key(platform_id, load_secrets())
    if not key:
        if kind == KIND_OLLAMA:
            key = "ollama"
        else:
            raise ValueError("API key is required to test this model.")

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if kind == KIND_OPENROUTER:
        site_url = str(platform.get("site_url") or "").strip()
        site_name = str(platform.get("site_name") or "").strip()
        if site_url:
            headers["HTTP-Referer"] = site_url
        if site_name:
            headers["X-Title"] = site_name

    body = {
        "model": mid,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=TEST_TIMEOUT_S) as client:
            resp = client.post(url, headers=headers, json=body)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if resp.status_code >= 400:
                detail = resp.text[:500]
                try:
                    err = resp.json()
                    detail = str(
                        err.get("error", {}).get("message")
                        if isinstance(err.get("error"), dict)
                        else err.get("error") or err.get("message") or detail
                    )
                except Exception:
                    pass
                return {"ok": False, "latency_ms": latency_ms, "error": detail}
            return {"ok": True, "latency_ms": latency_ms, "error": None}
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "error": str(exc)}
