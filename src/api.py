"""FastAPI HTTP API for the sandboxed deep agent (HTML GUI backend).

Run (from repo root):
    PYTHONPATH=src uvicorn api:app --host 0.0.0.0 --port 8010 --reload
"""

from __future__ import annotations

import json
import mimetypes
import os
import getpass
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent import _default_workdir
from api_models import (
    ChatRequest,
    ChatResponse,
    CreateFolderRequest,
    CreateSessionRequest,
    FileContentResponse,
    FileEntry,
    FileListResponse,
    FolderCreateResponse,
    FolderListResponse,
    HealthResponse,
    MessagesResponse,
    ResetResponse,
    SessionListResponse,
    SessionResponse,
    SessionSummary,
)
from mcp_tools import load_mcp_connections
from message_summary import last_assistant_text, serialize_messages
from openrouter_model import DEFAULT_MODEL
from sessions import store
from streaming import iter_agent_turn_events


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    store.close()


app = FastAPI(
    title="Deep Agent API",
    description="HTTP API for the bubblewrap-sandboxed deep agent GUI.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize_messages(messages: list) -> list[dict[str, Any]]:
    return serialize_messages(messages)


def _session_summary(meta) -> SessionSummary:
    return SessionSummary(
        id=meta.id,
        title=meta.title or "New chat",
        preview=meta.preview or "No session yet",
        message_count=meta.message_count or 0,
        model=meta.model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        updated_at=meta.updated_at,
    )


def _last_assistant_text(messages: list) -> str:
    return last_assistant_text(messages)


def _require_session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _session_response(session) -> SessionResponse:
    messages = session.get_messages()
    return SessionResponse(
        id=session.id,
        sandbox_id=session.sandbox.id,
        workdir=str(session.sandbox._workdir),
        network=session.sandbox.network,
        model=session.model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        message_count=len(messages),
        mcp_servers=session.mcp_servers,
        mcp_tool_names=session.mcp_tool_names,
        subagent_names=session.subagent_names,
    )


def _resolve_workspace_path(session, rel_path: str) -> Path:
    workdir = Path(session.sandbox._workdir).resolve()
    clean = rel_path.strip().lstrip("/")
    candidate = (workdir / clean).resolve()
    try:
        candidate.relative_to(workdir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes workspace") from None
    return candidate


_PREVIEWABLE_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif",
}

# Directory names skipped when listing workspace folders for the pwd picker.
_SKIP_FOLDER_NAMES = frozenset({
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "target",
    "site-packages",
})


def _should_skip_folder_dir(name: str) -> bool:
    return name.startswith(".") or name in _SKIP_FOLDER_NAMES


def _validate_folder_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if clean in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid folder name")
    if "/" in clean or "\\" in clean:
        raise HTTPException(status_code=400, detail="Folder name cannot contain path separators")
    return clean


def _list_workspace_folders(workdir: Path) -> list[str]:
    """Return workspace-relative folder paths, pruning hidden and cache trees."""
    root = workdir.resolve()
    folders = [""]
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            child_dirs: list[Path] = []
            with os.scandir(current) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if _should_skip_folder_dir(entry.name):
                        continue
                    child = Path(entry.path)
                    child_dirs.append(child)
                    folders.append(child.relative_to(root).as_posix())
            stack.extend(sorted(child_dirs, key=lambda p: p.name.lower(), reverse=True))
        except OSError:
            continue
    folders.sort(key=str.lower)
    return folders


def _media_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _is_previewable_image(path: Path) -> bool:
    return path.suffix.lower() in _PREVIEWABLE_IMAGE_SUFFIXES


def _validate_pwd(session, pwd: str | None) -> str | None:
    if pwd is None or not pwd.strip():
        return None
    target = _resolve_workspace_path(session, pwd)
    if not target.exists():
        raise HTTPException(status_code=404, detail="pwd folder not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="pwd must be a directory")
    rel = str(target.relative_to(Path(session.sandbox._workdir).resolve())).replace("\\", "/")
    return rel if rel != "." else ""


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/sessions", response_model=SessionListResponse)
def list_sessions() -> SessionListResponse:
    return SessionListResponse(sessions=[_session_summary(m) for m in store.list_all()])


@app.post("/api/sessions", response_model=SessionResponse, status_code=201)
def create_session(body: CreateSessionRequest) -> SessionResponse:
    try:
        session = store.create(
            model=body.model,
            network=body.network,
            workdir=body.workdir,
            with_subagents=body.with_subagents,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return _session_response(session)


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    return _session_response(_require_session(session_id))


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    if not store.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/sessions/{session_id}/messages", response_model=MessagesResponse)
def get_messages(session_id: str) -> MessagesResponse:
    _require_session(session_id)
    messages = store.read_messages(session_id)
    store.sync_chat_summary(session_id, messages)
    return MessagesResponse(messages=_serialize_messages(messages))


@app.post("/api/sessions/{session_id}/reset", response_model=ResetResponse)
def reset_history(session_id: str) -> ResetResponse:
    _require_session(session_id)
    store.reset_thread(session_id)
    return ResetResponse()


@app.post("/api/sessions/{session_id}/chat", response_model=ChatResponse)
def chat(session_id: str, body: ChatRequest) -> ChatResponse:
    session = _require_session(session_id)
    pwd = _validate_pwd(session, body.pwd)
    user_turn = [{"role": "user", "content": body.message}]
    with session.lock:
        session.touch()
        final_messages = user_turn
        for event in iter_agent_turn_events(
            session.agent,
            user_turn,
            thread_id=session.id,
            pwd=pwd,
        ):
            if event["type"] == "done":
                final_messages = event["messages"]
        session.touch()
        store.sync_chat_summary(session_id, final_messages)
        return ChatResponse(
            reply=_last_assistant_text(final_messages),
            messages=_serialize_messages(final_messages),
        )


@app.post("/api/sessions/{session_id}/chat/stream")
def chat_stream(session_id: str, body: ChatRequest) -> StreamingResponse:
    session = _require_session(session_id)
    pwd = _validate_pwd(session, body.pwd)

    def event_generator():
        user_turn = [{"role": "user", "content": body.message}]
        with session.lock:
            session.touch()
            for event in iter_agent_turn_events(
                session.agent,
                user_turn,
                thread_id=session.id,
                pwd=pwd,
            ):
                if event["type"] == "done":
                    session.touch()
                    store.sync_chat_summary(session_id, event["messages"])
                    payload = {
                        "type": "done",
                        "messages": _serialize_messages(event["messages"]),
                        "reply": _last_assistant_text(event["messages"]),
                        "usage": event.get("usage"),
                    }
                else:
                    payload = event
                yield f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/sessions/{session_id}/files", response_model=FileListResponse)
def list_files(
    session_id: str,
    path: str = Query("", description="Path relative to workspace root"),
) -> FileListResponse:
    session = _require_session(session_id)
    target = _resolve_workspace_path(session, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    workdir = Path(session.sandbox._workdir).resolve()
    scanned: list[tuple[bool, str, FileEntry]] = []
    with os.scandir(target) as entries:
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            name = entry.name
            rel = Path(entry.path).relative_to(workdir).as_posix()
            size: int | None = None
            if not is_dir:
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
            scanned.append(
                (
                    is_dir,
                    name.lower(),
                    FileEntry(path=rel, name=name, is_dir=is_dir, size=size),
                )
            )
    entries = [item for _, _, item in sorted(scanned, key=lambda row: (not row[0], row[1]))]
    rel_path = target.relative_to(workdir).as_posix()
    return FileListResponse(path=rel_path or ".", entries=entries)


@app.get("/api/sessions/{session_id}/files/content", response_model=FileContentResponse)
def read_file(
    session_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
) -> FileContentResponse:
    session = _require_session(session_id)
    target = _resolve_workspace_path(session, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Binary file cannot be displayed") from None
    rel = str(target.relative_to(Path(session.sandbox._workdir).resolve())).replace("\\", "/")
    return FileContentResponse(path=rel, content=content, size=target.stat().st_size)


@app.get("/api/sessions/{session_id}/files/raw")
def read_file_raw(
    session_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
) -> Response:
    session = _require_session(session_id)
    target = _resolve_workspace_path(session, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    if not _is_previewable_image(target):
        raise HTTPException(status_code=415, detail="File type does not support raw preview")
    rel = str(target.relative_to(Path(session.sandbox._workdir).resolve())).replace("\\", "/")
    return Response(
        content=target.read_bytes(),
        media_type=_media_type_for(target),
        headers={
            "Content-Disposition": f'inline; filename="{target.name}"',
            "X-File-Path": rel,
        },
    )


@app.get("/api/sessions/{session_id}/folders", response_model=FolderListResponse)
def list_folders(session_id: str) -> FolderListResponse:
    session = _require_session(session_id)
    workdir = Path(session.sandbox._workdir).resolve()
    return FolderListResponse(folders=_list_workspace_folders(workdir))


@app.post("/api/sessions/{session_id}/folders", response_model=FolderCreateResponse, status_code=201)
def create_folder(session_id: str, body: CreateFolderRequest) -> FolderCreateResponse:
    session = _require_session(session_id)
    name = _validate_folder_name(body.name)
    parent = body.parent.strip().lstrip("/")
    parent_path = _resolve_workspace_path(session, parent)
    if not parent_path.exists():
        raise HTTPException(status_code=404, detail="Parent folder not found")
    if not parent_path.is_dir():
        raise HTTPException(status_code=400, detail="Parent path is not a directory")
    target = parent_path / name
    if target.exists():
        raise HTTPException(status_code=409, detail="Folder already exists")
    try:
        target.mkdir(parents=False, exist_ok=False)
    except OSError as e:
        raise HTTPException(status_code=500, detail="Failed to create folder") from e
    workdir = Path(session.sandbox._workdir).resolve()
    rel = str(target.relative_to(workdir)).replace("\\", "/")
    return FolderCreateResponse(path=rel if rel != "." else "")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    mcp_connections = load_mcp_connections()
    return {
        "default_model": os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        "default_workdir": _default_workdir(),
        "default_network": os.environ.get("DEEPAGENT_NETWORK_ACCESS", "false").lower()
        in {"1", "true", "yes"},
        "mcp_enabled": bool(mcp_connections),
        "mcp_servers": list(mcp_connections.keys()),
        "username": os.environ.get("DEEPAGENT_USERNAME") or getpass.getuser() or "User",
    }


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
