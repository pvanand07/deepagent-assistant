"""OpenRouter model factory.

OpenRouter exposes an OpenAI-compatible `/chat/completions` API, so we reuse
`langchain_openai.ChatOpenAI` pointed at OpenRouter's base URL instead of
needing a separate integration package.

Required env var:
    OPENROUTER_API_KEY   - from https://openrouter.ai/keys

Optional env vars:
    OPENROUTER_MODEL      - default: "anthropic/claude-sonnet-4.5"
    OPENROUTER_SITE_URL   - sent as HTTP-Referer (OpenRouter attribution/rate-limit header)
    OPENROUTER_SITE_NAME  - sent as X-Title (shows up in OpenRouter's dashboard/logs)
    OPENROUTER_TEMPERATURE- default: 0.3
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


def get_openrouter_model(
    model: str | None = None,
    *,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
) -> ChatOpenAI:
    """Build a `ChatOpenAI` client routed through OpenRouter.

    Works with any tool-calling-capable model listed at
    https://openrouter.ai/models (filter by "Tools" support) -- e.g.
    "anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-3-pro",
    "qwen/qwen3-max", "deepseek/deepseek-v3.2".

    Raises:
        RuntimeError: If `OPENROUTER_API_KEY` is not set.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        msg = (
            "OPENROUTER_API_KEY is not set. Get a key at "
            "https://openrouter.ai/keys and put it in your .env file."
        )
        raise RuntimeError(msg)

    default_headers = {}
    if site_url := os.environ.get("OPENROUTER_SITE_URL"):
        default_headers["HTTP-Referer"] = site_url
    if site_name := os.environ.get("OPENROUTER_SITE_NAME"):
        default_headers["X-Title"] = site_name

    resolved_model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    resolved_temperature = (
        temperature
        if temperature is not None
        else float(os.environ.get("OPENROUTER_TEMPERATURE", "0.3"))
    )

    kwargs: dict = {
        "model": resolved_model,
        "api_key": api_key,
        "base_url": OPENROUTER_BASE_URL,
        "temperature": resolved_temperature,
        "default_headers": default_headers or None,
    }
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatOpenAI(**kwargs)
