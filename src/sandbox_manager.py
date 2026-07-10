"""App-scoped microsandbox lifecycle, exec lock, and command logging."""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents.backends.protocol import ExecuteResponse

from sandbox_config import (
    LOG_DIR_REL,
    LOG_PREVIEW_LINES,
    LOG_RETENTION_BYTES,
    LOG_RETENTION_DAYS,
    SANDBOX_NAME,
    SANDBOX_ROOT,
    default_network,
    default_workdir,
    exec_timeout,
    sandbox_cpus,
    sandbox_idle_timeout,
    sandbox_image,
    sandbox_lock_wait,
    sandbox_memory_mib,
    use_stub_backend,
)

# Set by RunManager around each chat turn so lock ownership is attributable.
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sandbox_session_id", default=None
)
current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sandbox_run_id", default=None
)

CancelRunFn = Callable[[str], Awaitable[bool]]


@dataclass
class LockHolder:
    session_id: str | None
    run_id: str | None
    since: float


@dataclass
class ExecResult:
    response: ExecuteResponse
    log_path: str | None = None
    busy: bool = False


_VIRT_HELP = """\
microsandbox could not start a microVM.

Requirements:
  - Linux: KVM enabled (/dev/kvm), or
  - macOS: Apple Silicon with Hypervisor.framework, or
  - Windows: Windows Hypervisor Platform (WHP) enabled

Install/check the runtime:
  uv run python -c "import asyncio; from microsandbox import install, is_installed; \
asyncio.run(install()) if not is_installed() else print('ok')"
  msb doctor

Then rebuild the guest image if needed:
  docker build -f Dockerfile.sandbox -t deepagent-workspace:dev .
"""


class SandboxManager:
    """Owns the single shared microsandbox for the app process."""

    def __init__(self) -> None:
        self._sb: Any | None = None
        self._lock = asyncio.Lock()
        self._holder: LockHolder | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._workdir: Path = default_workdir()
        self._network: bool = default_network()
        self._backend: Any | None = None
        self._cancel_run: CancelRunFn | None = None
        self._started = False
        self._create_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._started

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("SandboxManager is not started")
        return self._loop

    @property
    def workdir(self) -> Path:
        return self._workdir

    @property
    def network(self) -> bool:
        return self._network

    @property
    def backend(self) -> Any:
        if self._backend is None:
            raise RuntimeError("SandboxManager backend is not ready")
        return self._backend

    @property
    def holder(self) -> LockHolder | None:
        return self._holder

    def bind_cancel_run(self, cancel_run: CancelRunFn) -> None:
        self._cancel_run = cancel_run

    async def startup(self) -> None:
        if use_stub_backend():
            self._loop = asyncio.get_running_loop()
            self._workdir.mkdir(parents=True, exist_ok=True)
            from microsandbox_sandbox import MicrosandboxSandbox

            self._backend = MicrosandboxSandbox(manager=self, stub=True)
            self._started = True
            return

        self._loop = asyncio.get_running_loop()
        self._workdir = default_workdir()
        self._network = default_network()
        self._workdir.mkdir(parents=True, exist_ok=True)
        (self._workdir / LOG_DIR_REL).mkdir(parents=True, exist_ok=True)

        try:
            from microsandbox import is_installed, install

            if not is_installed():
                await install()
        except Exception as exc:
            raise RuntimeError(_VIRT_HELP) from exc

        try:
            await self._create_sandbox()
        except Exception as exc:
            raise RuntimeError(f"{_VIRT_HELP}\nUnderlying error: {exc}") from exc

        from microsandbox_sandbox import MicrosandboxSandbox

        self._backend = MicrosandboxSandbox(manager=self)
        self._started = True

    async def shutdown(self) -> None:
        if not self._started:
            return
        sb = self._sb
        self._sb = None
        self._started = False
        if sb is None or use_stub_backend():
            return
        try:
            await sb.stop()
        except Exception:
            pass
        try:
            from microsandbox import Sandbox

            await Sandbox.remove(SANDBOX_NAME)
        except Exception:
            pass

    async def _create_sandbox(self) -> None:
        from microsandbox import Network, Sandbox, Volume

        kwargs: dict[str, Any] = {
            "image": sandbox_image(),
            "memory": sandbox_memory_mib(),
            "cpus": sandbox_cpus(),
            "workdir": SANDBOX_ROOT,
            "replace": True,
            "volumes": {
                SANDBOX_ROOT: Volume.bind(str(self._workdir)),
            },
            "network": Network.public_only() if self._network else Network.none(),
            "env": {
                "HOME": SANDBOX_ROOT,
                "TMPDIR": "/tmp",
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        }
        idle = sandbox_idle_timeout()
        if idle > 0:
            kwargs["idle_timeout"] = idle

        self._sb = await Sandbox.create(SANDBOX_NAME, **kwargs)

    async def ensure_sandbox(self) -> Any:
        async with self._create_lock:
            if use_stub_backend():
                return None
            if self._sb is None:
                await self._create_sandbox()
                return self._sb
            try:
                from microsandbox import SandboxNotRunningError

                # Cheap liveness probe; recreate after idle auto-stop.
                await self._sb.shell("true", timeout=10)
            except Exception as exc:
                name = type(exc).__name__
                if name in {"SandboxNotRunningError", "SandboxNotFoundError"} or (
                    "not running" in str(exc).lower()
                ):
                    await self._create_sandbox()
                else:
                    # Unknown failure — try replace once.
                    try:
                        await self._create_sandbox()
                    except Exception:
                        raise exc from None
            return self._sb

    def status_dict(self) -> dict[str, Any]:
        holder = self._holder
        return {
            "started": self._started,
            "sandbox_name": SANDBOX_NAME,
            "workdir": str(self._workdir),
            "network": self._network,
            "image": sandbox_image(),
            "busy": holder is not None,
            "holder_session_id": holder.session_id if holder else None,
            "holder_run_id": holder.run_id if holder else None,
            "holder_since": holder.since if holder else None,
            "default_lock_wait": sandbox_lock_wait(),
            "default_exec_timeout": exec_timeout(),
        }

    async def wait_for_lock(self, wait_seconds: int | None = None) -> dict[str, Any]:
        wait = sandbox_lock_wait() if wait_seconds is None else max(0, int(wait_seconds))
        if not self._lock.locked():
            return {"busy": False, **self.status_dict()}
        acquire_timeout = 0.01 if wait == 0 else float(wait)
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=acquire_timeout)
        except asyncio.TimeoutError:
            return {
                "busy": True,
                "waited_seconds": wait,
                "message": (
                    f"Sandbox still busy after {wait}s. "
                    "Ask the user before calling cancel_sandbox_holder."
                ),
                **self.status_dict(),
            }
        # Acquired only to probe; release immediately.
        self._lock.release()
        return {"busy": False, "waited_seconds": wait, **self.status_dict()}

    async def cancel_holder(self) -> dict[str, Any]:
        holder = self._holder
        if holder is None or not holder.run_id:
            return {"cancelled": False, "reason": "sandbox is not held by any run"}
        if self._cancel_run is None:
            return {"cancelled": False, "reason": "cancel callback not bound"}
        ok = await self._cancel_run(holder.run_id)
        return {
            "cancelled": bool(ok),
            "holder_session_id": holder.session_id,
            "holder_run_id": holder.run_id,
        }

    async def exec_command(
        self,
        command: str,
        *,
        timeout: int | None = None,
        lock_wait: int | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> ExecResult:
        """Run a shell command under the shared lock; log full output to workspace."""
        sid = session_id if session_id is not None else current_session_id.get()
        rid = run_id if run_id is not None else current_run_id.get()
        wait = sandbox_lock_wait() if lock_wait is None else max(0, int(lock_wait))
        acquire_timeout = 0.01 if wait == 0 else float(wait)

        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=acquire_timeout)
        except asyncio.TimeoutError:
            holder = self._holder
            msg = (
                f"[Sandbox busy] Could not acquire exec lock within {wait}s. "
                f"Held by session={holder.session_id if holder else '?'} "
                f"run={holder.run_id if holder else '?'}. "
                "Wait with sandbox_wait (configure wait_seconds), or ask the user "
                "before cancel_sandbox_holder."
            )
            return ExecResult(
                response=ExecuteResponse(output=msg, exit_code=None, truncated=False),
                busy=True,
            )

        self._holder = LockHolder(session_id=sid, run_id=rid, since=time.time())
        log_id = uuid.uuid4().hex[:16]
        host_log = self._workdir / LOG_DIR_REL / f"{log_id}.log"
        guest_log = f"{SANDBOX_ROOT}/{LOG_DIR_REL}/{log_id}.log"
        try:
            host_log.parent.mkdir(parents=True, exist_ok=True)
            if use_stub_backend():
                output, exit_code, timed_out = await self._stub_exec(command, timeout)
            else:
                output, exit_code, timed_out = await self._vm_exec(command, timeout)

            host_log.write_text(output, encoding="utf-8", errors="replace")
            self._prune_logs()

            preview, was_trimmed = _last_lines(output, LOG_PREVIEW_LINES)
            suffix_parts = [f"\n[Full log: {guest_log}]"]
            if was_trimmed:
                suffix_parts.insert(0, f"\n[Output truncated to last {LOG_PREVIEW_LINES} lines]")
            if timed_out:
                effective = exec_timeout() if timeout is None else timeout
                suffix_parts.append(f"\n[Command timed out after {effective}s]")
            return ExecResult(
                response=ExecuteResponse(
                    output=preview + "".join(suffix_parts),
                    exit_code=exit_code,
                    truncated=was_trimmed or timed_out,
                ),
                log_path=guest_log,
            )
        finally:
            self._holder = None
            self._lock.release()

    async def _stub_exec(
        self, command: str, timeout: int | None
    ) -> tuple[str, int | None, bool]:
        del command, timeout
        return ("[stub sandbox] no command executed\n", 0, False)

    async def _vm_exec(
        self, command: str, timeout: int | None
    ) -> tuple[str, int | None, bool]:
        sb = await self.ensure_sandbox()
        effective = exec_timeout() if timeout is None else timeout
        no_timeout = effective == 0
        try:
            from microsandbox import ExecTimeoutError

            kwargs: dict[str, Any] = {"cwd": SANDBOX_ROOT}
            if not no_timeout:
                kwargs["timeout"] = float(effective)
            output = await sb.shell(command, **kwargs)
            text = _combine_output(output)
            code = getattr(output, "exit_code", None)
            return text, code, False
        except Exception as exc:
            from microsandbox import ExecTimeoutError

            if isinstance(exc, ExecTimeoutError) or type(exc).__name__ == "ExecTimeoutError":
                partial = str(exc)
                return partial, None, True
            raise

    def _prune_logs(self) -> None:
        log_dir = self._workdir / LOG_DIR_REL
        if not log_dir.is_dir():
            return
        now = time.time()
        max_age = LOG_RETENTION_DAYS * 86400
        files = sorted(
            (p for p in log_dir.glob("*.log") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        for path in files:
            try:
                if now - path.stat().st_mtime > max_age:
                    path.unlink(missing_ok=True)
            except OSError:
                continue
        files = sorted(
            (p for p in log_dir.glob("*.log") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        total = sum(p.stat().st_size for p in files)
        while total > LOG_RETENTION_BYTES and files:
            oldest = files.pop(0)
            try:
                size = oldest.stat().st_size
                oldest.unlink(missing_ok=True)
                total -= size
            except OSError:
                break


def _combine_output(output: Any) -> str:
    stdout = getattr(output, "stdout_text", None) or ""
    stderr = getattr(output, "stderr_text", None) or ""
    if stdout and stderr:
        return stdout + ("\n" if not stdout.endswith("\n") else "") + stderr
    return stdout or stderr or ""


def _last_lines(text: str, n: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= n:
        return text, False
    return "\n".join(lines[-n:]), True


_manager: SandboxManager | None = None


def get_manager() -> SandboxManager:
    global _manager
    if _manager is None:
        _manager = SandboxManager()
    return _manager


def reset_manager_for_tests() -> None:
    global _manager
    _manager = None
