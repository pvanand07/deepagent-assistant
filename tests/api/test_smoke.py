"""Basic API smoke tests."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from deep_agent.api.app import app, lifespan
from deep_agent.sandbox.manager import SandboxManager, reset_manager_for_tests


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "sandbox_healthy" in body
    assert "sandbox_degraded" in body
    assert "sandbox_starting" in body


@pytest.mark.asyncio
async def test_create_and_get_session(client: AsyncClient) -> None:
    create = await client.post("/api/sessions", json={"with_subagents": False})
    assert create.status_code == 201
    body = create.json()
    session_id = body["id"]
    assert body["active_run_id"] is None
    assert body["message_count"] == 0
    assert body["agent_ready"] is False

    get_resp = await client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 200
    got = get_resp.json()
    assert got["id"] == session_id
    assert got["agent_ready"] is False

    listed = await client.get("/api/sessions")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["sessions"]}
    assert session_id in ids

    # Workspace works without hydrating the agent.
    files = await client.get(f"/api/sessions/{session_id}/files")
    assert files.status_code == 200


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient, session_id: str) -> None:
    delete = await client.delete(f"/api/sessions/{session_id}")
    assert delete.status_code == 204
    missing = await client.get(f"/api/sessions/{session_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_lifespan_health_before_sandbox_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """/health must succeed as soon as DB is up, while sandbox is still starting."""
    from tests.conftest import _close_persistence, _reset_store

    data = tmp_path / "data"
    data.mkdir()
    work = tmp_path / "workspace"
    work.mkdir()
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(work))
    monkeypatch.setenv("DEEPAGENT_APP_DB", str(data / "app.sqlite"))
    monkeypatch.setenv("DEEPAGENT_MESSAGES_DB", str(data / "messages.sqlite"))
    monkeypatch.setenv("DEEPAGENT_CHECKPOINT_DB", str(data / "checkpoints.sqlite"))
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "stub")

    await _close_persistence()
    _reset_store()
    reset_manager_for_tests()

    gate = asyncio.Event()

    async def slow_startup(self) -> None:
        self.begin_startup()
        await gate.wait()
        self._loop = asyncio.get_running_loop()
        self._workdir = work
        self._network = False
        self._activate_backend(stub=True)
        self._starting = False

    monkeypatch.setattr(SandboxManager, "startup", slow_startup)

    transport = ASGITransport(app=app)
    async with lifespan(app):
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            health = await http.get("/health")
            assert health.status_code == 200
            body = health.json()
            assert body["sandbox_starting"] is True
            assert body["sandbox_healthy"] is False

            create = await http.post("/api/sessions", json={"with_subagents": False})
            assert create.status_code == 201
            assert create.json()["agent_ready"] is False

            gate.set()
            for _ in range(50):
                cfg = await http.get("/api/config")
                if not cfg.json().get("sandbox_starting"):
                    break
                await asyncio.sleep(0.05)
            cfg = await http.get("/api/config")
            assert cfg.json()["sandbox_healthy"] is True
            assert cfg.json()["sandbox_starting"] is False

    await _close_persistence()
    _reset_store()
    reset_manager_for_tests()


@pytest.mark.asyncio
async def test_config_reports_setup_required_when_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from deep_agent.chat.sessions import store
    from deep_agent.settings.store import default_settings, reset_settings_cache, save_settings
    from tests.conftest import _close_persistence, _reset_store

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data))
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(tmp_path / "ws"))
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "stub")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    await _close_persistence()
    _reset_store()
    reset_manager_for_tests()
    reset_settings_cache()
    cfg = default_settings()
    cfg["setup_complete"] = False
    save_settings(cfg, {"platforms": {}})

    from deep_agent.sandbox.manager import get_manager

    await store.startup()
    manager = get_manager()
    await manager.startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["setup_required"] is True
    await store.close()
    await manager.shutdown()
    reset_settings_cache()
