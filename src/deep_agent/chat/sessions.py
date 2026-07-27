"""Async session store: agent hydration, run orchestration, persistence glue."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deep_agent.chat.messages import messages_after_baseline, summary_from_messages
from deep_agent.integrations.model_provider import default_model_for_provider
from deep_agent.chat.runs import RunManager
from deep_agent.persistence.database import (
    AppDB,
    CheckpointManager,
    MessageDB,
    RunRecord,
    SessionMeta,
    thread_config,
)
from deep_agent.sandbox.config import default_network, default_workdir
from deep_agent.chat.streaming import rollback_uncommitted_turn


@dataclass
class AgentSession:
    id: str
    agent: Any
    sandbox: Any
    model: str
    mcp_servers: list[str] = field(default_factory=list)
    mcp_tool_names: list[str] = field(default_factory=list)
    mcp_failed: list[dict[str, str]] = field(default_factory=list)
    subagent_names: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def workdir(self) -> Path:
        """Current shared workspace used by this session's sandbox."""
        return Path(getattr(self.sandbox, "_workdir"))

    def cleanup(self) -> None:
        """Per-session cleanup. Shared Bubblewrap sandbox is not destroyed here."""
        cleanup = getattr(self.sandbox, "cleanup", None)
        if callable(cleanup):
            cleanup()


@dataclass
class _McpRegistry:
    """Process-wide MCP tool cache (partial-degrade aware)."""

    tools: list = field(default_factory=list)
    servers: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)


class SessionStore:
    """Owns session lifecycle. All methods run on the app event loop.

    Concurrency model:
    - Hydration (agent build) is guarded per session id, so two simultaneous
      requests never build the same agent twice.
    - One run at a time per session (enforced by ``RunManager``); runs on
      different sessions execute in parallel, bounded by a global semaphore.
    - MCP tools are loaded once per process and shared across all agents.
    - All sessions share one Bubblewrap backend from ``SandboxManager``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._hydration_locks: dict[str, asyncio.Lock] = {}
        self._db: AppDB | None = None
        self._messages: MessageDB | None = None
        self._checkpoints: CheckpointManager | None = None
        self.runs: RunManager | None = None
        self._mcp_cache: _McpRegistry | None = None
        self._mcp_lock = asyncio.Lock()

    async def startup(self) -> None:
        self._db = await AppDB.get()
        self._messages = await MessageDB.get()
        self._checkpoints = await CheckpointManager.get()
        await self._db.mark_interrupted_runs()
        await self._migrate_legacy_sessions()
        self.runs = RunManager(self._db, self._messages)

    async def _migrate_legacy_sessions(self) -> None:
        """Import pre-AppDB ``sessions.json`` once, retaining session/thread IDs."""
        from deep_agent.persistence.session_persistence import sessions_meta_path

        path = sessions_meta_path()
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            legacy = raw.get("sessions") or {}
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(legacy, dict):
            return
        for session_id, item in legacy.items():
            if not isinstance(item, dict) or await self._db.get_session(str(session_id)):
                continue
            now = time.time()
            meta = SessionMeta(
                id=str(item.get("id") or session_id),
                model=str(item.get("model") or self._resolved_model(None)),
                network=bool(item.get("network", default_network())),
                workdir=item.get("workdir") or str(default_workdir()),
                with_subagents=bool(item.get("with_subagents", True)),
                created_at=float(item.get("created_at") or now),
                updated_at=float(item.get("updated_at") or now),
                title=str(item.get("title") or "New chat"),
                preview=str(item.get("preview") or "No session yet"),
                message_count=int(item.get("message_count") or 0),
            )
            await self._db.upsert_session(meta)

    async def close(self) -> None:
        if self.runs is not None:
            await self.runs.cancel_all()
        for session in list(self._sessions.values()):
            session.cleanup()
        self._sessions.clear()
        await self._close_mcp()
        if self._checkpoints is not None:
            await self._checkpoints.close()
        if self._messages is not None:
            await self._messages.close()
        if self._db is not None:
            await self._db.close()

    def _resolved_model(self, model: str | None) -> str:
        return model or os.environ.get("OPENROUTER_MODEL") or default_model_for_provider()

    def is_agent_ready(self, session_id: str) -> bool:
        return session_id in self._sessions

    def get_cached(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    async def _close_mcp(self) -> None:
        """Drop cached MCP tools/registry (best-effort teardown)."""
        async with self._mcp_lock:
            self._mcp_cache = None

    def invalidate_runtime(self) -> None:
        """Drop cached agents and MCP tools so the next chat rebuilds them.

        Does not cancel in-flight runs; those keep their existing agent until done.
        """
        for session in list(self._sessions.values()):
            session.cleanup()
        self._sessions.clear()
        self._mcp_cache = None

    async def _get_mcp(self) -> _McpRegistry:
        from deep_agent.integrations.mcp import aload_mcp_tools

        async with self._mcp_lock:
            if self._mcp_cache is None:
                tools, servers, failed = await aload_mcp_tools()
                self._mcp_cache = _McpRegistry(
                    tools=tools, servers=servers, failed=failed
                )
            return self._mcp_cache

    async def _build_session(self, meta: SessionMeta) -> AgentSession:
        from deep_agent.agent_factory import build_agent
        from deep_agent.sandbox.manager import get_manager

        mcp = await self._get_mcp()
        manager = get_manager()
        sandbox = manager.backend if manager.healthy else None
        agent, sandbox, mcp_meta = await asyncio.to_thread(
            build_agent,
            model_name=meta.model,
            with_subagents=meta.with_subagents,
            mcp_tools=mcp.tools,
            mcp_servers=mcp.servers,
            mcp_failed=mcp.failed,
            checkpointer=self._checkpoints.checkpointer,
            sandbox=sandbox,
            sandbox_available=manager.healthy,
        )
        return AgentSession(
            id=meta.id,
            agent=agent,
            sandbox=sandbox,
            model=meta.model,
            mcp_servers=mcp_meta["servers"],
            mcp_tool_names=mcp_meta["tool_names"],
            mcp_failed=list(mcp_meta.get("failed") or mcp.failed),
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
    ) -> SessionMeta:
        """Create session metadata only — agent hydrates on first chat."""
        now = time.time()
        meta = SessionMeta(
            id=uuid.uuid4().hex,
            model=self._resolved_model(model),
            network=default_network(),
            workdir=str(default_workdir()),
            with_subagents=with_subagents,
            created_at=now,
            updated_at=now,
        )
        await self._db.upsert_session(meta)
        return meta

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

    async def set_model(
        self, session_id: str, model: str, *, as_default: bool = True
    ) -> SessionMeta:
        """Switch the session model; rebuilds the agent on the next chat turn.

        Also updates the app default model so new sessions inherit the pick.
        Refuses while a run is in flight for this session.
        """
        from deep_agent.chat.runs import RunConflictError
        from deep_agent.settings.store import (
            apply_runtime_env,
            find_platform_for_model,
            load_settings,
            save_settings,
        )

        mid = (model or "").strip()
        if not mid:
            raise ValueError("model is required")
        meta = await self._db.get_session(session_id)
        if meta is None:
            raise KeyError(session_id)
        if self.runs is not None:
            active = self.runs.active_run_id(session_id)
            if active:
                raise RunConflictError(active)

        meta.model = mid
        meta.updated_at = time.time()
        await self._db.upsert_session(meta)

        cached = self._sessions.pop(session_id, None)
        if cached is not None:
            cached.cleanup()

        if as_default:
            cfg = load_settings()
            cfg["default_model"] = mid
            owner = find_platform_for_model(mid, cfg)
            if owner:
                cfg["active_platform_id"] = owner["id"]
            save_settings(cfg)
            apply_runtime_env(cfg)

        return meta

    async def get_run(self, run_id: str) -> RunRecord | None:
        return await self._db.get_run(run_id)

    async def list_all(self) -> list[SessionMeta]:
        return await self._db.list_sessions()

    async def read_messages(self, session_id: str) -> list[Any]:
        messages = await self._messages.list_messages(session_id)
        if messages:
            return messages
        return await self._backfill_messages_from_runs(session_id)

    async def message_count(self, session_id: str) -> int:
        return await self._messages.count_messages(session_id)

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
            usage: dict | None = None,
            step_usage: dict | None = None,
        ) -> None:
            del final_messages, baseline_ids, run_id
            await self.sync_chat_summary(session_id)
            await self._db.update_last_usage(
                session_id,
                usage=usage if status == "done" else None,
                step_usage=step_usage if status == "done" else None,
            )

        return await self.runs.start(
            agent=session.agent,
            session_id=session_id,
            message=message,
            pwd=pwd,
            user_message_id=user_message_id,
            on_terminal=on_terminal,
            mcp_failed=session.mcp_failed,
        )

    async def reset_thread(self, session_id: str) -> None:
        await self.runs.cancel_session(session_id)
        await self._checkpoints.delete_thread(session_id)
        await self._messages.delete_session(session_id)
        await self._db.update_chat_summary(
            session_id, title="New chat", preview="No session yet", message_count=0
        )
        await self._db.update_last_usage(session_id)

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
