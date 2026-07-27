"""Unit tests for MCP partial-degrade loading and resilient tool calls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.types import CallToolResult

from deep_agent.integrations.mcp import (
    _resilient_mcp_interceptor,
    _server_semaphores,
    aload_mcp_tools,
    format_mcp_exception,
    iter_exception_tree,
)


def test_format_mcp_exception_never_empty() -> None:
    exc = httpx.ConnectError("")
    assert str(exc) == ""
    formatted = format_mcp_exception(exc)
    assert formatted
    assert "ConnectError" in formatted


def test_format_mcp_exception_unwraps_exception_group() -> None:
    nested = httpx.ConnectError("")
    group = ExceptionGroup("unhandled errors in a TaskGroup", [nested])
    formatted = format_mcp_exception(group)
    assert "ExceptionGroup" in formatted
    assert "ConnectError" in formatted


def test_iter_exception_tree_walks_children() -> None:
    leaf = ValueError("boom")
    group = ExceptionGroup("outer", [leaf])
    nodes = list(iter_exception_tree(group))
    assert nodes[0] is group
    assert leaf in nodes


@pytest.mark.asyncio
async def test_resilient_interceptor_returns_is_error_on_transport_failure() -> None:
    _server_semaphores.clear()
    interceptor = _resilient_mcp_interceptor()
    request = SimpleNamespace(server_name="iresearcher", name="web_fetch")

    async def boom(_req):
        raise httpx.ConnectError("")

    result = await interceptor(request, boom)
    assert isinstance(result, CallToolResult)
    assert result.isError is True
    text = result.content[0].text
    assert "iresearcher" in text
    assert "web_fetch" in text
    assert "ConnectError" in text


@pytest.mark.asyncio
async def test_resilient_interceptor_propagates_cancellation() -> None:
    interceptor = _resilient_mcp_interceptor()
    request = SimpleNamespace(server_name="iresearcher", name="web_fetch")

    async def cancelled(_req):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await interceptor(request, cancelled)


@pytest.mark.asyncio
async def test_resilient_interceptor_limits_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _server_semaphores.clear()
    monkeypatch.setenv("DEEPAGENT_MCP_MAX_CONCURRENT", "1")
    # Force a fresh semaphore with the new limit.
    from deep_agent.integrations import mcp as mcp_mod

    mcp_mod._server_semaphores.clear()

    interceptor = _resilient_mcp_interceptor()
    request = SimpleNamespace(server_name="iresearcher", name="web_fetch")
    active = 0
    max_active = 0
    gate = asyncio.Event()

    async def slow(_req):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await gate.wait()
        active -= 1
        return CallToolResult(content=[], isError=False)

    t1 = asyncio.create_task(interceptor(request, slow))
    t2 = asyncio.create_task(interceptor(request, slow))
    await asyncio.sleep(0.05)
    assert max_active == 1
    gate.set()
    await asyncio.gather(t1, t2)
    assert max_active == 1


@pytest.mark.asyncio
async def test_aload_mcp_tools_partial_degrade() -> None:
    connections = {
        "good": {"transport": "http", "url": "https://good.example/mcp"},
        "bad": {"transport": "http", "url": "https://bad.example/mcp"},
    }

    async def fake_one(name: str, conn: dict):
        if name == "bad":
            return name, [], {
                "name": "bad",
                "url": conn["url"],
                "error": "ConnectError: ConnectError('')",
            }
        tool = type("T", (), {"name": f"{name}_tool"})()
        return name, [tool], None

    with patch(
        "deep_agent.integrations.mcp._aload_one_server",
        new=AsyncMock(side_effect=fake_one),
    ):
        tools, ok, failed = await aload_mcp_tools(connections)

    assert ok == ["good"]
    assert len(tools) == 1
    assert getattr(tools[0], "name") == "good_tool"
    assert len(failed) == 1
    assert failed[0]["name"] == "bad"
    assert failed[0]["url"] == "https://bad.example/mcp"
    assert failed[0]["error"]


@pytest.mark.asyncio
async def test_aload_mcp_tools_gather_exception_is_captured() -> None:
    connections = {
        "boom": {"transport": "http", "url": "https://boom.example/mcp"},
    }

    with patch(
        "deep_agent.integrations.mcp._aload_one_server",
        new=AsyncMock(side_effect=httpx.ConnectError("")),
    ):
        tools, ok, failed = await aload_mcp_tools(connections)

    assert tools == []
    assert ok == []
    assert len(failed) == 1
    assert failed[0]["name"] == "boom"
    assert "ConnectError" in failed[0]["error"]
