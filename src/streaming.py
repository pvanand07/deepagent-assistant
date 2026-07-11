"""Async token-level streaming for deepagents.

Pure event production: ``iter_agent_turn_events`` is an async generator over
LangGraph v2 stream chunks. It knows nothing about HTTP, cancellation, or
persistence -- the run executor (see ``runs.py``) owns those concerns.
Cancellation support is provided as two helpers: ``capture_baseline_ids``
(call before the turn) and ``rollback_uncommitted_turn`` (call after a
cancelled/interrupted turn to restore the checkpoint).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    RemoveMessage,
    ToolMessage,
    ToolMessageChunk,
)


def _source_label(ns: tuple[str, ...]) -> tuple[bool, str]:
    """Map a v2 namespace tuple to (is_subagent, display_label)."""
    for segment in ns:
        if segment.startswith("tools:"):
            return True, segment.split(":", 1)[-1]
    return False, "main"


def _token_text(token: Any) -> str:
    text = getattr(token, "text", None)
    if text is not None:
        return str(text)
    content = getattr(token, "content", None)
    if isinstance(content, str):
        return content
    return ""


def _is_ai_token(token: Any) -> bool:
    return isinstance(token, (AIMessage, AIMessageChunk))


def _is_tool_token(token: Any) -> bool:
    return isinstance(token, (ToolMessage, ToolMessageChunk))


def _normalize_usage(usage_metadata: Any) -> dict[str, int] | None:
    if not usage_metadata:
        return None
    if isinstance(usage_metadata, dict):
        um = usage_metadata
    else:
        um = {
            "input_tokens": getattr(usage_metadata, "input_tokens", 0),
            "output_tokens": getattr(usage_metadata, "output_tokens", 0),
            "total_tokens": getattr(usage_metadata, "total_tokens", 0),
            "input_token_details": getattr(usage_metadata, "input_token_details", None),
        }
    details = um.get("input_token_details") or {}
    if not isinstance(details, dict):
        details = {}
    return {
        "input_tokens": int(um.get("input_tokens") or 0),
        "output_tokens": int(um.get("output_tokens") or 0),
        "total_tokens": int(um.get("total_tokens") or 0),
        "cache_read": int(details.get("cache_read") or 0),
    }


def _accumulate_usage(turn: dict[str, int], step: dict[str, int]) -> dict[str, int]:
    turn["input_tokens"] += step["input_tokens"]
    turn["output_tokens"] += step["output_tokens"]
    turn["total_tokens"] += step["total_tokens"]
    turn["cache_read"] += step["cache_read"]
    turn["model_calls"] += 1
    return turn


def _estimate_tokens(char_count: int) -> int:
    return max(1, char_count // 4) if char_count else 0


def _usage_estimate_event(
    *,
    turn_usage: dict[str, int],
    phase: str,
    chars: int,
    tool_name: str | None = None,
) -> dict[str, Any]:
    estimated = _estimate_tokens(chars)
    turn = dict(turn_usage)
    turn["estimated_output_tokens"] = estimated
    turn["streaming_chars"] = chars
    return {
        "type": "usage_estimate",
        "phase": phase,
        "tool_name": tool_name,
        "chars": chars,
        "estimated_output_tokens": estimated,
        "turn": turn,
    }


async def capture_baseline_ids(agent: Any, config: dict[str, Any]) -> set[str]:
    """Message ids present in the checkpoint before a turn starts."""
    try:
        state = await agent.aget_state(config)
    except Exception:
        return set()
    return {
        m.id
        for m in (state.values or {}).get("messages", [])
        if getattr(m, "id", None)
    }


async def rollback_uncommitted_turn(
    agent: Any,
    config: dict[str, Any],
    baseline_ids: set[str],
) -> None:
    """Strip messages written to the checkpoint after a cancelled turn started.

    Restores the thread to its state as of the last completed agent message:
    any human/AI/tool messages this turn wrote (including the triggering user
    message) are tombstoned via ``RemoveMessage`` so the next turn starts from
    a clean, un-truncated history.
    """
    state = await agent.aget_state(config)
    current = list((state.values or {}).get("messages") or [])
    stray = [m for m in current if getattr(m, "id", None) and m.id not in baseline_ids]
    if stray:
        await agent.aupdate_state(config, {"messages": [RemoveMessage(id=m.id) for m in stray]})


async def iter_agent_turn_events(
    agent: Any,
    input_messages: list,
    *,
    thread_id: str,
    pwd: str | None = None,
    tool_preview_len: int = 500,
) -> AsyncIterator[dict[str, Any]]:
    """Yield structured stream events for one agent turn.

    ``input_messages`` should contain only the new user turn; prior history is
    loaded from the LangGraph checkpointer via ``thread_id``.

    Event types:
        source_start  - agent/subagent began producing output
        token         - AI text token
        tool_call_start / tool_call_args / tool_call_end
        tool_result   - tool output
        usage         - token usage update (per model call + turn cumulative)
        usage_estimate- live output-token estimate while model streams
        tool_running  - sandbox tool execution started (after model finishes)
        done          - final message list (raw LangChain messages; caller serializes)
    """
    stream_kwargs: dict[str, Any] = {
        "stream_mode": ["messages", "values"],
        "subgraphs": True,
        "version": "v2",
    }
    if pwd:
        stream_kwargs["context"] = {"pwd": pwd}
    config = {"configurable": {"thread_id": thread_id}}

    final_messages: list = list(input_messages)
    current_source = ""
    in_tool_call = False
    current_tool_name: str | None = None
    step_stream_chars = 0
    turn_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read": 0,
        "model_calls": 0,
    }
    last_step_usage: dict[str, int] | None = None

    def _finish_tool_call(source: str) -> list[dict[str, Any]]:
        nonlocal in_tool_call, current_tool_name, step_stream_chars
        if not in_tool_call:
            return []
        events: list[dict[str, Any]] = [{"type": "tool_call_end"}]
        if current_tool_name:
            events.append(
                {"type": "tool_running", "source": source, "name": current_tool_name}
            )
        in_tool_call = False
        current_tool_name = None
        step_stream_chars = 0
        return events

    async for chunk in agent.astream({"messages": input_messages}, config=config, **stream_kwargs):
        chunk_type = chunk["type"]
        ns = chunk.get("ns", ())

        if chunk_type == "values":
            final_messages = chunk["data"]["messages"]
            continue

        if chunk_type != "messages":
            continue

        token, _metadata = chunk["data"]
        is_subagent, source = _source_label(ns)
        tool_call_chunks = getattr(token, "tool_call_chunks", None) or []

        step_usage = _normalize_usage(getattr(token, "usage_metadata", None))
        if step_usage:
            last_step_usage = step_usage
            _accumulate_usage(turn_usage, step_usage)
            yield {"type": "usage", "turn": dict(turn_usage), "step": step_usage}
            if in_tool_call:
                for event in _finish_tool_call(source):
                    yield event
            else:
                step_stream_chars = 0

        if _is_tool_token(token):
            for event in _finish_tool_call(source):
                yield event
            content = _token_text(token) or str(token.content)
            if len(content) > tool_preview_len:
                content = content[:tool_preview_len] + " …[truncated]"
            yield {
                "type": "tool_result",
                "source": source,
                "name": getattr(token, "name", "tool"),
                "content": content,
            }
            continue

        if tool_call_chunks:
            for tc in tool_call_chunks:
                if tc.get("name"):
                    for event in _finish_tool_call(source):
                        yield event
                    in_tool_call = True
                    current_tool_name = tc["name"]
                    step_stream_chars = 0
                    yield {
                        "type": "tool_call_start",
                        "source": source,
                        "name": tc["name"],
                    }
                if tc.get("args"):
                    args_chunk = tc["args"]
                    yield {"type": "tool_call_args", "args": args_chunk}
                    step_stream_chars += len(args_chunk)
                    yield _usage_estimate_event(
                        turn_usage=turn_usage,
                        phase="tool_args",
                        chars=step_stream_chars,
                        tool_name=current_tool_name,
                    )
            continue

        if _is_ai_token(token) and not tool_call_chunks:
            text = _token_text(token)
            if not text:
                continue
            for event in _finish_tool_call(source):
                yield event
            step_stream_chars += len(text)
            yield _usage_estimate_event(
                turn_usage=turn_usage,
                phase="text",
                chars=step_stream_chars,
            )
            if source != current_source:
                yield {
                    "type": "source_start",
                    "source": source,
                    "is_subagent": is_subagent,
                }
                current_source = source
            yield {
                "type": "token",
                "source": source,
                "text": text,
                "is_subagent": is_subagent,
            }

    for event in _finish_tool_call(current_source or "main"):
        yield event

    done_usage = dict(turn_usage) if turn_usage["model_calls"] else None
    yield {
        "type": "done",
        "messages": final_messages,
        "usage": done_usage,
        "step_usage": last_step_usage,
    }
