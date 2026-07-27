"""Settings platforms, model catalog, MCP API, runtime invalidation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from deep_agent.chat.sessions import store
from deep_agent.settings.store import (
    DEFAULT_OPENROUTER_MODELS,
    default_settings,
    load_settings,
    reset_settings_cache,
    temperature_for_model,
    update_from_ui,
)


def test_default_settings_seed_openrouter_models_with_luna_default() -> None:
    cfg = default_settings()
    assert cfg["default_model"] == "openai/gpt-5.6-luna"
    assert cfg["active_platform_id"] == "openrouter"
    models = cfg["platforms"][0]["models"]
    assert [m["id"] for m in models] == list(DEFAULT_OPENROUTER_MODELS)
    assert all(m["enabled"] for m in models)


@pytest.mark.asyncio
async def test_structured_settings_multi_model_and_temperature(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))
    put = await client.put(
        "/api/settings",
        json={
            "config": {
                "platforms": [
                    {
                        "id": "openrouter",
                        "name": "OpenRouter",
                        "kind": "openrouter",
                        "enabled": True,
                        "models": [
                            {"id": "a/model-1", "enabled": True, "temperature": 0.2},
                            {"id": "b/model-2", "enabled": True, "temperature": 0.9},
                        ],
                        "api_key": "sk-test-key-for-unit-tests",
                    },
                    {
                        "id": "ollama",
                        "name": "Ollama",
                        "kind": "ollama",
                        "enabled": True,
                        "base_url": "http://127.0.0.1:11434/v1",
                        "models": [{"id": "llama3.2", "enabled": True, "temperature": 0.1}],
                    },
                ],
                "default_model": "llama3.2",
            }
        },
    )
    assert put.status_code == 200
    cfg = put.json()["config"]
    assert cfg["default_model"] == "llama3.2"
    assert cfg["active_platform_id"] == "ollama"
    or_plat = next(p for p in cfg["platforms"] if p["id"] == "openrouter")
    assert len(or_plat["models"]) == 2
    assert or_plat["models"][0]["temperature"] == 0.2

    reset_settings_cache()
    loaded = load_settings(force=True)
    assert temperature_for_model(loaded, "llama3.2") == 0.1
    assert temperature_for_model(loaded, "b/model-2") == 0.9


@pytest.mark.asyncio
async def test_available_models_openrouter_and_ollama(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))
    await client.put(
        "/api/settings",
        json={
            "config": {
                "platforms": [
                    {
                        "id": "openrouter",
                        "kind": "openrouter",
                        "name": "OpenRouter",
                        "models": [{"id": "x", "enabled": True}],
                        "api_key": "sk-test-key-for-unit-tests",
                    },
                    {
                        "id": "ollama",
                        "kind": "ollama",
                        "name": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "models": [{"id": "gemma4", "enabled": True}],
                    },
                ],
                "default_model": "x",
            }
        },
    )

    class FakeResp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status
            self.text = str(payload)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception("http error")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            if "openrouter" in url:
                return FakeResp(
                    {"data": [{"id": "anthropic/claude-sonnet-4.5", "name": "Claude"}]}
                )
            if "/api/tags" in url:
                return FakeResp({"models": [{"name": "llama3.2:latest"}]})
            return FakeResp({"data": []})

    with patch("deep_agent.integrations.model_catalog.httpx.Client", FakeClient):
        or_resp = await client.get("/api/platforms/openrouter/models/available")
        assert or_resp.status_code == 200
        assert or_resp.json()["models"][0]["id"] == "anthropic/claude-sonnet-4.5"

        ol_resp = await client.get("/api/platforms/ollama/models/available")
        assert ol_resp.status_code == 200
        assert ol_resp.json()["models"][0]["id"] == "llama3.2:latest"

        missing = await client.get("/api/platforms/nope/models/available")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_model_test_endpoint(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return FakeResp()

    with patch("deep_agent.integrations.model_catalog.httpx.Client", FakeClient):
        resp = await client.post(
            "/api/platforms/openrouter/models/test",
            json={"model": "test-model"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "latency_ms" in body


@pytest.mark.asyncio
async def test_mcp_crud_roundtrip(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DEEPAGENT_MCP_CONFIG", str(data_dir / ".mcp.json"))

    get0 = await client.get("/api/mcp")
    assert get0.status_code == 200
    assert get0.json()["servers"] == {}

    put = await client.put(
        "/api/mcp",
        json={
            "servers": {
                "demo": {"command": "npx", "args": ["-y", "demo"]},
                "remote": {"url": "https://example.com/mcp", "bearer_token": "tok"},
            }
        },
    )
    assert put.status_code == 200
    assert set(put.json()["servers"]) == {"demo", "remote"}
    assert (data_dir / ".mcp.json").is_file()

    merge = await client.put(
        "/api/mcp",
        json={"merge": True, "servers": {"extra": {"command": "uvx", "args": ["x"]}}},
    )
    assert merge.status_code == 200
    assert "extra" in merge.json()["servers"]
    assert "demo" in merge.json()["servers"]

    bad = await client.put("/api/mcp", json={"servers": {"bad": {"foo": 1}}})
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_mcp_test_unknown_server(
    client: AsyncClient,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPAGENT_MCP_CONFIG", str(data_dir / ".mcp.json"))
    resp = await client.post("/api/mcp/missing/test")
    assert resp.status_code == 404


def test_invalidate_runtime_clears_caches() -> None:
    from deep_agent.chat.sessions import _McpRegistry

    store._sessions["s1"] = MagicMock()
    store._mcp_cache = _McpRegistry(tools=[], servers=[], failed=[])
    store.invalidate_runtime()
    assert store._sessions == {}
    assert store._mcp_cache is None


def test_update_from_ui_keeps_multiple_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(tmp_path))
    reset_settings_cache()
    update_from_ui(
        {
            "platforms": [
                {
                    "id": "openrouter",
                    "kind": "openrouter",
                    "name": "OpenRouter",
                    "models": [
                        {"id": "m1", "enabled": True, "temperature": 0.4},
                        {"id": "m2", "enabled": False, "temperature": 0.5},
                    ],
                    "api_key": "sk-abc",
                }
            ],
            "default_model": "m1",
        }
    )
    cfg = load_settings(force=True)
    assert len(cfg["platforms"][0]["models"]) == 2
    assert cfg["platforms"][0]["models"][1]["enabled"] is False
