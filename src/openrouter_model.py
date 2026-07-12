"""OpenAI-compatible chat model factory (OpenRouter, Ollama, custom).

All providers use ``langchain_openai.ChatOpenAI`` against an OpenAI-compatible
``/chat/completions`` endpoint.

Env vars:
    DEEPAGENT_LLM_PROVIDER   - ``openrouter`` (default) | ``ollama`` | ``custom``
    DEEPAGENT_LLM_BASE_URL   - override / required for ``custom``
    OPENROUTER_API_KEY       - API key (optional for Ollama)
    OPENROUTER_MODEL         - model id
    OPENROUTER_TEMPERATURE   - default 0.3
    OPENROUTER_SITE_URL      - OpenRouter HTTP-Referer (openrouter only)
    OPENROUTER_SITE_NAME     - OpenRouter X-Title (openrouter only)
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_OLLAMA_MODEL = "gemma4"
DEFAULT_PROVIDER = "openrouter"

PROVIDERS = ("openrouter", "ollama", "custom")


def llm_provider() -> str:
    raw = (os.environ.get("DEEPAGENT_LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    return raw if raw in PROVIDERS else DEFAULT_PROVIDER


def default_model_for_provider(provider: str | None = None) -> str:
    p = provider or llm_provider()
    if p == "ollama":
        return DEFAULT_OLLAMA_MODEL
    return DEFAULT_MODEL


def resolve_base_url(provider: str | None = None) -> str:
    p = provider or llm_provider()
    override = (os.environ.get("DEEPAGENT_LLM_BASE_URL") or "").strip()
    if p == "custom":
        if not override:
            raise RuntimeError(
                "DEEPAGENT_LLM_BASE_URL is required when DEEPAGENT_LLM_PROVIDER=custom "
                "(OpenAI-compatible base URL, e.g. https://api.example.com/v1)."
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
    provider = llm_provider()
    base_url = resolve_base_url(provider)

    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        if provider == "ollama":
            # Ollama's OpenAI shim ignores the key but ChatOpenAI requires one.
            api_key = "ollama"
        else:
            label = "API key" if provider == "custom" else "OPENROUTER_API_KEY"
            raise RuntimeError(
                f"{label} is not set. Add it in Settings or your .env file."
            )

    resolved_model = (
        model
        or (os.environ.get("OPENROUTER_MODEL") or "").strip()
        or default_model_for_provider(provider)
    )

    if temperature is not None:
        resolved_temperature = temperature
    else:
        raw_temp = (os.environ.get("OPENROUTER_TEMPERATURE") or "").strip()
        resolved_temperature = float(raw_temp) if raw_temp else 0.3

    default_headers = None
    if provider == "openrouter":
        headers: dict[str, str] = {}
        if site_url := (os.environ.get("OPENROUTER_SITE_URL") or "").strip():
            headers["HTTP-Referer"] = site_url
        if site_name := (os.environ.get("OPENROUTER_SITE_NAME") or "").strip():
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
