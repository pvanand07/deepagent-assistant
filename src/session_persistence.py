"""Disk-backed LangGraph checkpoints and session metadata."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator, Coroutine
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeVar

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

T = TypeVar("T")


def default_data_dir() -> Path:
    env = os.environ.get("DEEPAGENT_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def checkpoint_db_path() -> Path:
    override = os.environ.get("DEEPAGENT_CHECKPOINT_DB")
    if override:
        return Path(override)
    return default_data_dir() / "checkpoints.sqlite"


def sessions_meta_path() -> Path:
    return default_data_dir() / "sessions.json"


def thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


class AsyncLoopRunner:
    """Single background event loop for AsyncSqliteSaver and agent.astream()."""

    _instance: AsyncLoopRunner | None = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="deepagent-async",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    @classmethod
    def get(cls) -> AsyncLoopRunner:
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def iter_async_generator(self, agen: AsyncIterator[Any]) -> Any:
        async def _anext() -> Any:
            return await agen.__anext__()

        try:
            while True:
                try:
                    yield self.run(_anext())
                except StopAsyncIteration:
                    break
        finally:
            try:
                self.run(agen.aclose())
            except (RuntimeError, StopAsyncIteration, GeneratorExit):
                pass

    def close(self) -> None:
        if not self._loop.is_running():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


def get_async_runner() -> AsyncLoopRunner:
    return AsyncLoopRunner.get()


@dataclass
class SessionMeta:
    id: str
    model: str
    network: bool
    workdir: str | None
    with_subagents: bool
    created_at: float
    updated_at: float
    title: str = "New chat"
    preview: str = "No session yet"
    message_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMeta:
        return cls(
            id=str(data["id"]),
            model=str(data["model"]),
            network=bool(data.get("network", False)),
            workdir=data.get("workdir"),
            with_subagents=bool(data.get("with_subagents", True)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            title=str(data.get("title") or "New chat"),
            preview=str(data.get("preview") or "No session yet"),
            message_count=int(data.get("message_count") or 0),
        )


class CheckpointManager:
    """Process-wide async SQLite checkpointer (thread_id == session id)."""

    _instance: CheckpointManager | None = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        path = checkpoint_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = path
        self._runner = get_async_runner()
        self._conn: aiosqlite.Connection | None = None
        self.checkpointer: AsyncSqliteSaver | None = None
        self._runner.run(self._open())

    async def _open(self) -> None:
        self._conn = await aiosqlite.connect(str(self.db_path))
        self.checkpointer = AsyncSqliteSaver(self._conn)
        await self.checkpointer.setup()

    @classmethod
    def get(cls) -> CheckpointManager:
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def close(self) -> None:
        if self._conn is not None:
            self._runner.run(self._conn.close())
            self._conn = None
            self.checkpointer = None

    def delete_thread(self, thread_id: str) -> None:
        assert self.checkpointer is not None
        self._runner.run(self.checkpointer.adelete_thread(thread_id))

    def read_messages(self, thread_id: str) -> list[Any]:
        """Read the latest checkpointed messages for a thread (no agent required)."""
        assert self.checkpointer is not None

        async def _read() -> list[Any]:
            tup = await self.checkpointer.aget_tuple(thread_config(thread_id))
            if tup is None:
                return []
            channel_values = tup.checkpoint.get("channel_values") or {}
            messages = channel_values.get("messages") or []
            return list(messages)

        return self._runner.run(_read())

    def message_count(self, thread_id: str) -> int:
        return len(self.read_messages(thread_id))


class SessionMetadataStore:
    """JSON file storing per-session config (model, workdir, etc.)."""

    def __init__(self) -> None:
        self._path = sessions_meta_path()
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionMeta] = {}
        self._load()

    def _load(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._sessions = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = raw.get("sessions") or {}
            self._sessions = {
                sid: SessionMeta.from_dict(meta)
                for sid, meta in items.items()
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self._sessions = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": {sid: asdict(meta) for sid, meta in self._sessions.items()},
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get(self, session_id: str) -> SessionMeta | None:
        with self._lock:
            return self._sessions.get(session_id)

    def upsert(self, meta: SessionMeta) -> None:
        with self._lock:
            self._sessions[meta.id] = meta
            self._save()

    def touch(self, session_id: str) -> None:
        with self._lock:
            meta = self._sessions.get(session_id)
            if meta is None:
                return
            meta.updated_at = time.time()
            self._save()

    def update_chat_summary(
        self,
        session_id: str,
        *,
        title: str,
        preview: str,
        message_count: int,
    ) -> None:
        with self._lock:
            meta = self._sessions.get(session_id)
            if meta is None:
                return
            meta.title = title
            meta.preview = preview
            meta.message_count = message_count
            meta.updated_at = time.time()
            self._save()

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
            self._save()
            return True

    def list_all(self) -> list[SessionMeta]:
        with self._lock:
            return sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)


metadata_store = SessionMetadataStore()
