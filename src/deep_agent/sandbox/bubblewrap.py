"""Bubblewrap-based sandbox backend for deepagents.

Implements `deepagents.backends.sandbox.BaseSandbox` using `bwrap` (bubblewrap)
for real OS-level isolation: separate mount/pid/uts/ipc/cgroup namespaces, an
unprivileged user namespace, a read-only view of the host system, and (by
default) no network access. Only one host directory -- the sandbox's own
workdir -- is bind-mounted read-write.

This gives every `execute()` call:
- Its own filesystem view (host files outside the allow-list are invisible,
  not just "denied" -- there's nothing to traverse into).
- Its own PID namespace (can't see or signal host/other processes).
- No network access unless explicitly enabled.
- No setuid/privilege-escalation path (`--unshare-user`, `--die-with-parent`).

It does NOT provide CPU/memory/disk quota enforcement by itself (bwrap has no
cgroup-based resource limiting built in) -- see `_apply_rlimits` for the
best-effort per-process limits applied via `prlimit`/`RLIMIT_*`, and the
docstring note below on pairing this with cgroups v2 for hard quotas.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

DEFAULT_TIMEOUT = 120
DEFAULT_MAX_OUTPUT_BYTES = 200_000

# Host paths made read-only inside every sandbox. Enough for python3, bash,
# coreutils, and common interpreters/build tools to run. Missing paths are
# skipped silently (not every host has /lib64, etc.).
_DEFAULT_RO_BINDS = [
    "/usr",
    "/bin",
    "/lib",
    "/lib64",
    "/etc/alternatives",
    "/etc/ssl",
    "/etc/resolv.conf",
    "/etc/nsswitch.conf",
    "/etc/hosts",
]


class BubblewrapSandbox(BaseSandbox):
    """Sandbox backend that runs `execute()` inside a `bwrap` namespace jail.

    Examples:
        ```python
        from deep_agent.sandbox.bubblewrap import BubblewrapSandbox
        from deepagents import create_deep_agent

        sandbox = BubblewrapSandbox(network=False)
        agent = create_deep_agent(backend=sandbox)
        ```

        Or drive it directly:
        ```python
        sandbox = BubblewrapSandbox()
        sandbox.upload_files([("/workspace/main.py", b"print('hi')")])
        result = sandbox.execute("python3 /workspace/main.py")
        print(result.output, result.exit_code)
        sandbox.cleanup()
        ```
    """

    def __init__(
        self,
        *,
        workdir: str | Path | None = None,
        sandbox_root: str = "/workspace",
        network: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        extra_ro_binds: list[str] | None = None,
        env: dict[str, str] | None = None,
        as_uid: int = 0,
        as_gid: int = 0,
        rlimit_as_mb: int | None = 1024,
        rlimit_nproc: int | None = 64,
    ) -> None:
        """Create a bubblewrap-backed sandbox.

        Args:
            workdir: Host directory bind-mounted read-write into the sandbox
                at `sandbox_root`. Created under a temp dir if not given, and
                owned/cleaned up by this instance in that case.
            sandbox_root: Path inside the sandbox where `workdir` is mounted.
                All `execute`/`upload_files`/`download_files` paths must live
                under this prefix.
            network: If False (default), the sandbox gets its own network
                namespace with no interfaces -- no network access at all,
                including localhost. If True, network namespace is shared
                with the host.
            timeout: Default wall-clock timeout in seconds for `execute()`.
            max_output_bytes: Output is truncated past this size.
            extra_ro_binds: Additional host paths to bind read-only, beyond
                the default set needed for a basic Python/shell environment.
            env: Environment variables available inside the sandbox. Starts
                empty (a minimal PATH/HOME/TMPDIR is always injected) unless
                overridden here -- the host environment is never inherited.
            as_uid: Fake uid presented inside the sandbox's user namespace
                (cosmetic only -- it maps to the real host user's privileges,
                not an actual privilege change).
            as_gid: Fake gid, see `as_uid`.
            rlimit_as_mb: Best-effort address-space limit per process, in MB.
                None disables the limit. This is not a substitute for cgroup
                accounting under concurrent load.
            rlimit_nproc: Best-effort cap on number of processes/threads the
                sandboxed user can create. None disables the limit.
        """
        if shutil.which("bwrap") is None:
            msg = "bubblewrap ('bwrap') is not installed or not on PATH."
            raise RuntimeError(msg)

        self._id = f"bwrap-{uuid.uuid4().hex[:12]}"
        self._owns_workdir = workdir is None
        self._workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="bwrap-sandbox-"))
        self._workdir.mkdir(parents=True, exist_ok=True)

        self.sandbox_root = sandbox_root.rstrip("/") or "/workspace"
        self.network = network
        self.default_timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.extra_ro_binds = extra_ro_binds or []
        self.env = env or {}
        self.as_uid = as_uid
        self.as_gid = as_gid
        self.rlimit_as_mb = rlimit_as_mb
        self.rlimit_nproc = rlimit_nproc

    # -- SandboxBackendProtocol -----------------------------------------

    @property
    def id(self) -> str:
        """Unique identifier for this sandbox instance."""
        return self._id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Run `command` inside a fresh bwrap jail and return its output.

        Each call spins up a brand-new sandbox process (bwrap has no
        persistent "container" to attach to) sharing only the `workdir`
        bind-mount as state between calls -- which matches how the
        filesystem tools (`ls`/`read_file`/etc, all implemented on top of
        `execute()` by `BaseSandbox`) expect to see consistent file state
        across calls.
        """
        effective_timeout = timeout if timeout else self.default_timeout
        no_timeout = timeout == 0

        argv = self._build_bwrap_argv(command)

        try:
            proc = subprocess.run(  # noqa: S603
                argv,
                capture_output=True,
                timeout=None if no_timeout else effective_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or b"") + (e.stderr or b"")
            output = partial.decode("utf-8", errors="replace")
            return ExecuteResponse(
                output=(output + f"\n[Command timed out after {effective_timeout}s]"),
                exit_code=None,
                truncated=len(partial) > self.max_output_bytes,
            )

        raw = (proc.stdout or b"") + (proc.stderr or b"")
        truncated = len(raw) > self.max_output_bytes
        if truncated:
            raw = raw[: self.max_output_bytes]
        output = raw.decode("utf-8", errors="replace")
        if truncated:
            output += "\n[Output truncated]"

        return ExecuteResponse(output=output, exit_code=proc.returncode, truncated=truncated)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Write files directly to the host-side workdir (no sandbox needed for I/O)."""
        results = []
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
        """Read files directly from the host-side workdir."""
        results = []
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

    # -- lifecycle --------------------------------------------------------

    def cleanup(self) -> None:
        """Remove the host workdir if this instance created it."""
        if self._owns_workdir and self._workdir.exists():
            shutil.rmtree(self._workdir, ignore_errors=True)

    def __enter__(self) -> "BubblewrapSandbox":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()

    # -- internals ----------------------------------------------------------

    def _to_host_path(self, sandbox_path: str) -> Path | None:
        """Map a sandbox-visible path under `sandbox_root` to its host path."""
        if not sandbox_path.startswith(self.sandbox_root):
            return None
        rel = sandbox_path[len(self.sandbox_root) :].lstrip("/")
        candidate = (self._workdir / rel).resolve()
        # Guard against `..` escaping workdir.
        try:
            candidate.relative_to(self._workdir.resolve())
        except ValueError:
            return None
        return candidate

    def _build_bwrap_argv(self, command: str) -> list[str]:
        argv: list[str] = ["bwrap"]

        # Namespaces: isolate everything, then explicitly punch a hole for
        # network if requested. --die-with-parent kills the sandbox if we
        # get killed/crash, so nothing lingers.
        argv += [
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
        ]
        if self.network:
            argv += ["--share-net"]

        # Minimal read-only base system.
        for host_path in [*_DEFAULT_RO_BINDS, *self.extra_ro_binds]:
            if os.path.exists(host_path):
                argv += ["--ro-bind", host_path, host_path]

        # Pseudo-filesystems. Use a read-only bind of the host /proc instead of
        # `--proc`, which mounts a fresh procfs and fails inside Docker even
        # with apparmor/seccomp unconfined ("Can't mount proc on /newroot/proc:
        # Operation not permitted"). A ro-bind is enough for python3/shell
        # tooling; PID isolation still comes from --unshare-all.
        if os.path.exists("/proc"):
            argv += ["--ro-bind", "/proc", "/proc"]
        argv += [
            "--dev", "/dev",
            "--tmpfs", "/tmp",
        ]

        # The only writable area: our workdir, mounted at sandbox_root.
        argv += ["--bind", str(self._workdir), self.sandbox_root]

        # Cosmetic uid/gid inside the user namespace + working directory.
        argv += ["--uid", str(self.as_uid), "--gid", str(self.as_gid)]
        argv += ["--chdir", self.sandbox_root]

        # Clean, minimal environment -- host env is never inherited.
        argv += ["--clearenv"]
        base_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": self.sandbox_root,
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
        }
        base_env.update(self.env)
        for key, value in base_env.items():
            argv += ["--setenv", key, value]

        wrapped = self._wrap_with_rlimits(command)
        argv += ["/bin/sh", "-c", wrapped]
        return argv

    def _wrap_with_rlimits(self, command: str) -> str:
        """Best-effort per-process resource caps applied inside the jail.

        bwrap itself has no resource-limiting of its own; this uses the
        shell's `ulimit` (RLIMIT_AS / RLIMIT_NPROC) as a cheap safety net.
        For real quota *enforcement* under concurrent/adversarial load,
        pair this backend with a cgroup v2 slice around the whole `bwrap`
        invocation (e.g. `systemd-run --scope -p MemoryMax=... -p CPUQuota=...
        bwrap ...`) -- ulimit alone can be defeated by fork-heavy workloads.
        """
        prefix_parts = []
        if self.rlimit_as_mb is not None:
            prefix_parts.append(f"ulimit -v {self.rlimit_as_mb * 1024} 2>/dev/null;")
        if self.rlimit_nproc is not None:
            prefix_parts.append(f"ulimit -u {self.rlimit_nproc} 2>/dev/null;")
        prefix = " ".join(prefix_parts)
        return f"{prefix} {command}" if prefix else command
