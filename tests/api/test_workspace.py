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


@pytest.mark.asyncio
async def test_preview_serves_html_and_sibling_assets(
    client: AsyncClient,
    session_id: str,
    workspace_dir,
) -> None:
    out = workspace_dir / "output"
    out.mkdir()
    (out / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head>'
        '<body><script src="script.js"></script></body></html>',
        encoding="utf-8",
    )
    (out / "styles.css").write_text("body { color: tomato; }", encoding="utf-8")
    (out / "script.js").write_text("window.__preview = true;", encoding="utf-8")

    html = await client.get(f"/api/sessions/{session_id}/preview/output/index.html")
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]
    assert b"styles.css" in html.content

    css = await client.get(f"/api/sessions/{session_id}/preview/output/styles.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert b"tomato" in css.content

    js = await client.get(f"/api/sessions/{session_id}/preview/output/script.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert b"__preview" in js.content

    missing = await client.get(f"/api/sessions/{session_id}/preview/output/missing.js")
    assert missing.status_code == 404

    escape = await client.get(f"/api/sessions/{session_id}/preview/../notes.txt")
    assert escape.status_code in {400, 404}