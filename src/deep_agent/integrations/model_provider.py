"""OpenAI-compatible chat model factory (OpenRouter, Ollama, custom).

Reads the active platform from ``deep_agent.settings`` (JSON). Process env can
still override for CI/tests after settings are applied.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_OLLAMA_MODEL = "gemma4"
DEFAULT_PROVIDER = "openrouter"

PROVIDERS = ("openrouter", "ollama", "custom")


def llm_provider() -> str:
    try:
        from deep_agent.settings.store import active_platform, load_settings

        kind = str(active_platform(load_settings()).get("kind") or "").strip().lower()
        if kind in PROVIDERS:
            return kind
    except Exception:
        pass
    raw = (os.environ.get("DEEPAGENT_LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    return raw if raw in PROVIDERS else DEFAULT_PROVIDER


def default_model_for_provider(provider: str | None = None) -> str:
    try:
        from deep_agent.settings.store import load_settings

        model = str(load_settings().get("default_model") or "").strip()
        if model:
            return model
    except Exception:
        pass
    p = provider or llm_provider()
    if p == "ollama":
        return DEFAULT_OLLAMA_MODEL
    return DEFAULT_MODEL


def resolve_base_url(provider: str | None = None) -> str:
    p = provider or llm_provider()
    try:
        from deep_agent.settings.store import active_platform, load_settings

        platform = active_platform(load_settings())
        kind = str(platform.get("kind") or p).lower()
        base = str(platform.get("base_url") or "").strip().rstrip("/")
        if kind == "openrouter":
            return OPENROUTER_BASE_URL
        if base:
            return base
        if kind == "ollama":
            return OLLAMA_BASE_URL
    except Exception:
        pass

    # Env fallback (tests / CI). OpenRouter never uses a custom override.
    if p == "openrouter":
        return OPENROUTER_BASE_URL
    override = (os.environ.get("DEEPAGENT_LLM_BASE_URL") or "").strip()
    if p == "custom":
        if not override:
            raise RuntimeError(
                "Base URL is required for a custom provider "
                "(OpenAI-compatible, e.g. https://api.example.com/v1)."
            )
        return override.rstrip("/")
    if override:
        return override.rstrip("/")
    if p == "ollama":
        return OLLAMA_BASE_URL
    return OPENROUTER_BASE_URL


def get_chat_model(
    model: str | None = None,
    *,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """Build a ``ChatOpenAI`` client for the configured provider."""
    from langchain_openai import ChatOpenAI

    from deep_agent.settings.store import (
        active_platform,
        load_secrets,
        load_settings,
        platform_api_key,
    )

    cfg = load_settings()
    platform = active_platform(cfg)
    provider = str(platform.get("kind") or llm_provider()).lower()
    base_url = resolve_base_url(provider)

    api_key = platform_api_key(platform["id"], load_secrets())
    if not api_key:
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        if provider == "ollama":
            api_key = "ollama"
        else:
            label = "API key" if provider == "custom" else "OpenRouter API key"
            raise RuntimeError(
                f"{label} is not set. Finish Setup or open Settings to add one."
            )

    resolved_model = (
        model
        or str(cfg.get("default_model") or "").strip()
        or (os.environ.get("OPENROUTER_MODEL") or "").strip()
        or default_model_for_provider(provider)
    )

    if temperature is not None:
        resolved_temperature = temperature
    else:
        try:
            resolved_temperature = float(cfg.get("temperature", 0.3))
        except (TypeError, ValueError):
            raw_temp = (os.environ.get("OPENROUTER_TEMPERATURE") or "").strip()
            resolved_temperature = float(raw_temp) if raw_temp else 0.3

    default_headers = None
    if provider == "openrouter":
        headers: dict[str, str] = {}
        site_url = str(platform.get("site_url") or "").strip() or (
            os.environ.get("OPENROUTER_SITE_URL") or ""
        ).strip()
        site_name = str(platform.get("site_name") or "").strip() or (
            os.environ.get("OPENROUTER_SITE_NAME") or ""
        ).strip()
        if site_url:
            headers["HTTP-Referer"] = site_url
        if site_name:
            headers["X-Title"] = site_name
        default_headers = headers or None

    kwargs: dict = {
        "model": resolved_model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": resolved_temperature,
        "default_headers": default_headers,
    }
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatOpenAI(**kwargs)


def get_openrouter_model(
    model: str | None = None,
    *,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """Backward-compatible alias for ``get_chat_model``."""
    return get_chat_model(
        model=model,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )
