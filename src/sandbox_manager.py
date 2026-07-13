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
    guest_network,
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

Default guest image is python:3.12-slim (pulled from Docker Hub on first use).
Optional custom image:
  docker build -f Dockerfile.sandbox -t deepagent-workspace:dev .
  docker save deepagent-workspace:dev | msb load --tag deepagent-workspace:dev
  set DEEPAGENT_SANDBOX_IMAGE=deepagent-workspace:dev
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
        self._healthy = False
        self._degraded_reason: str | None = None
        self._fix_it: str | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def degraded(self) -> bool:
        return self._started and not self._healthy

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
    def backend(self) -> Any | None:
        """Shared microsandbox backend, or ``None`` when degraded (no VM)."""
        return self._backend

    @property
    def holder(self) -> LockHolder | None:
        return self._holder

    def bind_cancel_run(self, cancel_run: CancelRunFn) -> None:
        self._cancel_run = cancel_run

    def _enter_degraded(self, reason: str) -> None:
        self._healthy = False
        self._backend = None
        self._sb = None
        self._degraded_reason = reason
        self._fix_it = _VIRT_HELP
        self._started = True

    async def startup(self) -> None:
        if use_stub_backend():
            self._loop = asyncio.get_running_loop()
            self._workdir = default_workdir()
            self._network = default_network()
            self._workdir.mkdir(parents=True, exist_ok=True)
            from microsandbox_sandbox import MicrosandboxSandbox

            self._backend = MicrosandboxSandbox(manager=self, stub=True)
            self._healthy = True
            self._degraded_reason = None
            self._fix_it = None
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
            self._enter_degraded(f"microsandbox install/check failed: {exc}")
            return

        try:
            await self._create_sandbox()
        except Exception as exc:
            self._enter_degraded(f"microsandbox could not create a microVM: {exc}")
            return

        from microsandbox_sandbox import MicrosandboxSandbox

        self._backend = MicrosandboxSandbox(manager=self)
        self._healthy = True
        self._degraded_reason = None
        self._fix_it = None
        self._started = True

    async def retry_sandbox(self) -> dict[str, Any]:
        """Attempt to create the microVM after a degraded start."""
        if use_stub_backend():
            return self.status_dict()
        if self._healthy and self._backend is not None:
            return self.status_dict()
        try:
            from microsandbox import is_installed, install

            if not is_installed():
                await install()
            await self._create_sandbox()
            from microsandbox_sandbox import MicrosandboxSandbox

            self._backend = MicrosandboxSandbox(manager=self)
            self._healthy = True
            self._degraded_reason = None
            self._fix_it = None
            self._started = True
        except Exception as exc:
            self._enter_degraded(f"microsandbox retry failed: {exc}")
        return self.status_dict()

    async def recreate_from_env(self) -> dict[str, Any]:
        """Re-read workdir/network from env and replace the shared microVM.

        Raises ``RuntimeError`` if an exec currently holds the sandbox lock.
        """
        self._workdir = default_workdir()
        self._network = default_network()
        self._workdir.mkdir(parents=True, exist_ok=True)
        (self._workdir / LOG_DIR_REL).mkdir(parents=True, exist_ok=True)

        if use_stub_backend():
            from microsandbox_sandbox import MicrosandboxSandbox

            self._backend = MicrosandboxSandbox(manager=self, stub=True)
            self._healthy = True
            self._degraded_reason = None
            self._fix_it = None
            self._started = True
            return self.status_dict()

        if not self._started:
            return self.status_dict()

        if self._lock.locked():
            raise RuntimeError(
                "Cannot recreate sandbox while a command is running. "
                "Wait for the current exec to finish, then Save again."
            )

        async with self._create_lock:
            old = self._sb
            self._sb = None
            if old is not None:
                try:
                    await old.stop()
                except Exception:
                    pass
            try:
                from microsandbox import Sandbox

                await Sandbox.remove(SANDBOX_NAME)
            except Exception:
                pass

            try:
                from microsandbox import is_installed, install

                if not is_installed():
                    await install()
                await self._create_sandbox()
                from microsandbox_sandbox import MicrosandboxSandbox

                self._backend = MicrosandboxSandbox(manager=self)
                self._healthy = True
                self._degraded_reason = None
                self._fix_it = None
            except Exception as exc:
                self._enter_degraded(f"sandbox recreate after settings failed: {exc}")
        return self.status_dict()

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
        from microsandbox import Sandbox, Volume

        kwargs: dict[str, Any] = {
            "image": sandbox_image(),
            "memory": sandbox_memory_mib(),
            "cpus": sandbox_cpus(),
            "workdir": SANDBOX_ROOT,
            "replace": True,
            "volumes": {
                SANDBOX_ROOT: Volume.bind(str(self._workdir)),
            },
            "network": guest_network(),
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
            if not self._healthy:
                raise RuntimeError(
                    self._degraded_reason
                    or "Sandbox is unavailable (degraded mode). See fix_it guidance."
                )
            if self._sb is None:
                await self._create_sandbox()
                return self._sb
            try:
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
            "healthy": self._healthy,
            "degraded": self.degraded,
            "degraded_reason": self._degraded_reason,
            "fix_it": self._fix_it,
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
            "backend": "stub" if use_stub_backend() else (
                "microsandbox" if self._healthy else "unavailable"
            ),
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
            # Truncate/create so streaming flushes have a stable target.
            host_log.write_bytes(b"")
            if use_stub_backend():
                output, exit_code, timed_out = await self._stub_exec(command, timeout)
                host_log.write_text(output, encoding="utf-8", errors="replace")
            else:
                output, exit_code, timed_out = await self._vm_exec(
                    command, timeout, host_log=host_log
                )
                # Rewrite decoded text so the on-disk log matches the returned string.
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
                    # Size trim only — timeout is signaled via the suffix above.
                    # Marking timeout as truncated makes deepagents claim
                    # "truncated due to size limits", which is misleading.
                    truncated=was_trimmed,
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
        self,
        command: str,
        timeout: int | None,
        *,
        host_log: Path,
    ) -> tuple[str, int | None, bool]:
        """Stream guest output; keep partial logs if the app-owned deadline fires.

        Uses ``shell_stream`` with no SDK timeout so bytes already received are
        retained when we kill the process. Chunks are flushed to ``host_log`` as
        they arrive so a crash mid-command still leaves a useful file.
        """
        sb = await self.ensure_sandbox()
        effective = exec_timeout() if timeout is None else timeout
        no_timeout = effective == 0
        handle = await sb.shell_stream(command, cwd=SANDBOX_ROOT)
        chunks: list[bytes] = []
        exit_code: int | None = None
        timed_out = False
        loop = asyncio.get_running_loop()
        deadline = None if no_timeout else (loop.time() + float(effective))

        def _on_bytes(data: bytes) -> None:
            if not data:
                return
            chunks.append(data)
            try:
                with host_log.open("ab") as fh:
                    fh.write(data)
            except OSError:
                pass

        def _handle_event(event: Any) -> bool:
            """Apply one stream event. Return True when the process has exited."""
            nonlocal exit_code
            kind = _event_kind(event)
            if kind == "stdout" or kind == "stderr":
                _on_bytes(getattr(event, "data", None) or b"")
                return False
            if kind == "exited":
                code = getattr(event, "code", None)
                exit_code = int(code) if code is not None else None
                return True
            return False

        async def _recv_until(
            *, stop_at: float | None, stop_on_exit: bool
        ) -> bool:
            """Receive events until exit, stream end, or ``stop_at`` (loop time).

            Returns True if the process exited cleanly (ExitedEvent or EOF after
            start). Returns False if the wall-clock deadline was hit first.
            """
            while True:
                if stop_at is not None:
                    remaining = stop_at - loop.time()
                    if remaining <= 0:
                        return False
                    try:
                        event = await asyncio.wait_for(handle.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        return False
                else:
                    event = await handle.recv()

                if event is None:
                    return True
                if _handle_event(event) and stop_on_exit:
                    return True

        try:
            finished = await _recv_until(stop_at=deadline, stop_on_exit=True)
            if not finished:
                timed_out = True
                try:
                    await handle.kill()
                except Exception:
                    pass
                # Brief grace drain for bytes already in flight after kill.
                await _recv_until(stop_at=loop.time() + 0.5, stop_on_exit=True)
        except Exception:
            try:
                await handle.kill()
            except Exception:
                pass
            raise

        text = b"".join(chunks).decode("utf-8", errors="replace")
        if timed_out and not text:
            text = f"exec timed out after {effective}s\n"
        return text, exit_code, timed_out

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


def _event_kind(event: Any) -> str:
    """Normalize microsandbox stream events to stdout|stderr|exited|started|other."""
    et = getattr(event, "event_type", None)
    if isinstance(et, str) and et:
        return et.lower()
    name = type(event).__name__.lower()
    if name.startswith("stdout"):
        return "stdout"
    if name.startswith("stderr"):
        return "stderr"
    if name.startswith("exited"):
        return "exited"
    if name.startswith("started"):
        return "started"
    return name or "other"


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
