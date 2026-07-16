"""Unit tests for MCP partial-degrade loading."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deep_agent.integrations.mcp import aload_mcp_tools, format_mcp_exception


def test_format_mcp_exception_never_empty() -> None:
    exc = httpx.ConnectError("")
    assert str(exc) == ""
    formatted = format_mcp_exception(exc)
    assert formatted
    assert "ConnectError" in formatted


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
