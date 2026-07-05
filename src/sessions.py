"""Session store with LangGraph SQLite checkpoint persistence."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent import _default_network, _default_workdir, build_agent
from bubblewrap_sandbox import BubblewrapSandbox
from message_summary import summary_from_messages
from openrouter_model import DEFAULT_MODEL
from session_persistence import (
    CheckpointManager,
    SessionMeta,
    get_async_runner,
    metadata_store,
    thread_config,
)


@dataclass
class AgentSession:
    id: str
    agent: Any
    sandbox: BubblewrapSandbox
    model: str
    mcp_servers: list[str] = field(default_factory=list)
    mcp_tool_names: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def touch(self) -> None:
        self.updated_at = time.time()
        metadata_store.touch(self.id)

    def cleanup(self) -> None:
        self.sandbox.cleanup()

    def get_messages(self) -> list[Any]:
        async def _read() -> list[Any]:
            state = await self.agent.aget_state(thread_config(self.id))
            return list((state.values or {}).get("messages") or [])

        return get_async_runner().run(_read())


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        self._metadata = metadata_store
        self._checkpoints = CheckpointManager.get()

    def _resolved_model(self, model: str | None) -> str:
        return model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)

    def _build_session(self, meta: SessionMeta) -> AgentSession:
        agent, sandbox, mcp_meta = build_agent(
            model_name=meta.model,
            network=meta.network,
            workdir=meta.workdir,
            with_subagents=meta.with_subagents,
            checkpointer=self._checkpoints.checkpointer,
        )
        return AgentSession(
            id=meta.id,
            agent=agent,
            sandbox=sandbox,
            model=meta.model,
            mcp_servers=mcp_meta["servers"],
            mcp_tool_names=mcp_meta["tool_names"],
            created_at=meta.created_at,
            updated_at=meta.updated_at,
        )

    def create(
        self,
        *,
        model: str | None = None,
        network: bool | None = None,
        workdir: str | None = None,
        with_subagents: bool = True,
    ) -> AgentSession:
        resolved_workdir = workdir or _default_workdir()
        resolved_network = network if network is not None else _default_network()
        resolved_model = self._resolved_model(model)
        now = time.time()
        meta = SessionMeta(
            id=uuid.uuid4().hex,
            model=resolved_model,
            network=resolved_network,
            workdir=resolved_workdir,
            with_subagents=with_subagents,
            created_at=now,
            updated_at=now,
        )
        session = self._build_session(meta)
        self._metadata.upsert(meta)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str, *, hydrate: bool = True) -> AgentSession | None:
        with self._lock:
            cached = self._sessions.get(session_id)
        if cached is not None:
            return cached
        if not hydrate:
            return None
        meta = self._metadata.get(session_id)
        if meta is None:
            return None
        session = self._build_session(meta)
        with self._lock:
            self._sessions[session_id] = session
        return session

    def list_all(self) -> list[SessionMeta]:
        return self._metadata.list_all()

    def read_messages(self, session_id: str) -> list[Any]:
        with self._lock:
            cached = self._sessions.get(session_id)
        if cached is not None:
            return cached.get_messages()
        session = self.get(session_id)
        if session is None:
            return []
        return session.get_messages()

    def sync_chat_summary(
        self,
        session_id: str,
        messages: list[Any] | None = None,
    ) -> None:
        if messages is None:
            messages = self.read_messages(session_id)
        title, preview, count = summary_from_messages(messages)
        self._metadata.update_chat_summary(
            session_id,
            title=title,
            preview=preview,
            message_count=count,
        )

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not self._metadata.delete(session_id):
            if session is None:
                return False
        self._checkpoints.delete_thread(session_id)
        if session is not None and session.sandbox is not None:
            session.cleanup()
        return True

    def reset_thread(self, session_id: str) -> None:
        self._checkpoints.delete_thread(session_id)
        self._metadata.update_chat_summary(
            session_id,
            title="New chat",
            preview="No session yet",
            message_count=0,
        )

    def cleanup_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            if session.sandbox is not None:
                session.cleanup()

    def close(self) -> None:
        self.cleanup_all()
        self._checkpoints.close()
        get_async_runner().close()


store = SessionStore()
