"""Application-scoped Bubblewrap lifecycle and execution serialization."""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from deepagents.backends.protocol import ExecuteResponse

from deep_agent.sandbox.backend import BubblewrapBackend, SandboxBackend
from deep_agent.sandbox.config import (
    default_network,
    default_workdir,
    exec_timeout,
    sandbox_lock_wait,
)

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


class SandboxManager:
    """Own one shared Bubblewrap workspace for this single-tenant deployment."""

    def __init__(self) -> None:
        self._backend: SandboxBackend | None = None
        self._workdir: Path = default_workdir()
        self._network: bool = default_network()
        self._lock = asyncio.Lock()
        self._holder: LockHolder | None = None
        self._cancel_run: CancelRunFn | None = None
        self._started = False
        self._starting = False
        self._healthy = False
        self._degraded_reason: str | None = None

    @property
    def backend(self) -> SandboxBackend | None:
        return self._backend

    @property
    def workdir(self) -> Path:
        return self._workdir

    @property
    def network(self) -> bool:
        return self._network

    @property
    def holder(self) -> LockHolder | None:
        return self._holder

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def starting(self) -> bool:
        return self._starting

    @property
    def degraded(self) -> bool:
        return self._started and not self._healthy

    def bind_cancel_run(self, cancel_run: CancelRunFn) -> None:
        self._cancel_run = cancel_run

    def begin_startup(self) -> None:
        self._starting = True

    async def startup(self) -> None:
        self._starting = True
        try:
            self._workdir = default_workdir()
            self._network = default_network()
            self._workdir.mkdir(parents=True, exist_ok=True)
            backend = BubblewrapBackend(
                workdir=self._workdir,
                network=self._network,
                timeout=exec_timeout(),
            )
            await backend.start()
            self._backend = backend
            self._healthy = True
            self._degraded_reason = None
        except Exception as exc:
            self._backend = None
            self._healthy = False
            self._degraded_reason = str(exc)
        finally:
            self._started = True
            self._starting = False

    async def retry_sandbox(self) -> dict[str, object]:
        if not self._healthy:
            await self.startup()
        return self.status_dict()

    async def recreate_from_env(self) -> dict[str, object]:
        if self._lock.locked():
            raise RuntimeError("Cannot recreate Bubblewrap while a command is running.")
        await self.shutdown()
        await self.startup()
        return self.status_dict()

    async def shutdown(self) -> None:
        backend, self._backend = self._backend, None
        if backend is not None:
            await backend.stop()
        self._healthy = False
        self._started = False

    def status_dict(self) -> dict[str, object]:
        return {
            "started": self._started,
            "starting": self._starting,
            "healthy": self._healthy,
            "degraded": self.degraded,
            "degraded_reason": self._degraded_reason,
            "workdir": str(self._workdir),
            "network": self._network,
            "backend": "bubblewrap" if self._healthy else "unavailable",
            "busy": self._holder is not None,
            "holder_session_id": self._holder.session_id if self._holder else None,
            "holder_run_id": self._holder.run_id if self._holder else None,
            "holder_since": self._holder.since if self._holder else None,
            "default_exec_timeout": exec_timeout(),
            "default_lock_wait": sandbox_lock_wait(),
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
        sid = session_id if session_id is not None else current_session_id.get()
        rid = run_id if run_id is not None else current_run_id.get()
        wait = sandbox_lock_wait() if lock_wait is None else max(0, int(lock_wait))
        acquire_timeout = 0.01 if wait == 0 else float(wait)

        if self._backend is None:
            return ExecResult(
                response=ExecuteResponse(
                    output="[Sandbox unavailable] " + (self._degraded_reason or ""),
                    exit_code=None,
                    truncated=False,
                )
            )

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
        try:
            response = await self._backend.exec(command, timeout=timeout)
            return ExecResult(response=response)
        finally:
            self._holder = None
            self._lock.release()


_manager: SandboxManager | None = None


def get_manager() -> SandboxManager:
    global _manager
    if _manager is None:
        _manager = SandboxManager()
    return _manager


def reset_manager_for_tests() -> None:
    """Drop the process-wide manager singleton (tests only)."""
    global _manager
    _manager = None
