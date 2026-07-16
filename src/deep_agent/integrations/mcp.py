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

from deep_agent.sandbox.env import env_bool

logger = logging.getLogger(__name__)

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# failed entry: {"name": str, "url": str, "error": str}
McpFailedServer = dict[str, str]


def format_mcp_exception(exc: BaseException) -> str:
    """Human-readable error; never empty (ConnectError often has blank str())."""
    msg = str(exc).strip()
    if msg:
        return f"{type(exc).__name__}: {msg}"
    rep = repr(exc).strip()
    if rep:
        return f"{type(exc).__name__}: {rep}"
    return type(exc).__name__


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
    """Search order: ``DEEPAGENT_MCP_CONFIG``, then desktop AppData, then repo."""
    from deep_agent.sandbox.config import is_desktop_mode, resolve_data_dir

    paths: list[Path] = []
    override = os.environ.get("DEEPAGENT_MCP_CONFIG")
    if override:
        paths.append(Path(override))
        return paths
    if is_desktop_mode() or os.environ.get("DEEPAGENT_DATA_DIR"):
        paths.append(resolve_data_dir() / ".mcp.json")
    paths.extend(
        [
            _PROJECT_ROOT / ".mcp.json",
            _PROJECT_ROOT / ".deepagents" / ".mcp.json",
        ]
    )
    return paths


def mcp_config_path() -> Path:
    """Writable path for MCP config (create here on PUT)."""
    return _config_paths()[0]


def read_mcp_servers_raw() -> tuple[Path | None, dict[str, dict[str, Any]]]:
    """Return (path used, servers dict). Path is None if nothing on disk."""
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
            cleaned = {
                str(name): entry
                for name, entry in servers.items()
                if isinstance(entry, dict)
            }
            return path, cleaned
    return None, {}


def validate_mcp_server_entry(name: str, entry: dict[str, Any]) -> None:
    if not name.strip():
        raise ValueError("Server name is required.")
    if not isinstance(entry, dict):
        raise ValueError(f"Server {name!r} must be an object.")
    has_cmd = bool(entry.get("command"))
    has_url = bool(entry.get("url"))
    if not has_cmd and not has_url:
        raise ValueError(f'Server {name!r} needs either "command" or "url".')


def save_mcp_servers(servers: dict[str, Any], *, merge: bool = False) -> dict[str, dict[str, Any]]:
    """Write ``mcpServers`` to the writable config path. Returns saved servers."""
    if not isinstance(servers, dict):
        raise ValueError("servers must be an object.")
    path = mcp_config_path()
    existing: dict[str, dict[str, Any]] = {}
    if merge and path.is_file():
        _, existing = read_mcp_servers_raw()
        # Prefer the writable path contents if it exists.
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                raw = data.get("mcpServers") or data.get("mcp_servers") or {}
                if isinstance(raw, dict):
                    existing = {
                        str(k): v for k, v in raw.items() if isinstance(v, dict)
                    }
            except (OSError, json.JSONDecodeError):
                pass

    out: dict[str, dict[str, Any]] = dict(existing) if merge else {}
    for name, entry in servers.items():
        if entry is None:
            out.pop(str(name), None)
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"Server {name!r} must be an object.")
        validate_mcp_server_entry(str(name), entry)
        out[str(name)] = entry

    for name, entry in out.items():
        validate_mcp_server_entry(name, entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mcpServers": out}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Wrote MCP config (%d servers) to %s", len(out), path)
    return out


async def test_mcp_server(name: str) -> dict[str, Any]:
    """Connect to one MCP server and list tools."""
    _, servers = read_mcp_servers_raw()
    if not servers:
        servers = _env_fallback_servers()
    entry = servers.get(name)
    if entry is None:
        raise KeyError(f"Unknown MCP server: {name}")
    conn = _normalize_server_entry(entry)
    if conn is None:
        raise ValueError(f"MCP server {name!r} is disabled or invalid.")
    try:
        tools, ok, failed = await asyncio.wait_for(
            aload_mcp_tools({name: conn}),
            timeout=60.0,
        )
        if failed:
            return {
                "ok": False,
                "tool_count": None,
                "error": failed[0].get("error") or "MCP connect failed",
            }
        if name not in ok:
            return {"ok": False, "tool_count": None, "error": "MCP connect failed"}
        return {"ok": True, "tool_count": len(tools), "error": None}
    except Exception as exc:
        return {"ok": False, "tool_count": None, "error": format_mcp_exception(exc)}


def _load_mcp_servers_from_file() -> dict[str, dict[str, Any]]:
    _, servers = read_mcp_servers_raw()
    return servers


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
    if not env_bool("DEEPAGENT_MCP_ENABLED", default=True):
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


def _server_endpoint(conn: dict[str, Any]) -> str:
    if url := conn.get("url"):
        return str(url)
    command = conn.get("command")
    args = conn.get("args") or []
    if command:
        parts = [str(command), *[str(a) for a in args]]
        return " ".join(parts)
    return ""


async def _aload_one_server(
    name: str, conn: dict[str, Any]
) -> tuple[str, list[Any], McpFailedServer | None]:
    """Load tools for a single MCP server. Never raises."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    endpoint = _server_endpoint(conn)
    try:
        client = MultiServerMCPClient({name: conn}, tool_name_prefix=True)
        tools = await client.get_tools(server_name=name)
        return name, list(tools), None
    except Exception as exc:
        error = format_mcp_exception(exc)
        logger.warning(
            "MCP server connect failed name=%s url=%s exc_type=%s error=%r",
            name,
            endpoint,
            type(exc).__name__,
            error,
            exc_info=True,
        )
        return name, [], {"name": name, "url": endpoint, "error": error}


async def aload_mcp_tools(
    connections: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[Any], list[str], list[McpFailedServer]]:
    """Connect to configured MCP servers independently.

    Returns:
        ``(tools, ok_servers, failed)`` where ``failed`` is a list of
        ``{name, url, error}`` for servers that did not load. One bad server
        does not block the others.
    """
    resolved = connections if connections is not None else load_mcp_connections()
    if not resolved:
        return [], [], []

    results = await asyncio.gather(
        *(_aload_one_server(name, conn) for name, conn in resolved.items()),
        return_exceptions=True,
    )

    tools: list[Any] = []
    ok_servers: list[str] = []
    failed: list[McpFailedServer] = []

    for (name, conn), result in zip(resolved.items(), results, strict=True):
        if isinstance(result, BaseException):
            endpoint = _server_endpoint(conn)
            error = format_mcp_exception(result)
            logger.warning(
                "MCP server connect failed name=%s url=%s exc_type=%s error=%r",
                name,
                endpoint,
                type(result).__name__,
                error,
                exc_info=result,
            )
            failed.append({"name": name, "url": endpoint, "error": error})
            continue
        server_name, server_tools, fail = result
        if fail is not None:
            failed.append(fail)
            continue
        ok_servers.append(server_name)
        tools.extend(server_tools)

    if failed:
        logger.info(
            "MCP partial load: %d ok (%s), %d failed (%s)",
            len(ok_servers),
            ", ".join(ok_servers) or "-",
            len(failed),
            ", ".join(f["name"] for f in failed),
        )
    return tools, ok_servers, failed


def load_mcp_tools(
    connections: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[Any], list[str], list[McpFailedServer]]:
    """Synchronous wrapper around :func:`aload_mcp_tools`.

    Prefer ``await aload_mcp_tools()`` on the app event loop. This sync path is
    for CLI / offline use only (spawns a nested loop when called from a thread).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(aload_mcp_tools(connections))

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, aload_mcp_tools(connections)).result()
