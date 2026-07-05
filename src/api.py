"""FastAPI HTTP API for the sandboxed deep agent (HTML GUI backend).

Run (from repo root):
    PYTHONPATH=src uvicorn api:app --host 0.0.0.0 --port 8010 --reload
"""

from __future__ import annotations

import json
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import messages_to_dict

from agent import _default_workdir
from api_models import (
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    FileContentResponse,
    FileEntry,
    FileListResponse,
    FolderListResponse,
    HealthResponse,
    MessagesResponse,
    ResetResponse,
    SessionListResponse,
    SessionResponse,
    SessionSummary,
)
from mcp_tools import load_mcp_connections
from openrouter_model import DEFAULT_MODEL
from sessions import store
from streaming import iter_agent_turn_events


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    store.cleanup_all()


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
    if not messages:
        return []
    if isinstance(messages[0], dict):
        return messages
    return messages_to_dict(messages)


def _first_user_text(messages: list) -> str:
    serialized = _serialize_messages(messages)
    for msg in serialized:
        role = msg.get("type") or msg.get("role")
        if role not in {"human", "user"}:
            continue
        data = msg.get("data", msg)
        content = data.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            text = "".join(parts).strip()
            if text:
                return text
    return ""


def _session_title(session) -> str:
    title = _first_user_text(session.history)
    if not title:
        return "New chat"
    return title if len(title) <= 48 else title[:47] + "…"


def _session_summary(session) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        title=_session_title(session),
        message_count=len(session.history),
        model=session.model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        updated_at=session.updated_at,
    )


def _last_assistant_text(messages: list) -> str:
    serialized = _serialize_messages(messages)
    for msg in reversed(serialized):
        role = msg.get("type") or msg.get("role")
        if role in {"ai", "assistant"}:
            data = msg.get("data", msg)
            content = data.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "".join(parts)
    return ""


def _require_session(session_id: str):
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _session_response(session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        sandbox_id=session.sandbox.id,
        workdir=str(session.sandbox._workdir),
        network=session.sandbox.network,
        model=session.model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        message_count=len(session.history),
        mcp_servers=session.mcp_servers,
        mcp_tool_names=session.mcp_tool_names,
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
    return SessionListResponse(sessions=[_session_summary(s) for s in store.list_all()])


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
    session = _require_session(session_id)
    with session.lock:
        return MessagesResponse(messages=_serialize_messages(session.history))


@app.post("/api/sessions/{session_id}/reset", response_model=ResetResponse)
def reset_history(session_id: str) -> ResetResponse:
    session = _require_session(session_id)
    with session.lock:
        session.history = []
    return ResetResponse()


@app.post("/api/sessions/{session_id}/chat", response_model=ChatResponse)
def chat(session_id: str, body: ChatRequest) -> ChatResponse:
    session = _require_session(session_id)
    pwd = _validate_pwd(session, body.pwd)
    with session.lock:
        session.history.append({"role": "user", "content": body.message})
        session.touch()
        final_messages = session.history
        for event in iter_agent_turn_events(session.agent, session.history, pwd=pwd):
            if event["type"] == "done":
                final_messages = event["messages"]
        session.history = final_messages
        session.touch()
        return ChatResponse(
            reply=_last_assistant_text(final_messages),
            messages=_serialize_messages(final_messages),
        )


@app.post("/api/sessions/{session_id}/chat/stream")
def chat_stream(session_id: str, body: ChatRequest) -> StreamingResponse:
    session = _require_session(session_id)
    pwd = _validate_pwd(session, body.pwd)

    def event_generator():
        with session.lock:
            session.history.append({"role": "user", "content": body.message})
            session.touch()
            history_snapshot = list(session.history)
            for event in iter_agent_turn_events(session.agent, history_snapshot, pwd=pwd):
                if event["type"] == "done":
                    session.history = event["messages"]
                    session.touch()
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

    entries: list[FileEntry] = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel = child.relative_to(Path(session.sandbox._workdir).resolve())
        entries.append(
            FileEntry(
                path=str(rel).replace("\\", "/"),
                name=child.name,
                is_dir=child.is_dir(),
                size=None if child.is_dir() else child.stat().st_size,
            )
        )
    rel_path = str(target.relative_to(Path(session.sandbox._workdir).resolve())).replace("\\", "/")
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
    folders = [""]
    for path in sorted(workdir.rglob("*"), key=lambda p: str(p).lower()):
        if path.is_dir():
            rel = str(path.relative_to(workdir)).replace("\\", "/")
            folders.append(rel)
    return FolderListResponse(folders=folders)


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
    }


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
