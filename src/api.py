"""FastAPI HTTP API for the sandboxed deep agent (HTML GUI backend).

Run (from repo root):
    PYTHONPATH=src uvicorn api:app --host 0.0.0.0 --port 8010

Chat contract (run-based):
    POST /api/sessions/{sid}/chat                     -> 202 {run_id}   (starts a background run)
    GET  /api/sessions/{sid}/runs/{run_id}/events     -> SSE stream; resumable via
                                                         ?after=<seq> or Last-Event-ID header
    POST /api/sessions/{sid}/runs/{run_id}/cancel     -> cancel + checkpoint rollback
    GET  /api/sessions/{sid}/runs/active              -> reconnect discovery
    GET  /api/sessions/{sid}/runs/{run_id}            -> run status

The run keeps executing when the SSE client disconnects; only an explicit
cancel stops it. Reconnecting clients replay missed events from the durable
event log, then tail live events.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Load repo-root .env / .env.local before other app modules read os.environ.
from sandbox_config import (
    configure_file_logging,
    default_network,
    default_workdir,
    env_dir,
    is_desktop_mode,
    load_app_env,
    read_settings_env,
    resolve_data_dir,
    write_settings_env,
)

load_app_env()
configure_file_logging()

from agent import _default_workdir
from sandbox_manager import get_manager
from api_models import (
    ActiveRunResponse,
    CancelResponse,
    ChatRequest,
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
    RunResponse,
    SessionListResponse,
    SessionResponse,
    SessionSummary,
    SettingsResponse,
    SettingsUpdateRequest,
)
from mcp_tools import load_mcp_connections
from message_summary import serialize_messages
from openrouter_model import default_model_for_provider, llm_provider
from runs import RunConflictError
from sessions import store

_SSE_HEARTBEAT_SECONDS = 15


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from agent import ensure_agents_copied

    if is_desktop_mode() or os.environ.get("DEEPAGENT_DATA_DIR"):
        ensure_agents_copied()
    await store.startup()
    manager = get_manager()
    await manager.startup()
    assert store.runs is not None
    manager.bind_cancel_run(store.runs.cancel)
    try:
        yield
    finally:
        await store.close()
        await manager.shutdown()


app = FastAPI(
    title="Deep Agent API",
    description="HTTP API for the microsandbox-backed deep agent GUI.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- helpers -----------------------------------------------------------------


def _session_summary(meta) -> SessionSummary:
    return SessionSummary(
        id=meta.id,
        title=meta.title or "New chat",
        preview=meta.preview or "No session yet",
        message_count=meta.message_count or 0,
        model=meta.model or os.environ.get("OPENROUTER_MODEL") or default_model_for_provider(),
        updated_at=meta.updated_at,
        active_run_id=store.runs.active_run_id(meta.id),
    )


async def _require_session(session_id: str):
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _require_run(session_id: str, run_id: str):
    run = await store._db.get_run(run_id)  # noqa: SLF001 -- thin API-layer access
    if run is None or run.session_id != session_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def _session_response(session) -> SessionResponse:
    message_count = await store._messages.count_messages(session.id)  # noqa: SLF001
    meta = await store.get_meta(session.id)
    last_usage, last_step_usage = meta.parsed_usage() if meta else (None, None)
    return SessionResponse(
        id=session.id,
        sandbox_id=session.sandbox.id,
        workdir=str(session.sandbox._workdir),
        network=session.sandbox.network,
        model=session.model or os.environ.get("OPENROUTER_MODEL") or default_model_for_provider(),
        message_count=message_count,
        mcp_servers=session.mcp_servers,
        mcp_tool_names=session.mcp_tool_names,
        subagent_names=session.subagent_names,
        active_run_id=store.runs.active_run_id(session.id),
        last_usage=last_usage,
        last_step_usage=last_step_usage,
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


# -- health / sessions --------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    manager = get_manager()
    status = manager.status_dict() if manager.started else None
    healthy = bool(status and status.get("healthy"))
    degraded = bool(status and status.get("degraded"))
    return HealthResponse(
        status="ok" if not degraded else "degraded",
        sandbox_healthy=healthy if status else True,
        sandbox_degraded=degraded,
        sandbox_status=status,
    )


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    data = resolve_data_dir()
    manager = get_manager()
    return SettingsResponse(
        desktop=is_desktop_mode(),
        data_dir=str(data),
        workdir=str(default_workdir()),
        env_path=str(env_dir() / ".env"),
        values=read_settings_env(),
        sandbox_status=manager.status_dict() if manager.started else None,
    )


@app.put("/api/settings", response_model=SettingsResponse)
async def put_settings(body: SettingsUpdateRequest) -> SettingsResponse:
    from sandbox_config import sandbox_recreate_fingerprint

    before = sandbox_recreate_fingerprint()
    write_settings_env(body.values)
    after = sandbox_recreate_fingerprint()
    recreated = False
    status = None
    if before != after:
        manager = get_manager()
        try:
            status = await manager.recreate_from_env()
            recreated = True
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    resp = await get_settings()
    resp.sandbox_recreated = recreated
    if status is not None:
        resp.sandbox_status = status
    return resp


@app.post("/api/sandbox/retry")
async def retry_sandbox() -> dict[str, Any]:
    manager = get_manager()
    return await manager.retry_sandbox()


@app.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    metas = await store.list_all()
    return SessionListResponse(sessions=[_session_summary(m) for m in metas])


@app.post("/api/sessions", response_model=SessionResponse, status_code=201)
async def create_session(body: CreateSessionRequest) -> SessionResponse:
    try:
        session = await store.create(
            model=body.model,
            with_subagents=body.with_subagents,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return await _session_response(session)


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    session = await _require_session(session_id)
    return await _session_response(session)


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> Response:
    if not await store.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)


@app.get("/api/sessions/{session_id}/messages", response_model=MessagesResponse)
async def get_messages(session_id: str) -> MessagesResponse:
    if await store.get_meta(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await store.read_messages(session_id)
    await store.sync_chat_summary(session_id, messages)
    return MessagesResponse(messages=serialize_messages(messages))


@app.post("/api/sessions/{session_id}/reset", response_model=ResetResponse)
async def reset_history(session_id: str) -> ResetResponse:
    if await store.get_meta(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await store.reset_thread(session_id)
    return ResetResponse()


# -- chat runs -------------------------------------------------------------


@app.post("/api/sessions/{session_id}/chat", response_model=RunResponse, status_code=202)
async def chat(session_id: str, body: ChatRequest) -> RunResponse:
    """Start one chat turn as a background run and return immediately.

    The run keeps executing even if no client is watching. Attach to
    ``GET .../runs/{run_id}/events`` to stream it.
    """
    session = await _require_session(session_id)
    pwd = _validate_pwd(session, body.pwd)
    try:
        record = await store.start_chat(session_id, message=body.message, pwd=pwd)
    except RunConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": "A run is already in flight", "active_run_id": e.active_run_id},
        ) from e
    return RunResponse(run_id=record.id, session_id=session_id, status=record.status)


@app.get("/api/sessions/{session_id}/runs/active", response_model=ActiveRunResponse)
async def get_active_run(session_id: str) -> ActiveRunResponse:
    if await store.get_meta(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ActiveRunResponse(run_id=store.runs.active_run_id(session_id))


@app.get("/api/sessions/{session_id}/runs/{run_id}", response_model=RunResponse)
async def get_run_status(session_id: str, run_id: str) -> RunResponse:
    run = await _require_run(session_id, run_id)
    return RunResponse(run_id=run.id, session_id=run.session_id, status=run.status)


@app.post("/api/sessions/{session_id}/runs/{run_id}/cancel", response_model=CancelResponse)
async def cancel_run(session_id: str, run_id: str) -> CancelResponse:
    """Cancel an in-flight run. The executor rolls the checkpoint back to its
    pre-turn state and appends a ``cancelled`` event to the run log."""
    await _require_run(session_id, run_id)
    return CancelResponse(cancelled=await store.runs.cancel(run_id))


@app.get("/api/sessions/{session_id}/runs/{run_id}/events")
async def stream_run_events(
    session_id: str,
    run_id: str,
    request: Request,
    after: int | None = Query(None, description="Replay events with seq greater than this"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Resumable SSE stream of a run's events.

    Pure observer: opening or closing this stream never affects the run.
    Each SSE frame carries ``id: <seq>``, so browser ``EventSource`` reconnects
    resume automatically via ``Last-Event-ID``; fetch-based clients can pass
    ``?after=<seq>`` instead. Ends after the terminal event
    (``done`` | ``cancelled`` | ``error``).
    """
    await _require_run(session_id, run_id)

    cursor = 0
    if after is not None:
        cursor = max(0, after)
    elif last_event_id:
        try:
            cursor = max(0, int(last_event_id))
        except ValueError:
            cursor = 0

    async def event_generator():
        agen = store.runs.subscribe(run_id, cursor)
        try:
            while True:
                next_event = asyncio.ensure_future(agen.__anext__())
                # Heartbeat + disconnect detection while waiting for the next event.
                while True:
                    done, _ = await asyncio.wait({next_event}, timeout=_SSE_HEARTBEAT_SECONDS)
                    if done:
                        break
                    if await request.is_disconnected():
                        next_event.cancel()
                        return
                    yield ": ping\n\n"
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    return
                yield (
                    f"id: {event.get('seq', 0)}\n"
                    f"event: {event['type']}\n"
                    f"data: {json.dumps(event)}\n\n"
                )
        finally:
            await agen.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/sessions/{session_id}/chat/stop", response_model=CancelResponse)
async def stop_active_run(session_id: str) -> CancelResponse:
    """Convenience: cancel whatever run is active on this session."""
    if await store.get_meta(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return CancelResponse(cancelled=await store.runs.cancel_session(session_id))


# -- workspace files --------------------------------------------------------


@app.get("/api/sessions/{session_id}/files", response_model=FileListResponse)
async def list_files(
    session_id: str,
    path: str = Query("", description="Path relative to workspace root"),
) -> FileListResponse:
    session = await _require_session(session_id)
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
                (is_dir, name.lower(), FileEntry(path=rel, name=name, is_dir=is_dir, size=size))
            )
    entries = [item for _, _, item in sorted(scanned, key=lambda row: (not row[0], row[1]))]
    rel_path = target.relative_to(workdir).as_posix()
    return FileListResponse(path=rel_path or ".", entries=entries)


@app.get("/api/sessions/{session_id}/files/content", response_model=FileContentResponse)
async def read_file(
    session_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
) -> FileContentResponse:
    session = await _require_session(session_id)
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
async def read_file_raw(
    session_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
) -> Response:
    session = await _require_session(session_id)
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
async def list_folders(session_id: str) -> FolderListResponse:
    session = await _require_session(session_id)
    workdir = Path(session.sandbox._workdir).resolve()
    return FolderListResponse(folders=_list_workspace_folders(workdir))


@app.post(
    "/api/sessions/{session_id}/folders",
    response_model=FolderCreateResponse,
    status_code=201,
)
async def create_folder(session_id: str, body: CreateFolderRequest) -> FolderCreateResponse:
    session = await _require_session(session_id)
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
async def get_config() -> dict[str, Any]:
    mcp_connections = load_mcp_connections()
    manager = get_manager()
    sandbox_status = manager.status_dict() if manager.started else None
    return {
        "default_model": os.environ.get("OPENROUTER_MODEL") or default_model_for_provider(),
        "default_workdir": _default_workdir(),
        "default_network": default_network(),
        "mcp_enabled": bool(mcp_connections),
        "mcp_servers": list(mcp_connections.keys()),
        "username": os.environ.get("DEEPAGENT_USERNAME") or getpass.getuser() or "User",
        "sandbox_backend": os.environ.get("DEEPAGENT_SANDBOX_BACKEND", "microsandbox"),
        "desktop": is_desktop_mode(),
        "data_dir": str(resolve_data_dir()),
        "sandbox_healthy": bool(sandbox_status and sandbox_status.get("healthy")),
        "sandbox_degraded": bool(sandbox_status and sandbox_status.get("degraded")),
        "sandbox_status": sandbox_status,
        "llm_provider": llm_provider(),
        "has_api_key": bool(os.environ.get("OPENROUTER_API_KEY"))
        or llm_provider() == "ollama",
    }


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
