"""Shared fixtures: isolated SQLite, stub agent hydration, ASGI client."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from api import app
from session_persistence import AppDB, CheckpointManager, MessageDB
from sessions import SessionStore, store

from helpers.stubs import stub_build_session


async def _close_persistence() -> None:
    if AppDB._instance is not None:
        await AppDB._instance.close()
    if MessageDB._instance is not None:
        await MessageDB._instance.close()
    if CheckpointManager._instance is not None:
        await CheckpointManager._instance.close()


def _reset_store() -> None:
    store._sessions.clear()
    store._hydration_locks.clear()
    store._mcp_cache = None
    store._db = None
    store._messages = None
    store._checkpoints = None
    store.runs = None


@pytest.fixture
def workspace_dir(tmp_path):
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture
def data_dir(tmp_path):
    path = tmp_path / "data"
    path.mkdir()
    return path


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
    workspace_dir,
    data_dir,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(workspace_dir))
    monkeypatch.setenv("DEEPAGENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DEEPAGENT_APP_DB", str(data_dir / "app.sqlite"))
    monkeypatch.setenv("DEEPAGENT_MESSAGES_DB", str(data_dir / "messages.sqlite"))
    monkeypatch.setenv("DEEPAGENT_CHECKPOINT_DB", str(data_dir / "checkpoints.sqlite"))
    monkeypatch.setenv("DEEPAGENT_MAX_CONCURRENT_RUNS", "4")

    await _close_persistence()
    _reset_store()

    async def _build(self: SessionStore, meta):
        return await stub_build_session(self, meta)

    with patch.object(SessionStore, "_build_session", _build):
        await store.startup()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http
        await store.close()
    await _close_persistence()
    _reset_store()


@pytest.fixture
async def session_id(client: AsyncClient) -> str:
    response = await client.post(
        "/api/sessions",
        json={"with_subagents": False, "network": False},
    )
    response.raise_for_status()
    return response.json()["id"]
