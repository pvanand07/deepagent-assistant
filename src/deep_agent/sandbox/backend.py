"""Sandbox backend seam used by the web application.

The web tier deliberately depends on this small lifecycle protocol rather than
on Bubblewrap directly.  A future shared/multi-tenant backend can implement the
same contract without changing the chat or API layers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from deepagents.backends.protocol import ExecuteResponse

from deep_agent.sandbox.bubblewrap import BubblewrapSandbox


class SandboxBackend(Protocol):
    """Lifecycle and command interface required by ``SandboxManager``."""

    id: str
    network: bool
    _workdir: Path

    async def start(self) -> None: ...
    async def exec(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...
    async def stop(self) -> None: ...
    def status(self) -> dict[str, object]: ...


class BubblewrapBackend(BubblewrapSandbox):
    """App-managed Bubblewrap backend with an async lifecycle adapter."""

    async def start(self) -> None:
        return None

    async def exec(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)

    async def stop(self) -> None:
        self.cleanup()

    def status(self) -> dict[str, object]:
        return {
            "id": self.id,
            "workdir": str(self._workdir),
            "network": self.network,
            "backend": "bubblewrap",
        }
