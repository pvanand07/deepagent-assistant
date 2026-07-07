"""Async persistence: LangGraph checkpoints + app DB (sessions, runs, run events).

Everything runs on the FastAPI event loop -- the old ``AsyncLoopRunner``
sync/async bridge is gone. Two SQLite files under the data dir:

- ``checkpoints.sqlite`` -- LangGraph ``AsyncSqliteSaver`` (conversation state).
- ``app.sqlite``         -- session metadata, runs, and the append-only
                            per-run event log that powers stream resume.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


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


def app_db_path() -> Path:
    override = os.environ.get("DEEPAGENT_APP_DB")
    if override:
        return Path(override)
    return default_data_dir() / "app.sqlite"


def thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


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
    def from_row(cls, row: aiosqlite.Row) -> SessionMeta:
        return cls(
            id=row["id"],
            model=row["model"],
            network=bool(row["network"]),
            workdir=row["workdir"],
            with_subagents=bool(row["with_subagents"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            title=row["title"] or "New chat",
            preview=row["preview"] or "No session yet",
            message_count=row["message_count"] or 0,
        )


@dataclass
class RunRecord:
    id: str
    session_id: str
    status: str  # queued | running | done | cancelled | error | interrupted
    created_at: float
    updated_at: float
    error: str | None = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> RunRecord:
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error=row["error"],
        )


class CheckpointManager:
    """Process-wide async SQLite checkpointer (thread_id == session id)."""

    _instance: CheckpointManager | None = None
    _init_lock = asyncio.Lock()

    def __init__(self) -> None:
        self.db_path = checkpoint_db_path()
        self._conn: aiosqlite.Connection | None = None
        self.checkpointer: AsyncSqliteSaver | None = None

    async def _open(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL")
        self.checkpointer = AsyncSqliteSaver(self._conn)
        await self.checkpointer.setup()

    @classmethod
    async def get(cls) -> CheckpointManager:
        async with cls._init_lock:
            if cls._instance is None:
                instance = cls()
                await instance._open()
                cls._instance = instance
            return cls._instance

    async def delete_thread(self, thread_id: str) -> None:
        assert self.checkpointer is not None
        await self.checkpointer.adelete_thread(thread_id)

    async def read_messages(self, thread_id: str) -> list[Any]:
        """Read the latest checkpointed messages for a thread (no agent required)."""
        assert self.checkpointer is not None
        tup = await self.checkpointer.aget_tuple(thread_config(thread_id))
        if tup is None:
            return []
        channel_values = tup.checkpoint.get("channel_values") or {}
        return list(channel_values.get("messages") or [])

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self.checkpointer = None
        type(self)._instance = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    model          TEXT NOT NULL,
    network        INTEGER NOT NULL DEFAULT 0,
    workdir        TEXT,
    with_subagents INTEGER NOT NULL DEFAULT 1,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL,
    title          TEXT NOT NULL DEFAULT 'New chat',
    preview        TEXT NOT NULL DEFAULT 'No session yet',
    message_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    status       TEXT NOT NULL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    error        TEXT,
    baseline_ids TEXT,
    rolled_back  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, created_at);

CREATE TABLE IF NOT EXISTS run_events (
    run_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    type    TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class AppDB:
    """Async SQLite store for session metadata, runs, and run events."""

    _instance: AppDB | None = None
    _init_lock = asyncio.Lock()

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None

    async def _open(self) -> None:
        path = app_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    @classmethod
    async def get(cls) -> AppDB:
        async with cls._init_lock:
            if cls._instance is None:
                instance = cls()
                await instance._open()
                cls._instance = instance
            return cls._instance

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        type(self)._instance = None

    # -- sessions ---------------------------------------------------------

    async def upsert_session(self, meta: SessionMeta) -> None:
        d = asdict(meta)
        await self._conn.execute(
            """INSERT INTO sessions (id, model, network, workdir, with_subagents,
                                     created_at, updated_at, title, preview, message_count)
               VALUES (:id, :model, :network, :workdir, :with_subagents,
                       :created_at, :updated_at, :title, :preview, :message_count)
               ON CONFLICT(id) DO UPDATE SET
                   model=:model, network=:network, workdir=:workdir,
                   with_subagents=:with_subagents, updated_at=:updated_at,
                   title=:title, preview=:preview, message_count=:message_count""",
            d,
        )
        await self._conn.commit()

    async def get_session(self, session_id: str) -> SessionMeta | None:
        async with self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return SessionMeta.from_row(row) if row else None

    async def list_sessions(self) -> list[SessionMeta]:
        async with self._conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [SessionMeta.from_row(r) for r in rows]

    async def touch_session(self, session_id: str) -> None:
        await self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        await self._conn.commit()

    async def update_chat_summary(
        self, session_id: str, *, title: str, preview: str, message_count: int
    ) -> None:
        await self._conn.execute(
            """UPDATE sessions SET title = ?, preview = ?, message_count = ?,
                                   updated_at = ? WHERE id = ?""",
            (title, preview, message_count, time.time(), session_id),
        )
        await self._conn.commit()

    async def delete_session(self, session_id: str) -> bool:
        cur = await self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._conn.execute(
            "DELETE FROM run_events WHERE run_id IN (SELECT id FROM runs WHERE session_id = ?)",
            (session_id,),
        )
        await self._conn.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
        await self._conn.commit()
        return cur.rowcount > 0

    # -- runs ---------------------------------------------------------------

    async def insert_run(self, run_id: str, session_id: str) -> RunRecord:
        now = time.time()
        await self._conn.execute(
            "INSERT INTO runs (id, session_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?)",
            (run_id, session_id, now, now),
        )
        await self._conn.commit()
        return RunRecord(run_id, session_id, "queued", now, now)

    async def set_run_status(self, run_id: str, status: str, *, error: str | None = None) -> None:
        await self._conn.execute(
            "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, time.time(), run_id),
        )
        await self._conn.commit()

    async def set_run_baseline(self, run_id: str, baseline_ids: set[str]) -> None:
        await self._conn.execute(
            "UPDATE runs SET baseline_ids = ? WHERE id = ?",
            (json.dumps(sorted(baseline_ids)), run_id),
        )
        await self._conn.commit()

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
        return RunRecord.from_row(row) if row else None

    async def mark_interrupted_runs(self) -> None:
        """On startup: any run still queued/running belonged to a dead process."""
        await self._conn.execute(
            "UPDATE runs SET status = 'interrupted', updated_at = ? "
            "WHERE status IN ('queued', 'running')",
            (time.time(),),
        )
        await self._conn.commit()

    async def interrupted_unrolled_runs(self, session_id: str) -> list[tuple[str, set[str]]]:
        """(run_id, baseline_ids) for interrupted runs whose checkpoint wasn't rolled back."""
        async with self._conn.execute(
            "SELECT id, baseline_ids FROM runs "
            "WHERE session_id = ? AND status = 'interrupted' AND rolled_back = 0 "
            "AND baseline_ids IS NOT NULL ORDER BY created_at",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [(r["id"], set(json.loads(r["baseline_ids"]))) for r in rows]

    async def mark_run_rolled_back(self, run_id: str) -> None:
        await self._conn.execute("UPDATE runs SET rolled_back = 1 WHERE id = ?", (run_id,))
        await self._conn.commit()

    # -- run events -----------------------------------------------------------

    async def append_run_event(self, run_id: str, seq: int, type_: str, payload: str) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO run_events (run_id, seq, type, payload) VALUES (?, ?, ?, ?)",
            (run_id, seq, type_, payload),
        )
        await self._conn.commit()

    async def read_run_events(self, run_id: str, after_seq: int) -> list[dict[str, Any]]:
        async with self._conn.execute(
            "SELECT payload FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
            (run_id, after_seq),
        ) as cur:
            rows = await cur.fetchall()
        return [json.loads(r["payload"]) for r in rows]
