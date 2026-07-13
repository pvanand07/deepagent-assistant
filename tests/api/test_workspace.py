"""Workspace file/folder API end-to-end tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_create_and_read_workspace_files(
    client: AsyncClient,
    session_id: str,
    workspace_dir,
) -> None:
    sample = workspace_dir / "notes.txt"
    sample.write_text("hello workspace", encoding="utf-8")

    listing = await client.get(f"/api/sessions/{session_id}/files")
    assert listing.status_code == 200
    names = {entry["name"] for entry in listing.json()["entries"]}
    assert "notes.txt" in names

    content = await client.get(
        f"/api/sessions/{session_id}/files/content",
        params={"path": "notes.txt"},
    )
    assert content.status_code == 200
    assert content.json()["content"] == "hello workspace"


@pytest.mark.asyncio
async def test_create_folder(client: AsyncClient, session_id: str) -> None:
    create = await client.post(
        f"/api/sessions/{session_id}/folders",
        json={"name": "artifacts", "parent": ""},
    )
    assert create.status_code == 201
    assert create.json()["path"] == "artifacts"

    folders = await client.get(f"/api/sessions/{session_id}/folders")
    assert folders.status_code == 200
    assert "artifacts" in folders.json()["folders"]

    duplicate = await client.post(
        f"/api/sessions/{session_id}/folders",
        json={"name": "artifacts", "parent": ""},
    )
    assert duplicate.status_code == 409
