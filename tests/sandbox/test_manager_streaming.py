"""Unit tests for streaming exec + partial logs on app-owned timeout."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from deep_agent.sandbox.manager import SandboxManager, reset_manager_for_tests


@dataclass
class _Evt:
    event_type: str
    data: bytes | None = None
    code: int | None = None
    pid: int | None = None


class _FakeHandle:
    def __init__(self, events: list[Any], *, hang_after: int | None = None) -> None:
        self._events = list(events)
        self._idx = 0
        self._hang_after = hang_after
        self.killed = False

    async def recv(self) -> Any | None:
        if self._hang_after is not None and self._idx >= self._hang_after:
            # Simulate a stuck process: never emit more events until killed.
            while not self.killed:
                await asyncio.sleep(0.05)
            return None
        if self._idx >= len(self._events):
            return None
        event = self._events[self._idx]
        self._idx += 1
        return event

    async def kill(self) -> None:
        self.killed = True


class _FakeSandbox:
    def __init__(self, handle: _FakeHandle) -> None:
        self._handle = handle
        self.last_script: str | None = None
        self.last_kwargs: dict[str, Any] = {}

    async def shell_stream(self, script: str, **kwargs: Any) -> _FakeHandle:
        self.last_script = script
        self.last_kwargs = kwargs
        return self._handle


@pytest.fixture(autouse=True)
def _reset_manager() -> None:
    reset_manager_for_tests()
    yield
    reset_manager_for_tests()


@pytest.mark.asyncio
async def test_vm_exec_keeps_partial_output_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPAGENT_EXEC_TIMEOUT", "1")
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "microsandbox")

    handle = _FakeHandle(
        [
            _Evt("started", pid=42),
            _Evt("stdout", data=b"hello "),
            _Evt("stderr", data=b"retrying...\n"),
        ],
        hang_after=3,
    )
    fake_sb = _FakeSandbox(handle)
    mgr = SandboxManager()
    mgr._workdir = tmp_path
    mgr._started = True
    mgr._loop = asyncio.get_running_loop()
    mgr._sb = fake_sb

    async def _ensure() -> Any:
        return fake_sb

    mgr.ensure_sandbox = _ensure  # type: ignore[method-assign]

    log_path = tmp_path / "partial.log"
    log_path.write_bytes(b"")
    text, code, timed_out = await mgr._vm_exec("sleep 999", 1, host_log=log_path)

    assert timed_out is True
    assert code is None
    assert "hello " in text
    assert "retrying..." in text
    assert handle.killed is True
    assert "hello " in log_path.read_text(encoding="utf-8")
    # SDK timeout must not be passed — app owns the deadline.
    assert "timeout" not in fake_sb.last_kwargs


@pytest.mark.asyncio
async def test_vm_exec_success_collects_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPAGENT_EXEC_TIMEOUT", "30")

    handle = _FakeHandle(
        [
            _Evt("stdout", data=b"ok\n"),
            _Evt("exited", code=0),
        ]
    )
    fake_sb = _FakeSandbox(handle)
    mgr = SandboxManager()
    mgr._workdir = tmp_path
    mgr._started = True
    mgr._loop = asyncio.get_running_loop()
    mgr._sb = fake_sb

    async def _ensure() -> Any:
        return fake_sb

    mgr.ensure_sandbox = _ensure  # type: ignore[method-assign]

    log_path = tmp_path / "ok.log"
    log_path.write_bytes(b"")
    text, code, timed_out = await mgr._vm_exec("echo ok", 30, host_log=log_path)

    assert timed_out is False
    assert code == 0
    assert text == "ok\n"


@pytest.mark.asyncio
async def test_exec_command_timeout_does_not_set_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPAGENT_EXEC_TIMEOUT", "1")
    monkeypatch.setenv("DEEPAGENT_SANDBOX_BACKEND", "microsandbox")
    monkeypatch.setenv("DEEPAGENT_WORKDIR", str(tmp_path))

    handle = _FakeHandle(
        [_Evt("stdout", data=b"partial-line\n")],
        hang_after=1,
    )
    fake_sb = _FakeSandbox(handle)
    mgr = SandboxManager()
    mgr._workdir = tmp_path
    mgr._started = True
    mgr._network = False
    mgr._loop = asyncio.get_running_loop()
    mgr._sb = fake_sb

    async def _ensure() -> Any:
        return fake_sb

    mgr.ensure_sandbox = _ensure  # type: ignore[method-assign]

    result = await mgr.exec_command("sleep 999", timeout=1)
    assert result.response.truncated is False
    assert "partial-line" in result.response.output
    assert "Command timed out after 1s" in result.response.output
    assert result.log_path is not None
    # guest path → host file under workdir
    host_log = tmp_path / ".deepagent" / "logs" / Path(result.log_path).name
    assert "partial-line" in host_log.read_text(encoding="utf-8")
