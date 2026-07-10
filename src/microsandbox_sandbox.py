"""Microsandbox-backed ``BaseSandbox`` for deepagents."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from sandbox_config import SANDBOX_ROOT, default_network, exec_timeout

if TYPE_CHECKING:
    from sandbox_manager import SandboxManager


class MicrosandboxSandbox(BaseSandbox):
    """Shared microsandbox backend: async-native exec, host-direct file I/O."""

    def __init__(self, *, manager: SandboxManager, stub: bool = False) -> None:
        self._manager = manager
        self._stub = stub
        self._id = "msb-deepagent" if not stub else "msb-stub"
        self._workdir = manager.workdir
        self.sandbox_root = SANDBOX_ROOT
        self.network = manager.network if not stub else default_network()
        self.default_timeout = exec_timeout()

    @property
    def id(self) -> str:
        return self._id

    def cleanup(self) -> None:
        """Shared VM is owned by SandboxManager — session cleanup is a no-op."""

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Sync bridge for CLI/tests. Do not call on the app event-loop thread."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None and running is self._manager.loop:
            raise RuntimeError(
                "MicrosandboxSandbox.execute() cannot run on the app event loop; "
                "use aexecute() instead"
            )
        fut = asyncio.run_coroutine_threadsafe(
            self.aexecute(command, timeout=timeout),
            self._manager.loop,
        )
        return fut.result()

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> ExecuteResponse:
        result = await self._manager.exec_command(command, timeout=timeout)
        return result.response

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse] = []
        for path, content in files:
            host_path = self._to_host_path(path)
            if host_path is None:
                results.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            try:
                host_path.parent.mkdir(parents=True, exist_ok=True)
                host_path.write_bytes(content)
                results.append(FileUploadResponse(path=path))
            except IsADirectoryError:
                results.append(FileUploadResponse(path=path, error="is_directory"))
            except PermissionError:
                results.append(FileUploadResponse(path=path, error="permission_denied"))
            except OSError as e:
                results.append(FileUploadResponse(path=path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        for path in paths:
            host_path = self._to_host_path(path)
            if host_path is None:
                results.append(FileDownloadResponse(path=path, error="invalid_path"))
                continue
            try:
                content = host_path.read_bytes()
                results.append(FileDownloadResponse(path=path, content=content))
            except FileNotFoundError:
                results.append(FileDownloadResponse(path=path, error="file_not_found"))
            except IsADirectoryError:
                results.append(FileDownloadResponse(path=path, error="is_directory"))
            except PermissionError:
                results.append(FileDownloadResponse(path=path, error="permission_denied"))
            except OSError as e:
                results.append(FileDownloadResponse(path=path, error=str(e)))
        return results

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return self.upload_files(files)

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self.download_files(paths)

    def _to_host_path(self, sandbox_path: str) -> Path | None:
        if not sandbox_path.startswith(self.sandbox_root):
            return None
        rel = sandbox_path[len(self.sandbox_root) :].lstrip("/")
        candidate = (self._workdir / rel).resolve()
        try:
            candidate.relative_to(self._workdir.resolve())
        except ValueError:
            return None
        return candidate
