"""Optional real microsandbox integration tests.

Skipped unless DEEPAGENT_MSB_INTEGRATION=1 and virtualization works.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DEEPAGENT_MSB_INTEGRATION") != "1",
    reason="Set DEEPAGENT_MSB_INTEGRATION=1 to run real microsandbox tests",
)


@pytest.mark.asyncio
async def test_manager_exec_and_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "microsandbox")
    monkeypatch.setenv("DEEPAGENT_SANDBOX_IDLE_TIMEOUT", "60")

    from deep_agent.sandbox.manager import SandboxManager, reset_manager_for_tests

    reset_manager_for_tests()
    mgr = SandboxManager()
    try:
        await mgr.startup()
        result = await mgr.exec_command("echo hello-msb && uname -a", timeout=60)
        assert result.busy is False
        assert "hello-msb" in result.response.output
        assert result.log_path is not None
        assert result.log_path.startswith("/workspace/.deepagent/logs/")
        host_log = mgr.workdir / ".deepagent" / "logs" / Path(result.log_path).name
        assert host_log.is_file()
        assert "hello-msb" in host_log.read_text(encoding="utf-8")
    finally:
        await mgr.shutdown()
        reset_manager_for_tests()


@pytest.mark.asyncio
async def test_chromium_inspects_and_screenshots_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "microsandbox")
    monkeypatch.setenv("DEEPAGENT_SANDBOX_IDLE_TIMEOUT", "60")

    from deep_agent.sandbox.html_tools import inspect_html_file, screenshot_html_file
    from deep_agent.sandbox.manager import SandboxManager, reset_manager_for_tests

    reset_manager_for_tests()
    mgr = SandboxManager()
    try:
        await mgr.startup()
        page = mgr.workdir / "fixture.html"
        page.write_text(
            "<!doctype html><title>Fixture</title><h1>Rendered</h1>",
            encoding="utf-8",
        )

        inspection = await inspect_html_file(mgr, "fixture.html")
        screenshot = await screenshot_html_file(
            mgr, "fixture.html", "fixture.png"
        )

        assert inspection["ok"] is True
        assert inspection["title"] == "Fixture"
        assert inspection["headings"] == [{"level": "h1", "text": "Rendered"}]
        assert screenshot["ok"] is True
        assert (mgr.workdir / "fixture.png").read_bytes().startswith(
            b"\x89PNG\r\n\x1a\n"
        )
    finally:
        await mgr.shutdown()
        reset_manager_for_tests()
