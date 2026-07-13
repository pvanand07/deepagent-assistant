"""Characterization tests for host-direct sandbox file I/O."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from microsandbox_sandbox import MicrosandboxSandbox


def _sandbox(workdir: Path) -> MicrosandboxSandbox:
    manager = SimpleNamespace(workdir=workdir, network=False, loop=None)
    return MicrosandboxSandbox(manager=manager, stub=True)


def test_host_read_pages_text_and_rejects_workspace_escape(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    (tmp_path / "notes.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("private", encoding="utf-8")

    result = sandbox.read("/workspace/notes.txt", offset=1, limit=2)
    assert result.file_data is not None
    assert result.file_data["content"] == "two\nthree"

    rejected = sandbox.read("/workspace/../outside.txt")
    assert rejected.error == "File '/workspace/../outside.txt': invalid_path"


def test_host_read_encodes_binary_files(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    content = b"\x00\xffbinary"
    (tmp_path / "image.bin").write_bytes(content)

    result = sandbox.read("/workspace/image.bin")

    assert result.file_data is not None
    assert result.file_data["encoding"] == "base64"
    assert base64.b64decode(result.file_data["content"]) == content


def test_host_upload_and_download_report_path_errors(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)

    uploads = sandbox.upload_files(
        [
            ("/workspace/nested/output.txt", b"saved"),
            ("/tmp/outside.txt", b"ignored"),
        ]
    )
    assert [item.error for item in uploads] == [None, "invalid_path"]
    assert (tmp_path / "nested" / "output.txt").read_bytes() == b"saved"

    (tmp_path / "folder").mkdir()
    downloads = sandbox.download_files(
        [
            "/workspace/nested/output.txt",
            "/workspace/folder",
            "/workspace/missing.txt",
            "/tmp/outside.txt",
        ]
    )
    assert downloads[0].content == b"saved"
    assert downloads[1].error in {"is_directory", "permission_denied"}
    assert [item.error for item in downloads[2:]] == ["file_not_found", "invalid_path"]
