"""Application-scoped Bubblewrap lifecycle and execution serialization."""

from __future__ import annotations

import asyncio
import contextvars
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from deepagents.backends.protocol import ExecuteResponse

from deep_agent.sandbox.backend import BubblewrapBackend, SandboxBackend
from deep_agent.sandbox.config import default_network, default_workdir, exec_timeout, sandbox_lock_wait

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


class SandboxManager:
    """Own one shared Bubblewrap workspace for this single-tenant deployment."""

    def __init__(self) -> None:
        self._backend: SandboxBackend | None = None
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
            workdir = default_workdir()
            workdir.mkdir(parents=True, exist_ok=True)
            backend = BubblewrapBackend(
                workdir=workdir,
                network=default_network(),
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
            "workdir": str(default_workdir()),
            "network": default_network(),
            "backend": "bubblewrap" if self._healthy else "unavailable",
            "busy": self._holder is not None,
            "holder_session_id": self._holder.session_id if self._holder else None,
            "holder_run_id": self._holder.run_id if self._holder else None,
            "holder_since": self._holder.since if self._holder else None,
            "default_exec_timeout": exec_timeout(),
        }

    async def exec_command(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        if self._backend is None:
            return ExecuteResponse(output="[Sandbox unavailable] " + (self._degraded_reason or ""), exit_code=None, truncated=False)
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=sandbox_lock_wait())
        except asyncio.TimeoutError:
            return ExecuteResponse(output="[Sandbox busy]", exit_code=None, truncated=False)
        self._holder = LockHolder(current_session_id.get(), current_run_id.get(), time.time())
        try:
            return await self._backend.exec(command, timeout=timeout)
        finally:
            self._holder = None
            self._lock.release()


_manager: SandboxManager | None = None


def get_manager() -> SandboxManager:
    global _manager
    if _manager is None:
        _manager = SandboxManager()
    return _manager
