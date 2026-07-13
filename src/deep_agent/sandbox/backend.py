"""Microsandbox-backed ``BaseSandbox`` for deepagents."""

from __future__ import annotations

import asyncio
import base64
import codecs
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileData,
    FileDownloadResponse,
    FileUploadResponse,
    ReadResult,
)
from deepagents.backends.sandbox import (
    MAX_BINARY_BYTES,
    MAX_OUTPUT_BYTES,
    TRUNCATION_MSG,
    BaseSandbox,
)
from deepagents.backends.utils import _get_file_type

from deep_agent.sandbox.config import SANDBOX_ROOT, default_network, exec_timeout
from deep_agent.sandbox.paths import resolve_under_workdir

if TYPE_CHECKING:
    from deep_agent.sandbox.manager import SandboxManager


class MicrosandboxSandbox(BaseSandbox):
    """Shared microsandbox backend: async-native exec, host-direct file I/O.

    ``read_file`` / ``write_file`` content transfer use the host workspace path.
    Guest ``execute`` still runs in the microVM (shell tools). This avoids
    Windows virtiofs/9p ``Permission denied`` on guest-side open/read of the
    bind-mounted workspace — a known sharp edge with microsandbox on WHP.
    """

    def __init__(self, *, manager: SandboxManager, stub: bool = False) -> None:
        self._manager = manager
        self._stub = stub
        self._id = "msb-deepagent" if not stub else "msb-stub"
        self.sandbox_root = SANDBOX_ROOT

    @property
    def id(self) -> str:
        return self._id

    @property
    def _workdir(self) -> Path:
        """Always follow the manager so settings recreate stays consistent."""
        return self._manager.workdir

    @property
    def network(self) -> bool:
        return self._manager.network if not self._stub else default_network()

    @property
    def default_timeout(self) -> int:
        return exec_timeout()

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

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        """Host-direct read (avoids guest bind-mount Permission denied on Windows)."""
        return self._read_host(file_path, offset=int(offset), limit=int(limit))

    async def aread(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> ReadResult:
        return await asyncio.to_thread(
            self._read_host, file_path, int(offset), int(limit)
        )

    def _read_host(self, file_path: str, offset: int, limit: int) -> ReadResult:
        host_path = self._to_host_path(file_path)
        if host_path is None:
            return ReadResult(error=f"File '{file_path}': invalid_path")

        try:
            st = host_path.stat()
        except FileNotFoundError:
            return ReadResult(error=f"File '{file_path}': file_not_found")
        except PermissionError:
            return ReadResult(error=f"File '{file_path}': permission_denied")
        except OSError as e:
            return ReadResult(error=f"File '{file_path}': {e}")

        if not host_path.is_file():
            return ReadResult(error=f"File '{file_path}': not_a_file")

        if st.st_size == 0:
            return ReadResult(
                file_data=FileData(
                    content="System reminder: File exists but has empty contents",
                    encoding="utf-8",
                )
            )

        file_type = _get_file_type(file_path)
        try:
            if file_type != "text":
                return self._read_binary(file_path, host_path, st.st_size)

            with host_path.open("rb") as f:
                raw_prefix = f.read(8192)
            is_binary = False
            try:
                codecs.getincrementaldecoder("utf-8")().decode(raw_prefix, final=False)
            except UnicodeDecodeError:
                is_binary = True
            if is_binary:
                return self._read_binary(file_path, host_path, st.st_size)

            return self._read_text_page(host_path, offset, limit)
        except PermissionError:
            return ReadResult(error=f"File '{file_path}': permission_denied")
        except OSError as e:
            return ReadResult(error=f"File '{file_path}': {e}")

    def _read_binary(
        self, file_path: str, host_path: Path, size: int
    ) -> ReadResult:
        if size > MAX_BINARY_BYTES:
            return ReadResult(
                error=(
                    f"File '{file_path}': Binary file exceeds maximum preview "
                    f"size of {MAX_BINARY_BYTES} bytes"
                )
            )
        raw = host_path.read_bytes()
        return ReadResult(
            file_data=FileData(
                content=base64.b64encode(raw).decode("ascii"),
                encoding="base64",
            )
        )

    def _read_text_page(self, host_path: Path, offset: int, limit: int) -> ReadResult:
        """Paginated text read matching BaseSandbox's guest template output."""
        line_count = 0
        returned_lines = 0
        truncated = False
        parts: list[str] = []
        current_bytes = 0
        msg_bytes = len(TRUNCATION_MSG.encode("utf-8"))
        effective_limit = MAX_OUTPUT_BYTES - msg_bytes

        with host_path.open("r", encoding="utf-8", newline=None) as f:
            for raw_line in f:
                line_count += 1
                if line_count <= offset:
                    continue
                if returned_lines >= limit:
                    break

                line = raw_line.rstrip("\n").rstrip("\r")
                piece = line if returned_lines == 0 else "\n" + line
                piece_bytes = len(piece.encode("utf-8"))
                if current_bytes + piece_bytes > effective_limit:
                    truncated = True
                    remaining_bytes = effective_limit - current_bytes
                    if remaining_bytes > 0:
                        prefix = piece.encode("utf-8")[:remaining_bytes].decode(
                            "utf-8", errors="ignore"
                        )
                        if prefix:
                            parts.append(prefix)
                    break

                parts.append(piece)
                current_bytes += piece_bytes
                returned_lines += 1

        content = "".join(parts)
        if truncated:
            content += TRUNCATION_MSG
        return ReadResult(file_data=FileData(content=content, encoding="utf-8"))

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
        return await asyncio.to_thread(self.upload_files, files)

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)

    def _to_host_path(self, sandbox_path: str) -> Path | None:
        if not sandbox_path.startswith(self.sandbox_root):
            return None
        rel = sandbox_path[len(self.sandbox_root) :].lstrip("/")
        return resolve_under_workdir(self._workdir, rel)
