"""Background run execution, durable event log, and stream fan-out.

Core idea: a chat message creates a *run*. The run executes as an
``asyncio.Task`` whose lifetime is independent of any HTTP connection --
clients merely *observe* runs through the event log:

- Every event gets a monotonic ``seq``. Live subscribers receive raw events
  through per-subscriber ``asyncio.Queue``s.
- Events are persisted append-only to SQLite so a client can reconnect and
  replay from any cursor. High-volume ``token`` / ``tool_call_args`` events
  are coalesced before persisting (one row per contiguous burst, carrying the
  burst's last ``seq``), and ``usage_estimate`` events are live-only.
- Cancellation is native ``task.cancel()``; the executor rolls the LangGraph
  checkpoint back to its pre-turn baseline and emits a ``cancelled`` event.
- Every run terminates the log with exactly one of ``done | cancelled | error``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from message_summary import (
    last_assistant_text,
    messages_after_baseline,
    serialize_messages,
    user_message_payload,
)
from session_persistence import AppDB, MessageDB, RunRecord, thread_config
from streaming import (
    capture_baseline_ids,
    iter_agent_turn_events,
    rollback_uncommitted_turn,
)
from sandbox_manager import current_run_id, current_session_id

# Live-only events: fanned out to connected subscribers, never persisted.
_EPHEMERAL_TYPES = {"usage_estimate"}

TERMINAL_TYPES = {"done", "cancelled", "error"}


def _max_concurrent_runs() -> int:
    try:
        return max(1, int(os.environ.get("DEEPAGENT_MAX_CONCURRENT_RUNS", "8")))
    except ValueError:
        return 8


class RunConflictError(RuntimeError):
    """A run is already in flight for this session."""

    def __init__(self, active_run_id: str) -> None:
        super().__init__(f"Run {active_run_id} already active for session")
        self.active_run_id = active_run_id


@dataclass
class _RunHandle:
    run_id: str
    session_id: str
    task: asyncio.Task | None = None
    closed: bool = False
    seq: int = 0
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    # Pending coalesced event awaiting flush (token burst or tool_call_args burst).
    pending: dict[str, Any] | None = None


# on_terminal(status, final_messages, *, baseline_ids, run_id, usage, step_usage)
TerminalCallback = Callable[..., Awaitable[None]]


class RunManager:
    def __init__(self, db: AppDB, messages: MessageDB) -> None:
        self._db = db
        self._messages = messages
        self._handles: dict[str, _RunHandle] = {}
        self._active_by_session: dict[str, str] = {}
        self._sem = asyncio.Semaphore(_max_concurrent_runs())

    # -- public API -------------------------------------------------------

    def active_run_id(self, session_id: str) -> str | None:
        return self._active_by_session.get(session_id)

    async def start(
        self,
        *,
        agent: Any,
        session_id: str,
        message: str,
        pwd: str | None,
        user_message_id: str,
        on_terminal: TerminalCallback,
    ) -> RunRecord:
        existing = self._active_by_session.get(session_id)
        if existing is not None:
            raise RunConflictError(existing)

        run_id = uuid.uuid4().hex
        record = await self._db.insert_run(run_id, session_id)
        await self._messages.append(
            session_id,
            user_message_payload(message, user_message_id),
            run_id=run_id,
            message_id=user_message_id,
        )
        handle = _RunHandle(run_id=run_id, session_id=session_id)
        self._handles[run_id] = handle
        self._active_by_session[session_id] = run_id
        handle.task = asyncio.create_task(
            self._execute(
                handle,
                agent,
                message,
                pwd,
                user_message_id,
                on_terminal,
            ),
            name=f"run-{run_id}",
        )
        return record

    async def cancel(self, run_id: str) -> bool:
        """Request cooperative cancellation of an in-flight run."""
        handle = self._handles.get(run_id)
        if handle is None or handle.task is None or handle.task.done():
            return False
        return handle.task.cancel()

    async def cancel_session(self, session_id: str) -> bool:
        run_id = self._active_by_session.get(session_id)
        if run_id is None:
            return False
        return await self.cancel(run_id)

    async def cancel_all(self) -> None:
        tasks = [h.task for h in self._handles.values() if h.task and not h.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def subscribe(self, run_id: str, after_seq: int) -> AsyncIterator[dict[str, Any]]:
        """Replay persisted events after ``after_seq``, then tail live events.

        Terminates after yielding a terminal event, or immediately after
        replay if the run is no longer live (its terminal event is persisted,
        so replay always ends with it for finished runs).
        """
        handle = self._handles.get(run_id)
        queue: asyncio.Queue | None = None
        if handle is not None and not handle.closed:
            queue = asyncio.Queue()
            handle.subscribers.append(queue)
        try:
            last = after_seq
            for event in await self._db.read_run_events(run_id, after_seq):
                yield event
                last = max(last, int(event.get("seq") or 0))
                if event.get("type") in TERMINAL_TYPES:
                    return
            if queue is None:
                return
            while True:
                item = await queue.get()
                if item is None:  # run closed
                    return
                if int(item.get("seq") or 0) <= last:
                    continue  # already delivered during replay
                yield item
                if item.get("type") in TERMINAL_TYPES:
                    return
        finally:
            if queue is not None and handle is not None:
                try:
                    handle.subscribers.remove(queue)
                except ValueError:
                    pass

    # -- event log --------------------------------------------------------

    async def _emit(self, handle: _RunHandle, event: dict[str, Any]) -> None:
        handle.seq += 1
        event = {**event, "seq": handle.seq}

        # Live fan-out first (raw, uncoalesced -- smooth streaming for viewers).
        for queue in list(handle.subscribers):
            queue.put_nowait(event)

        if event["type"] in _EPHEMERAL_TYPES:
            return

        # Coalesce high-volume events for persistence.
        coalesce_key: str | None = None
        if event["type"] == "token":
            coalesce_key = f"token:{event.get('source')}"
        elif event["type"] == "tool_call_args":
            coalesce_key = "tool_call_args"

        if coalesce_key is not None:
            pending = handle.pending
            if pending is not None and pending.get("_key") == coalesce_key:
                if event["type"] == "token":
                    pending["text"] += event["text"]
                else:
                    pending["args"] += event["args"]
                pending["seq"] = event["seq"]
            else:
                await self._flush_pending(handle)
                handle.pending = {**event, "_key": coalesce_key}
            return

        await self._flush_pending(handle)
        await self._persist(handle, event)

    async def _flush_pending(self, handle: _RunHandle) -> None:
        if handle.pending is None:
            return
        event = {k: v for k, v in handle.pending.items() if k != "_key"}
        handle.pending = None
        await self._persist(handle, event)

    async def _persist(self, handle: _RunHandle, event: dict[str, Any]) -> None:
        await self._db.append_run_event(
            handle.run_id, int(event["seq"]), str(event["type"]), json.dumps(event)
        )

    # -- executor ----------------------------------------------------------

    async def _execute(
        self,
        handle: _RunHandle,
        agent: Any,
        message: str,
        pwd: str | None,
        user_message_id: str,
        on_terminal: TerminalCallback,
    ) -> None:
        config = thread_config(handle.session_id)
        baseline_ids: set[str] = set()
        status = "error"
        error: str | None = None
        final_messages: list | None = None
        turn_usage: dict[str, Any] | None = None
        step_usage: dict[str, Any] | None = None
        session_token = current_session_id.set(handle.session_id)
        run_token = current_run_id.set(handle.run_id)

        try:
            async with self._sem:
                await self._db.set_run_status(handle.run_id, "running")
                baseline_ids = await capture_baseline_ids(agent, config)
                await self._db.set_run_baseline(handle.run_id, baseline_ids)

                user_turn = [
                    {"role": "user", "content": message, "id": user_message_id}
                ]
                async for event in iter_agent_turn_events(
                    agent,
                    user_turn,
                    thread_id=handle.session_id,
                    pwd=pwd,
                ):
                    if event["type"] == "done":
                        final_messages = event["messages"]
                        turn_usage = event.get("usage")
                        step_usage = event.get("step_usage")
                        turn_messages = messages_after_baseline(
                            final_messages, baseline_ids
                        )
                        await self._messages.append_many(
                            handle.session_id, turn_messages, run_id=handle.run_id
                        )
                        event = {
                            "type": "done",
                            "messages": serialize_messages(final_messages),
                            "reply": last_assistant_text(final_messages),
                            "usage": turn_usage,
                            "step_usage": step_usage,
                        }
                    await self._emit(handle, event)
                status = "done"
        except asyncio.CancelledError:
            # Swallow the cancellation: rollback + bookkeeping must complete.
            status = "cancelled"
            try:
                await asyncio.shield(rollback_uncommitted_turn(agent, config, baseline_ids))
            except Exception:
                pass
            try:
                await self._emit(handle, {"type": "cancelled"})
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 -- terminal event must always be emitted
            status = "error"
            error = str(exc)
            try:
                await self._emit(handle, {"type": "error", "error": error})
            except Exception:
                pass
        finally:
            current_session_id.reset(session_token)
            current_run_id.reset(run_token)
            try:
                await self._flush_pending(handle)
            except Exception:
                pass
            try:
                await self._db.set_run_status(handle.run_id, status, error=error)
            except Exception:
                pass
            handle.closed = True
            for queue in list(handle.subscribers):
                queue.put_nowait(None)
            if self._active_by_session.get(handle.session_id) == handle.run_id:
                del self._active_by_session[handle.session_id]
            self._handles.pop(handle.run_id, None)
            try:
                await on_terminal(
                    status,
                    final_messages,
                    baseline_ids=baseline_ids,
                    run_id=handle.run_id,
                    usage=turn_usage,
                    step_usage=step_usage,
                )
            except Exception:
                pass
