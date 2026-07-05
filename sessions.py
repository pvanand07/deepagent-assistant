"""In-memory session store for API clients."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent import _default_network, _default_workdir, build_agent
from bubblewrap_sandbox import BubblewrapSandbox
from openrouter_model import DEFAULT_MODEL


@dataclass
class AgentSession:
    id: str
    agent: Any
    sandbox: BubblewrapSandbox
    model: str
    mcp_servers: list[str] = field(default_factory=list)
    mcp_tool_names: list[str] = field(default_factory=list)
    history: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def cleanup(self) -> None:
        self.sandbox.cleanup()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()

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
        agent, sandbox, mcp_meta = build_agent(
            model_name=model,
            network=resolved_network,
            workdir=resolved_workdir,
            with_subagents=with_subagents,
        )
        resolved_model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
        session = AgentSession(
            id=uuid.uuid4().hex,
            agent=agent,
            sandbox=sandbox,
            model=resolved_model,
            mcp_servers=mcp_meta["servers"],
            mcp_tool_names=mcp_meta["tool_names"],
        )
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> AgentSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.cleanup()
        return True

    def cleanup_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.cleanup()


store = SessionStore()
