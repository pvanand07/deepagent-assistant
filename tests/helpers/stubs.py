"""Lightweight stand-ins for agent hydration in end-to-end tests."""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from deep_agent.chat.sessions import AgentSession, SessionStore
from deep_agent.persistence.database import SessionMeta


@dataclass
class StubSandbox:
    _workdir: Path
    id: str = "stub-sandbox"
    network: bool = False

    def cleanup(self) -> None:
        shutil.rmtree(self._workdir, ignore_errors=True)


@dataclass
class StubAgent:
    """Minimal agent surface used by capture/rollback helpers."""

    messages: list[Any] = field(default_factory=list)

    async def aget_state(self, config: dict[str, Any]) -> Any:
        class _State:
            def __init__(self, values: dict[str, Any]) -> None:
                self.values = values

        return _State({"messages": list(self.messages)})

    async def aupdate_state(self, config: dict[str, Any], update: dict[str, Any]) -> None:
        removals = {m.id for m in update.get("messages", []) if hasattr(m, "id")}
        if removals:
            self.messages = [m for m in self.messages if getattr(m, "id", None) not in removals]


async def stub_build_session(store: SessionStore, meta: SessionMeta) -> AgentSession:
    workdir = Path(meta.workdir or "/tmp/deepagent-test-workspace")
    workdir.mkdir(parents=True, exist_ok=True)
    return AgentSession(
        id=meta.id,
        agent=StubAgent(),
        sandbox=StubSandbox(workdir),
        model=meta.model,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
    )


async def success_turn(
    agent: Any,
    input_messages: list,
    *,
    thread_id: str,
    pwd: str | None = None,
    tool_preview_len: int = 500,
) -> AsyncIterator[dict[str, Any]]:
    del agent, thread_id, pwd, tool_preview_len
    user_msg = input_messages[0] if input_messages else {}
    user_text = user_msg.get("content", "") if isinstance(user_msg, dict) else ""
    user_id = user_msg.get("id", "user-test-1") if isinstance(user_msg, dict) else "user-test-1"
    yield {"type": "source_start", "source": "main", "is_subagent": False}
    for piece in ("Hello", " ", "from", " ", "tests"):
        yield {"type": "token", "source": "main", "text": piece, "is_subagent": False}
    messages = [
        HumanMessage(content=user_text, id=user_id),
        AIMessage(content="Hello from tests", id="ai-test-1"),
    ]
    yield {"type": "done", "messages": messages, "usage": None}


async def token_burst_turn(
    agent: Any,
    input_messages: list,
    *,
    thread_id: str,
    pwd: str | None = None,
    tool_preview_len: int = 500,
) -> AsyncIterator[dict[str, Any]]:
    del agent, thread_id, pwd, tool_preview_len
    user_text = input_messages[0]["content"] if input_messages else ""
    yield {"type": "source_start", "source": "main", "is_subagent": False}
    for i in range(20):
        yield {"type": "token", "source": "main", "text": f"t{i}", "is_subagent": False}
    messages = [
        HumanMessage(content=user_text, id="user-burst-1"),
        AIMessage(content="".join(f"t{i}" for i in range(20)), id="ai-burst-1"),
    ]
    yield {"type": "done", "messages": messages, "usage": None}


async def slow_turn(
    agent: Any,
    input_messages: list,
    *,
    thread_id: str,
    pwd: str | None = None,
    tool_preview_len: int = 500,
) -> AsyncIterator[dict[str, Any]]:
    del agent, thread_id, pwd, tool_preview_len
    user_text = input_messages[0]["content"] if input_messages else ""
    yield {"type": "source_start", "source": "main", "is_subagent": False}
    yield {"type": "token", "source": "main", "text": "slow", "is_subagent": False}
    gate = asyncio.Event()
    try:
        await gate.wait()
    except asyncio.CancelledError:
        raise
    messages = [
        HumanMessage(content=user_text, id="user-slow-1"),
        AIMessage(content="should not finish", id="ai-slow-1"),
    ]
    yield {"type": "done", "messages": messages, "usage": None}
