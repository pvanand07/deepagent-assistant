"""Tests for rendered HTML inspection and screenshots."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deep_agent.sandbox import html_tools
from deep_agent.sandbox.html_tools import inspect_html_file, screenshot_html_file
from deep_agent.sandbox.tools import build_sandbox_tools


class _FakeManager:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir


@pytest.mark.asyncio
async def test_inspect_html_reports_rendered_structure(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<p>Initial</p>", encoding="utf-8")
    (tmp_path / "hero.png").write_bytes(b"\x89PNG\r\n")
    manager = _FakeManager(tmp_path)
    dom = """<html><head><title>Rendered title</title></head><body>
<h1>Primary heading</h1>
<a href="/details"><span>Read</span> more</a>
<img src="hero.png">
<form action="/send" method="post"><input><button>Send</button></form>
</body></html>"""
    stderr = "CONSOLE: Uncaught ReferenceError: missing is not defined\n"

    async def fake_chromium(args, timeout=30):
        del timeout
        assert "--dump-dom" in args
        assert any(a.startswith("file://") for a in args)
        return 0, dom, stderr

    with patch.object(html_tools, "_run_host_chromium", side_effect=fake_chromium):
        report = await inspect_html_file(manager, "/workspace/page.html")

    assert report["ok"] is False
    assert report["title"] == "Rendered title"
    assert report["headings"] == [{"level": "h1", "text": "Primary heading"}]
    assert report["links"] == [{"href": "/details", "text": "Read more"}]
    assert report["missing_image_alt"] == ["hero.png"]
    assert report["forms"] == [{"action": "/send", "method": "post", "inputs": 2}]
    assert "ReferenceError" in report["browser_errors"][0]
    assert report["missing_assets"] == []


@pytest.mark.asyncio
async def test_inspect_html_fails_on_missing_local_assets(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text(
        '<link rel="stylesheet" href="missing.css"><script src="gone.js"></script>',
        encoding="utf-8",
    )
    manager = _FakeManager(tmp_path)
    dom = """<html><head>
<link rel="stylesheet" href="missing.css">
<script src="gone.js"></script>
<title>x</title></head><body></body></html>"""

    async def fake_chromium(args, timeout=30):
        del args, timeout
        return 0, dom, ""

    with patch.object(html_tools, "_run_host_chromium", side_effect=fake_chromium):
        report = await inspect_html_file(manager, "page.html")

    assert report["ok"] is False
    assert set(report["missing_assets"]) == {"missing.css", "gone.js"}


@pytest.mark.asyncio
async def test_screenshot_html_writes_png(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<p>hi</p>", encoding="utf-8")
    manager = _FakeManager(tmp_path)

    async def fake_chromium(args, timeout=30):
        del timeout
        shot = next(a for a in args if a.startswith("--screenshot="))
        path = Path(shot.split("=", 1)[1])
        path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return 0, "", ""

    with patch.object(html_tools, "_run_host_chromium", side_effect=fake_chromium):
        result = await screenshot_html_file(
            manager, "page.html", output_path="out.png", overwrite=True
        )

    assert result["ok"] is True
    assert result["output_path"] == "/workspace/out.png"
    assert (tmp_path / "out.png").is_file()


@pytest.mark.asyncio
async def test_screenshot_html_rejects_non_png(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<p>hi</p>", encoding="utf-8")
    manager = _FakeManager(tmp_path)

    async def fake_chromium(args, timeout=30):
        del timeout
        shot = next(a for a in args if a.startswith("--screenshot="))
        Path(shot.split("=", 1)[1]).write_bytes(b"not-a-png")
        return 0, "", ""

    with patch.object(html_tools, "_run_host_chromium", side_effect=fake_chromium):
        result = await screenshot_html_file(
            manager, "page.html", output_path="out.png", overwrite=True
        )

    assert result["ok"] is False
    assert "PNG" in result["error"]
    assert not (tmp_path / "out.png").exists()


def test_build_sandbox_tools_includes_html_helpers() -> None:
    names = {tool.name for tool in build_sandbox_tools()}
    assert {
        "sandbox_status",
        "sandbox_wait",
        "cancel_sandbox_holder",
        "bundle_html",
        "inspect_html",
        "screenshot_html",
    } <= names
