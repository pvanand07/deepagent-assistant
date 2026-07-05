"""Load MCP tools for the deep agent via langchain-mcp-adapters.

Reads server definitions from ``.mcp.json`` (or ``DEEPAGENT_MCP_CONFIG``),
with optional env-var substitution in headers/tokens. See Context7 / deepagents
docs: https://docs.langchain.com/oss/python/deepagents/mcp
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

_PROJECT_ROOT = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes"}


def _expand_env(value: str) -> str:
    return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def _expand_mapping(values: dict[str, str]) -> dict[str, str]:
    return {key: _expand_env(str(val)) for key, val in values.items()}


def _normalize_transport(raw: str | None) -> str:
    if not raw:
        return "http"
    normalized = raw.lower().replace("-", "_")
    if normalized in {"http", "streamable_http", "sse", "websocket"}:
        return normalized
    if normalized in {"streamablehttp"}:
        return "streamable_http"
    return "http"


def _normalize_server_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("disabled"):
        return None

    if "command" in entry:
        conn: dict[str, Any] = {
            "transport": "stdio",
            "command": entry["command"],
        }
        if args := entry.get("args"):
            conn["args"] = list(args)
        if env := entry.get("env"):
            conn["env"] = _expand_mapping({str(k): str(v) for k, v in env.items()})
        return conn

    url = entry.get("url")
    if not url:
        return None

    conn = {
        "transport": _normalize_transport(entry.get("type") or entry.get("transport")),
        "url": _expand_env(str(url)),
    }
    headers = {str(k): str(v) for k, v in (entry.get("headers") or {}).items()}
    bearer = entry.get("bearer_token")
    if bearer:
        headers["Authorization"] = f"Bearer {_expand_env(str(bearer))}"
    if headers:
        conn["headers"] = _expand_mapping(headers)
    return conn


def _config_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("DEEPAGENT_MCP_CONFIG")
    if override:
        paths.append(Path(override))
    paths.extend(
        [
            _PROJECT_ROOT / ".mcp.json",
            _PROJECT_ROOT / ".deepagents" / ".mcp.json",
        ]
    )
    return paths


def _load_mcp_servers_from_file() -> dict[str, dict[str, Any]]:
    for path in _config_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read MCP config %s: %s", path, exc)
            continue
        servers = data.get("mcpServers") or data.get("mcp_servers")
        if isinstance(servers, dict):
            logger.info("Loaded MCP server config from %s", path)
            return servers
    return {}


def _env_fallback_servers() -> dict[str, dict[str, Any]]:
    """Built-in env-based entries when no ``.mcp.json`` is present."""
    servers: dict[str, dict[str, Any]] = {}
    iresearcher_url = os.environ.get(
        "IRESEARCHER_MCP_URL", "https://iresearcher-mcp.elevatics.site/mcp"
    )
    token = os.environ.get("IRESEARCHER_MCP_BEARER_TOKEN")
    if token:
        servers["iresearcher"] = {"url": iresearcher_url, "bearer_token": token}
    return servers


def load_mcp_connections() -> dict[str, dict[str, Any]]:
    """Return ``MultiServerMCPClient`` connection dict (server name -> config)."""
    if not _env_bool("DEEPAGENT_MCP_ENABLED", default=True):
        return {}

    raw_servers = _load_mcp_servers_from_file()
    if not raw_servers:
        raw_servers = _env_fallback_servers()

    connections: dict[str, dict[str, Any]] = {}
    for name, entry in raw_servers.items():
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_server_entry(entry)
        if normalized:
            connections[name] = normalized
    return connections


async def aload_mcp_tools(
    connections: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[BaseTool], list[str]]:
    """Connect to configured MCP servers and return (tools, server_names)."""
    resolved = connections if connections is not None else load_mcp_connections()
    if not resolved:
        return [], []

    client = MultiServerMCPClient(resolved, tool_name_prefix=True)
    tools = await client.get_tools()
    return tools, list(resolved.keys())


def load_mcp_tools(
    connections: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[BaseTool], list[str]]:
    """Synchronous wrapper around :func:`aload_mcp_tools`."""
    return asyncio.run(aload_mcp_tools(connections))
