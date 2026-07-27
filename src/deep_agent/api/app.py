"""FastAPI HTTP API for the sandboxed deep agent (HTML GUI backend).

Run (from repo root):
    PYTHONPATH=src uvicorn deep_agent.api.app:app --host 0.0.0.0 --port 8010

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
from deep_agent.sandbox.config import (
    SANDBOX_NAME,
    configure_file_logging,
    default_network,
    default_workdir,
    is_desktop_mode,
    load_app_env,
    read_settings_env,
    resolve_data_dir,
    write_settings_env,
)

load_app_env()
configure_file_logging()

from deep_agent.sandbox.manager import get_manager
from deep_agent.api.models import (
    ActiveRunResponse,
    AvailableModelsResponse,
    CancelResponse,
    ChatRequest,
    ConfigResponse,
    CreateFolderRequest,
    CreateSessionRequest,
    FileContentResponse,
    FileEntry,
    FileListResponse,
    FolderCreateResponse,
    FolderListResponse,
    HealthResponse,
    McpConfigResponse,
    McpConfigUpdateRequest,
    McpTestResponse,
    MessagesResponse,
    ModelTestRequest,
    ModelTestResponse,
    ResetResponse,
    RunResponse,
    SessionListResponse,
    SessionResponse,
    SessionSummary,
    SettingsResponse,
    SettingsUpdateRequest,
    UpdateSessionRequest,
)
from deep_agent.integrations.mcp import load_mcp_connections
from deep_agent.chat.messages import serialize_messages
from deep_agent.integrations.model_provider import default_model_for_provider, llm_provider
from deep_agent.chat.runs import RunConflictError
from deep_agent.chat.sessions import store
from deep_agent.sandbox.paths import resolve_under_workdir

_SSE_HEARTBEAT_SECONDS = 15


async def _warmup_agent_imports() -> None:
    """Prefetch heavy agent deps so the first Send is faster."""
    try:
        await asyncio.to_thread(__import__, "deep_agent.agent_factory")
    except Exception:
        pass


async def _cancel_task(task: asyncio.Task | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from deep_agent.agent_factory import ensure_agents_copied

    if is_desktop_mode() or os.environ.get("DEEPAGENT_DATA_DIR"):
        ensure_agents_copied()
    await store.startup()
    manager = get_manager()
    assert store.runs is not None
    manager.bind_cancel_run(store.runs.cancel)
    # Do not await sandbox/agent warm-up — /health must succeed ASAP.
    manager.begin_startup()
    sandbox_task = asyncio.create_task(manager.startup())
    warmup_task = asyncio.create_task(_warmup_agent_imports())
    try:
        yield
    finally:
        await _cancel_task(warmup_task)
        await _cancel_task(sandbox_task)
        await store.close()
        await manager.shutdown()


app = FastAPI(
    title="Deep Agent API",
    description="HTTP API for the Bubblewrap-sandboxed deep agent GUI.",
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


async def _require_meta(session_id: str):
    meta = await store.get_meta(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return meta


def _meta_workdir(meta) -> Path:
    raw = getattr(meta, "workdir", None) or str(default_workdir())
    return Path(raw)


async def _require_run(session_id: str, run_id: str):
    run = await store.get_run(run_id)
    if run is None or run.session_id != session_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def _session_response_from_meta(meta) -> SessionResponse:
    message_count = await store.message_count(meta.id)
    last_usage, last_step_usage = meta.parsed_usage()
    cached = store.get_cached(meta.id)
    manager = get_manager()
    if cached is not None:
        sandbox_id = getattr(cached.sandbox, "id", SANDBOX_NAME)
        network = bool(getattr(cached.sandbox, "network", meta.network))
        workdir = str(cached.workdir)
        mcp_servers = cached.mcp_servers
        mcp_tool_names = cached.mcp_tool_names
        subagent_names = cached.subagent_names
    else:
        backend = manager.backend if manager.healthy else None
        sandbox_id = getattr(backend, "id", None) or (
            SANDBOX_NAME if manager.healthy or manager.starting else "pending"
        )
        network = bool(meta.network)
        workdir = str(_meta_workdir(meta))
        mcp_servers = []
        mcp_tool_names = []
        subagent_names = []
    return SessionResponse(
        id=meta.id,
        sandbox_id=str(sandbox_id),
        workdir=workdir,
        network=network,
        model=meta.model or os.environ.get("OPENROUTER_MODEL") or default_model_for_provider(),
        message_count=message_count,
        mcp_servers=mcp_servers,
        mcp_tool_names=mcp_tool_names,
        subagent_names=subagent_names,
        active_run_id=store.runs.active_run_id(meta.id) if store.runs else None,
        last_usage=last_usage,
        last_step_usage=last_step_usage,
        agent_ready=cached is not None,
    )


def _resolve_workspace_path(workdir: Path, rel_path: str) -> Path:
    candidate = resolve_under_workdir(workdir, rel_path)
    if candidate is None:
        raise HTTPException(status_code=400, detail="Path escapes workspace") from None
    return candidate


_PREVIEWABLE_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif",
}

# Web assets served under the path-based HTML preview route so relative
# <link>/<script>/<img> URLs resolve from the entry file's directory.
_PREVIEW_ASSET_SUFFIXES = _PREVIEWABLE_IMAGE_SUFFIXES | {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json", ".svg",
    ".map", ".txt", ".woff", ".woff2", ".ttf", ".otf", ".eot",
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


def _is_preview_asset(path: Path) -> bool:
    return path.suffix.lower() in _PREVIEW_ASSET_SUFFIXES


def _validate_pwd(workdir: Path, pwd: str | None) -> str | None:
    if pwd is None or not pwd.strip():
        return None
    target = _resolve_workspace_path(workdir, pwd)
    if not target.exists():
        raise HTTPException(status_code=404, detail="pwd folder not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="pwd must be a directory")
    rel = str(target.relative_to(workdir.resolve())).replace("\\", "/")
    return rel if rel != "." else ""


# -- health / sessions --------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    manager = get_manager()
    status = manager.status_dict()
    healthy = bool(status.get("healthy"))
    degraded = bool(status.get("degraded"))
    starting = bool(status.get("starting"))
    return HealthResponse(
        status="ok" if not degraded else "degraded",
        sandbox_healthy=healthy,
        sandbox_degraded=degraded,
        sandbox_starting=starting,
        sandbox_status=status,
    )


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    from deep_agent.settings.store import public_settings_view, settings_path

    data = resolve_data_dir()
    manager = get_manager()
    view = public_settings_view()
    path = str(settings_path())
    return SettingsResponse(
        desktop=is_desktop_mode(),
        data_dir=str(data),
        workdir=str(default_workdir()),
        env_path=path,
        settings_path=path,
        values=read_settings_env(),
        config=view,
        setup_required=bool(view.get("setup_required")),
        sandbox_status=manager.status_dict(),
    )


@app.put("/api/settings", response_model=SettingsResponse)
async def put_settings(body: SettingsUpdateRequest) -> SettingsResponse:
    from deep_agent.integrations.model_catalog import clear_catalog_cache
    from deep_agent.sandbox.config import sandbox_recreate_fingerprint
    from deep_agent.settings.store import update_from_ui

    before = sandbox_recreate_fingerprint()
    try:
        if body.config:
            payload = dict(body.config)
            if body.setup_complete is not None:
                payload["setup_complete"] = body.setup_complete
            update_from_ui(payload)
        else:
            values = dict(body.values)
            if body.setup_complete is True:
                # Ensure flat write marks setup done.
                write_settings_env(values)
                from deep_agent.settings.store import load_settings, save_settings

                cfg = load_settings()
                cfg["setup_complete"] = True
                save_settings(cfg)
            else:
                write_settings_env(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clear_catalog_cache()
    store.invalidate_runtime()
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


@app.get(
    "/api/platforms/{platform_id}/models/available",
    response_model=AvailableModelsResponse,
)
async def get_available_models(
    platform_id: str,
    q: str = Query("", description="Optional filter substring"),
) -> AvailableModelsResponse:
    from deep_agent.integrations.model_catalog import list_available_models

    try:
        models = await asyncio.to_thread(
            list_available_models, platform_id, query=q
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AvailableModelsResponse(models=models)


@app.post(
    "/api/platforms/{platform_id}/models/test",
    response_model=ModelTestResponse,
)
async def post_test_model(
    platform_id: str, body: ModelTestRequest
) -> ModelTestResponse:
    from deep_agent.integrations.model_catalog import test_model

    try:
        result = await asyncio.to_thread(test_model, platform_id, body.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelTestResponse(**result)


@app.get("/api/mcp", response_model=McpConfigResponse)
async def get_mcp_config() -> McpConfigResponse:
    from deep_agent.integrations.mcp import mcp_config_path, read_mcp_servers_raw

    path_used, servers = read_mcp_servers_raw()
    path = str(path_used) if path_used else str(mcp_config_path())
    return McpConfigResponse(path=path, servers=servers)


@app.put("/api/mcp", response_model=McpConfigResponse)
async def put_mcp_config(body: McpConfigUpdateRequest) -> McpConfigResponse:
    from deep_agent.integrations.mcp import mcp_config_path, save_mcp_servers

    try:
        servers = save_mcp_servers(body.servers, merge=body.merge)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.invalidate_runtime()
    return McpConfigResponse(path=str(mcp_config_path()), servers=servers)


@app.post("/api/mcp/{name}/test", response_model=McpTestResponse)
async def post_test_mcp(name: str) -> McpTestResponse:
    from deep_agent.integrations.mcp import test_mcp_server

    try:
        result = await test_mcp_server(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return McpTestResponse(**result)


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
        meta = await store.create(
            model=body.model,
            with_subagents=body.with_subagents,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return await _session_response_from_meta(meta)


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    meta = await _require_meta(session_id)
    return await _session_response_from_meta(meta)


@app.patch("/api/sessions/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, body: UpdateSessionRequest) -> SessionResponse:
    """Change the model used for subsequent turns in this session."""
    from deep_agent.chat.runs import RunConflictError

    try:
        meta = await store.set_model(session_id, body.model)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Session not found") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RunConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": "A run is already in flight", "active_run_id": e.active_run_id},
        ) from e
    return await _session_response_from_meta(meta)


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
    meta = await _require_meta(session_id)
    pwd = _validate_pwd(_meta_workdir(meta), body.pwd)
    try:
        record = await store.start_chat(session_id, message=body.message, pwd=pwd)
    except RunConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": "A run is already in flight", "active_run_id": e.active_run_id},
        ) from e
    return RunResponse(
        run_id=record.id,
        session_id=session_id,
        status=record.status,
        error=record.error,
        cause=record.cause,
        stage=record.stage,
    )


@app.get("/api/sessions/{session_id}/runs/active", response_model=ActiveRunResponse)
async def get_active_run(session_id: str) -> ActiveRunResponse:
    if await store.get_meta(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ActiveRunResponse(run_id=store.runs.active_run_id(session_id))


@app.get("/api/sessions/{session_id}/runs/{run_id}", response_model=RunResponse)
async def get_run_status(session_id: str, run_id: str) -> RunResponse:
    run = await _require_run(session_id, run_id)
    return RunResponse(
        run_id=run.id,
        session_id=run.session_id,
        status=run.status,
        error=run.error,
        cause=run.cause,
        stage=run.stage,
    )


@app.post("/api/sessions/{session_id}/runs/{run_id}/cancel", response_model=CancelResponse)
async def cancel_run(session_id: str, run_id: str) -> CancelResponse:
    """Cancel an in-flight run.

    Emits a ``cancelled`` terminal event with ``cause=user_cancel``. The user
    message and any workspace files already written are kept (partial turn).
    """
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
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    target = _resolve_workspace_path(workdir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

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
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    target = _resolve_workspace_path(workdir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Binary file cannot be displayed") from None
    rel = str(target.relative_to(workdir)).replace("\\", "/")
    return FileContentResponse(path=rel, content=content, size=target.stat().st_size)


@app.get("/api/sessions/{session_id}/files/raw")
async def read_file_raw(
    session_id: str,
    path: str = Query(..., description="File path relative to workspace root"),
) -> Response:
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    target = _resolve_workspace_path(workdir, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    if not _is_previewable_image(target):
        raise HTTPException(status_code=415, detail="File type does not support raw preview")
    rel = str(target.relative_to(workdir)).replace("\\", "/")
    return Response(
        content=target.read_bytes(),
        media_type=_media_type_for(target),
        headers={
            "Content-Disposition": f'inline; filename="{target.name}"',
            "X-File-Path": rel,
        },
    )


@app.get("/api/sessions/{session_id}/preview/{file_path:path}")
async def preview_workspace_asset(session_id: str, file_path: str) -> Response:
    """Serve an HTML entry (or sibling CSS/JS/image) for iframe preview.

    Path-based URL so relative ``href``/``src`` on ``output/index.html`` resolve
    to sibling files under the same directory (e.g. ``styles.css``, ``script.js``).
    """
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    target = _resolve_workspace_path(workdir, file_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory")
    if not _is_preview_asset(target):
        raise HTTPException(status_code=415, detail="File type does not support preview")
    rel = str(target.relative_to(workdir)).replace("\\", "/")
    media_type = _media_type_for(target)
    # Browsers often omit a type for .js; prefer an executable MIME for scripts.
    if target.suffix.lower() in {".js", ".mjs", ".cjs"} and media_type == "application/octet-stream":
        media_type = "text/javascript"
    return Response(
        content=target.read_bytes(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{target.name}"',
            "Cache-Control": "no-cache",
            "X-File-Path": rel,
        },
    )


@app.post("/api/sessions/{session_id}/files/open")
async def open_file_native(
    session_id: str,
    path: str = Query(..., description="Office file path relative to workspace root"),
) -> dict[str, str]:
    """Return a web-safe download hint; browsers cannot open host applications."""
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    target = _resolve_workspace_path(workdir, path)
    if not target.exists() or target.is_dir():
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "path": str(target.relative_to(workdir)).replace("\\", "/"),
        "status": "download_or_preview",
    }


@app.get("/api/sessions/{session_id}/folders", response_model=FolderListResponse)
async def list_folders(session_id: str) -> FolderListResponse:
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    return FolderListResponse(folders=_list_workspace_folders(workdir))


@app.post(
    "/api/sessions/{session_id}/folders",
    response_model=FolderCreateResponse,
    status_code=201,
)
async def create_folder(session_id: str, body: CreateFolderRequest) -> FolderCreateResponse:
    meta = await _require_meta(session_id)
    workdir = _meta_workdir(meta).resolve()
    name = _validate_folder_name(body.name)
    parent = body.parent.strip().lstrip("/")
    parent_path = _resolve_workspace_path(workdir, parent)
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
    rel = str(target.relative_to(workdir)).replace("\\", "/")
    return FolderCreateResponse(path=rel if rel != "." else "")


@app.get("/api/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    from deep_agent.settings.store import has_api_key_for_active, setup_required

    mcp_connections = load_mcp_connections()
    manager = get_manager()
    sandbox_status = manager.status_dict()
    return {
        "default_model": os.environ.get("OPENROUTER_MODEL") or default_model_for_provider(),
        "default_workdir": str(default_workdir()),
        "default_network": default_network(),
        "mcp_enabled": bool(mcp_connections),
        "mcp_servers": list(mcp_connections.keys()),
        "username": os.environ.get("DEEPAGENT_USERNAME") or getpass.getuser() or "User",
        "sandbox_backend": "bubblewrap",
        "desktop": is_desktop_mode(),
        "data_dir": str(resolve_data_dir()),
        "sandbox_healthy": bool(sandbox_status.get("healthy")),
        "sandbox_degraded": bool(sandbox_status.get("degraded")),
        "sandbox_starting": bool(sandbox_status.get("starting")),
        "sandbox_status": sandbox_status,
        "llm_provider": llm_provider(),
        "has_api_key": has_api_key_for_active()
        or bool(os.environ.get("OPENROUTER_API_KEY"))
        or llm_provider() == "ollama",
        "setup_required": setup_required(),
    }


_FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
