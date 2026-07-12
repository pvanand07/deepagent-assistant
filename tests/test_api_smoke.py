"""Basic API smoke tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "sandbox_healthy" in body
    assert "sandbox_degraded" in body


@pytest.mark.asyncio
async def test_create_and_get_session(client: AsyncClient) -> None:
    create = await client.post("/api/sessions", json={"with_subagents": False})
    assert create.status_code == 201
    body = create.json()
    session_id = body["id"]
    assert body["active_run_id"] is None
    assert body["message_count"] == 0

    get_resp = await client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == session_id

    listed = await client.get("/api/sessions")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["sessions"]}
    assert session_id in ids


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient, session_id: str) -> None:
    delete = await client.delete(f"/api/sessions/{session_id}")
    assert delete.status_code == 204
    missing = await client.get(f"/api/sessions/{session_id}")
    assert missing.status_code == 404
