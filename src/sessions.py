"""Async session store: agent hydration, run orchestration, persistence glue."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent import _default_network, _default_workdir, build_agent
from mcp_tools import load_mcp_tools
from message_summary import messages_after_baseline, summary_from_messages
from openrouter_model import DEFAULT_MODEL
from runs import RunManager
from session_persistence import (
    AppDB,
    CheckpointManager,
    MessageDB,
    RunRecord,
    SessionMeta,
    thread_config,
)
from streaming import rollback_uncommitted_turn


@dataclass
class AgentSession:
    id: str
    agent: Any
    sandbox: Any
    model: str
    mcp_servers: list[str] = field(default_factory=list)
    mcp_tool_names: list[str] = field(default_factory=list)
    subagent_names: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def cleanup(self) -> None:
        """Per-session cleanup. Shared microsandbox VM is not destroyed here."""
        cleanup = getattr(self.sandbox, "cleanup", None)
        if callable(cleanup):
            cleanup()


class SessionStore:
    """Owns session lifecycle. All methods run on the app event loop.

    Concurrency model:
    - Hydration (agent build) is guarded per session id, so two simultaneous
      requests never build the same agent twice.
    - One run at a time per session (enforced by ``RunManager``); runs on
      different sessions execute in parallel, bounded by a global semaphore.
    - MCP tools are loaded once per process and shared across all agents.
    - All sessions share one microsandbox backend from ``SandboxManager``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._hydration_locks: dict[str, asyncio.Lock] = {}
        self._db: AppDB | None = None
        self._messages: MessageDB | None = None
        self._checkpoints: CheckpointManager | None = None
        self.runs: RunManager | None = None
        self._mcp_cache: tuple[list, list[str]] | None = None
        self._mcp_lock = asyncio.Lock()

    async def startup(self) -> None:
        self._db = await AppDB.get()
        self._messages = await MessageDB.get()
        self._checkpoints = await CheckpointManager.get()
        await self._db.mark_interrupted_runs()
        self.runs = RunManager(self._db, self._messages)

    async def close(self) -> None:
        if self.runs is not None:
            await self.runs.cancel_all()
        for session in list(self._sessions.values()):
            session.cleanup()
        self._sessions.clear()
        if self._checkpoints is not None:
            await self._checkpoints.close()
        if self._messages is not None:
            await self._messages.close()
        if self._db is not None:
            await self._db.close()

    def _resolved_model(self, model: str | None) -> str:
        return model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    async def _get_mcp(self) -> tuple[list, list[str]]:
        async with self._mcp_lock:
            if self._mcp_cache is None:
                tools, servers = await asyncio.to_thread(load_mcp_tools)
                self._mcp_cache = (tools, servers)
            return self._mcp_cache

    async def _build_session(self, meta: SessionMeta) -> AgentSession:
        mcp_tools, mcp_servers = await self._get_mcp()
        from sandbox_manager import get_manager

        sandbox = get_manager().backend
        agent, sandbox, mcp_meta = await asyncio.to_thread(
            build_agent,
            model_name=meta.model,
            with_subagents=meta.with_subagents,
            mcp_tools=mcp_tools,
            mcp_servers=mcp_servers,
            checkpointer=self._checkpoints.checkpointer,
            sandbox=sandbox,
        )
        return AgentSession(
            id=meta.id,
            agent=agent,
            sandbox=sandbox,
            model=meta.model,
            mcp_servers=mcp_meta["servers"],
            mcp_tool_names=mcp_meta["tool_names"],
            subagent_names=mcp_meta.get("subagent_names", []),
            created_at=meta.created_at,
            updated_at=meta.updated_at,
        )

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._hydration_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._hydration_locks[session_id] = lock
        return lock

    async def _rollback_interrupted(self, session: AgentSession) -> None:
        config = thread_config(session.id)
        for run_id, baseline_ids in await self._db.interrupted_unrolled_runs(session.id):
            try:
                await rollback_uncommitted_turn(session.agent, config, baseline_ids)
            except Exception:
                continue
            await self._db.mark_run_rolled_back(run_id)

    async def create(
        self,
        *,
        model: str | None = None,
        with_subagents: bool = True,
    ) -> AgentSession:
        now = time.time()
        meta = SessionMeta(
            id=uuid.uuid4().hex,
            model=self._resolved_model(model),
            network=_default_network(),
            workdir=_default_workdir(),
            with_subagents=with_subagents,
            created_at=now,
            updated_at=now,
        )
        session = await self._build_session(meta)
        await self._db.upsert_session(meta)
        self._sessions[session.id] = session
        return session

    async def get(self, session_id: str, *, hydrate: bool = True) -> AgentSession | None:
        cached = self._sessions.get(session_id)
        if cached is not None:
            return cached
        if not hydrate:
            return None
        async with self._lock_for(session_id):
            cached = self._sessions.get(session_id)
            if cached is not None:
                return cached
            meta = await self._db.get_session(session_id)
            if meta is None:
                return None
            session = await self._build_session(meta)
            self._sessions[session_id] = session
            return session

    async def get_meta(self, session_id: str) -> SessionMeta | None:
        return await self._db.get_session(session_id)

    async def list_all(self) -> list[SessionMeta]:
        return await self._db.list_sessions()

    async def read_messages(self, session_id: str) -> list[Any]:
        messages = await self._messages.list_messages(session_id)
        if messages:
            return messages
        return await self._backfill_messages_from_runs(session_id)

    async def _backfill_messages_from_runs(self, session_id: str) -> list[Any]:
        for run_id, baseline_ids in await self._db.list_done_runs(session_id):
            events = await self._db.read_run_events(run_id, after_seq=0)
            for event in reversed(events):
                if event.get("type") != "done":
                    continue
                payloads = messages_after_baseline(
                    event.get("messages") or [], baseline_ids
                )
                if payloads:
                    await self._messages.append_many(session_id, payloads, run_id=run_id)
                break
        return await self._messages.list_messages(session_id)

    async def sync_chat_summary(
        self, session_id: str, messages: list[Any] | None = None
    ) -> None:
        if messages is None:
            messages = await self.read_messages(session_id)
        title, preview, count = summary_from_messages(messages)
        await self._db.update_chat_summary(
            session_id, title=title, preview=preview, message_count=count
        )

    async def start_chat(self, session_id: str, *, message: str, pwd: str | None) -> RunRecord:
        session = await self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        await self._rollback_interrupted(session)
        await self._db.touch_session(session_id)

        user_message_id = uuid.uuid4().hex

        async def on_terminal(
            status: str,
            final_messages: list | None,
            *,
            baseline_ids: set[str],
            run_id: str,
        ) -> None:
            del status, final_messages, baseline_ids, run_id
            await self.sync_chat_summary(session_id)

        return await self.runs.start(
            agent=session.agent,
            session_id=session_id,
            message=message,
            pwd=pwd,
            user_message_id=user_message_id,
            on_terminal=on_terminal,
        )

    async def reset_thread(self, session_id: str) -> None:
        await self.runs.cancel_session(session_id)
        await self._checkpoints.delete_thread(session_id)
        await self._messages.delete_session(session_id)
        await self._db.update_chat_summary(
            session_id, title="New chat", preview="No session yet", message_count=0
        )

    async def delete(self, session_id: str) -> bool:
        await self.runs.cancel_session(session_id)
        session = self._sessions.pop(session_id, None)
        self._hydration_locks.pop(session_id, None)
        deleted = await self._db.delete_session(session_id)
        if not deleted and session is None:
            return False
        await self._messages.delete_session(session_id)
        await self._checkpoints.delete_thread(session_id)
        if session is not None:
            session.cleanup()
        return True


store = SessionStore()
