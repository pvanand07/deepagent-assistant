"""Tests for rendered HTML inspection and screenshots."""

from __future__ import annotations

import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from deep_agent.sandbox.html_tools import inspect_html_file, screenshot_html_file
from deep_agent.sandbox.tools import build_sandbox_tools


class _FakeManager:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.commands: list[str] = []

    async def exec_command(self, command: str, timeout: int) -> SimpleNamespace:
        del timeout
        self.commands.append(command)
        tokens = shlex.split(command)
        if "--dump-dom" in tokens:
            dom_path = self._host_path(tokens[tokens.index(">") + 1])
            stderr_path = self._host_path(tokens[tokens.index("2>") + 1])
            dom_path.write_text(
                """<html><head><title>Rendered title</title></head><body>
<h1>Primary heading</h1>
<a href="/details"><span>Read</span> more</a>
<img src="hero.png">
<form action="/send" method="post"><input><button>Send</button></form>
</body></html>""",
                encoding="utf-8",
            )
            stderr_path.write_text(
                "CONSOLE: Uncaught ReferenceError: missing is not defined\n",
                encoding="utf-8",
            )
        screenshot = next(
            (token for token in tokens if token.startswith("--screenshot=")), None
        )
        if screenshot:
            output = self._host_path(screenshot.split("=", 1)[1])
            output.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        response = SimpleNamespace(exit_code=0, output="")
        return SimpleNamespace(response=response)

    def _host_path(self, guest_path: str) -> Path:
        return self.workdir / guest_path.removeprefix("/workspace/")


@pytest.mark.asyncio
async def test_inspect_html_reports_rendered_structure(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<p>Initial</p>", encoding="utf-8")
    manager = _FakeManager(tmp_path)

    report = await inspect_html_file(manager, "/workspace/page.html")

    assert report["ok"] is True
    assert report["title"] == "Rendered title"
    assert report["headings"] == [{"level": "h1", "text": "Primary heading"}]
    assert report["links"] == [{"href": "/details", "text": "Read more"}]
    assert report["missing_image_alt"] == ["hero.png"]
    assert report["forms"] == [{"action": "/send", "method": "post", "inputs": 2}]
    assert "ReferenceError" in report["browser_errors"][0]
    assert "file:///workspace/page.html" in manager.commands[0]


@pytest.mark.asyncio
async def test_screenshot_html_writes_png_and_clamps_viewport(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<p>Hello</p>", encoding="utf-8")
    manager = _FakeManager(tmp_path)

    result = await screenshot_html_file(
        manager,
        "page.html",
        "shots/page.png",
        viewport_width=100,
        viewport_height=9999,
    )

    assert result["ok"] is True
    assert result["output_path"] == "/workspace/shots/page.png"
    assert result["viewport"] == {"width": 320, "height": 2160}
    assert (tmp_path / "shots" / "page.png").is_file()
    assert "--window-size=320,2160" in manager.commands[0]


@pytest.mark.asyncio
async def test_html_render_tools_reject_workspace_escape(tmp_path: Path) -> None:
    manager = _FakeManager(tmp_path)

    with pytest.raises(ValueError, match="within /workspace"):
        await inspect_html_file(manager, "../outside.html")
    with pytest.raises(ValueError, match="within /workspace"):
        await screenshot_html_file(manager, "../outside.html")


def test_all_html_tools_are_registered() -> None:
    names = {item.name for item in build_sandbox_tools()}
    assert {"bundle_html", "inspect_html", "screenshot_html"} <= names
