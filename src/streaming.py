"""Token-level streaming helpers for deepagents.

Uses LangGraph v2 stream chunks with ``stream_mode=["messages", "values"]`` so
callers get live LLM tokens *and* the final message list for conversation
history. See https://docs.langchain.com/oss/python/deepagents/streaming
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage, ToolMessageChunk

from session_persistence import get_async_runner

# ANSI styling (override via ``style=`` on ``stream_agent_turn`` for tests/TTY checks)
DEFAULT_STYLE = {
    "cyan": "\033[36m",
    "gray": "\033[90m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


def _source_label(ns: tuple[str, ...]) -> tuple[bool, str]:
    """Map a v2 namespace tuple to (is_subagent, display_label)."""
    for segment in ns:
        if segment.startswith("tools:"):
            return True, segment.split(":", 1)[-1]
    return False, "main"


def _token_text(token: Any) -> str:
    """Extract printable text from a streamed message chunk."""
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
    """Normalize LangChain usage_metadata to a plain dict."""
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
    """Rough output-token estimate while the model is still streaming."""
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


def _iter_agent_stream(
    agent: Any,
    input_messages: list,
    *,
    config: dict[str, Any] | None = None,
    **stream_kwargs: Any,
) -> Iterator[Any]:
    """Iterate LangGraph v2 stream chunks using ``astream`` (required for async MCP tools)."""

    async def _chunks() -> AsyncIterator[Any]:
        async for chunk in agent.astream(
            {"messages": input_messages},
            config=config,
            **stream_kwargs,
        ):
            yield chunk

    agen = _chunks()
    yield from get_async_runner().iter_async_generator(agen)


def iter_agent_turn_events(
    agent: Any,
    input_messages: list,
    *,
    thread_id: str | None = None,
    pwd: str | None = None,
    tool_preview_len: int = 500,
) -> Iterator[dict[str, Any]]:
    """Yield structured stream events for API/SSE consumers.

    When ``thread_id`` is set, ``input_messages`` should contain only the new
    user turn; prior history is loaded from the LangGraph checkpointer.

    Event types:
        source_start  - agent/subagent began producing output
        token         - AI text token
        tool_call_start / tool_call_args / tool_call_end
        tool_result   - tool output
        usage         - token usage update (per model call + turn cumulative)
        usage_estimate- live output-token estimate while model streams
        tool_running  - sandbox tool execution started (after model finishes)
        done          - final message list (serialized via caller)
    """
    final_messages = list(input_messages)
    current_source = ""
    in_tool_call = False
    current_tool_name: str | None = None
    step_stream_chars = 0
    turn_usage: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read": 0,
        "model_calls": 0,
    }

    def _finish_tool_call(source: str) -> Iterator[dict[str, Any]]:
        nonlocal in_tool_call, current_tool_name, step_stream_chars
        if not in_tool_call:
            return
        yield {"type": "tool_call_end"}
        if current_tool_name:
            yield {
                "type": "tool_running",
                "source": source,
                "name": current_tool_name,
            }
        in_tool_call = False
        current_tool_name = None
        step_stream_chars = 0

    stream_kwargs: dict[str, Any] = {
        "stream_mode": ["messages", "values"],
        "subgraphs": True,
        "version": "v2",
    }
    if pwd:
        stream_kwargs["context"] = {"pwd": pwd}
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None

    for chunk in _iter_agent_stream(
        agent,
        input_messages,
        config=config,
        **stream_kwargs,
    ):
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
            _accumulate_usage(turn_usage, step_usage)
            yield {"type": "usage", "turn": dict(turn_usage), "step": step_usage}
            if in_tool_call:
                yield from _finish_tool_call(source)
            else:
                step_stream_chars = 0

        if _is_tool_token(token):
            yield from _finish_tool_call(source)
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
                    yield from _finish_tool_call(source)
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
            yield from _finish_tool_call(source)
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
            yield {"type": "token", "source": source, "text": text}

    yield from _finish_tool_call(current_source or "main")

    done_usage = dict(turn_usage) if turn_usage["model_calls"] else None
    yield {"type": "done", "messages": final_messages, "usage": done_usage}


def stream_agent_turn(
    agent: Any,
    input_messages: list,
    *,
    thread_id: str | None = None,
    write: Callable[[str], None] | None = None,
    style: dict[str, str] | None = None,
    tool_preview_len: int = 500,
) -> list:
    """Run one agent turn with token-level streaming.

    When ``thread_id`` is set, pass only the new user message(s); history is
    restored from the LangGraph checkpointer. Otherwise ``input_messages`` is
    treated as the full in-memory history for this turn.
    """
    colors = DEFAULT_STYLE if style is None else style
    cyan = colors.get("cyan", "")
    gray = colors.get("gray", "")
    bold = colors.get("bold", "")
    reset = colors.get("reset", "")

    sink = write or (lambda text: (sys.stdout.write(text), sys.stdout.flush()))

    final_messages = list(input_messages)
    current_source = ""
    mid_line = False
    in_tool_call = False
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None

    def writeln(text: str = "") -> None:
        nonlocal mid_line
        sink(text + "\n")
        mid_line = False

    def write_inline(text: str) -> None:
        nonlocal mid_line
        sink(text)
        mid_line = bool(text) and not text.endswith("\n")

    for chunk in _iter_agent_stream(
        agent,
        input_messages,
        config=config,
        stream_mode=["messages", "values"],
        subgraphs=True,
        version="v2",
    ):
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

        # Tool results (check before tool_call_chunks — ToolMessage has no such attr)
        if _is_tool_token(token):
            if in_tool_call:
                write_inline(")")
                in_tool_call = False
            if mid_line:
                writeln()
            content = _token_text(token) or str(token.content)
            if len(content) > tool_preview_len:
                content = content[:tool_preview_len] + " …[truncated]"
            tool_name = getattr(token, "name", "tool")
            writeln(f"  {gray}← [{source}] {tool_name}: {content}{reset}")
            continue

        # Streaming tool invocations (name + args arrive in chunks)
        if tool_call_chunks:
            for tc in tool_call_chunks:
                if tc.get("name"):
                    if mid_line:
                        writeln()
                    if in_tool_call:
                        write_inline(")")
                    in_tool_call = True
                    write_inline(f"  {cyan}→ [{source}] calling {tc['name']}(")
                if tc.get("args"):
                    write_inline(tc["args"])
            continue

        # AI tokens (skip tool-call-only chunks and metadata-only chunks)
        if _is_ai_token(token) and not tool_call_chunks:
            text = _token_text(token)
            if not text:
                continue
            if in_tool_call:
                write_inline(")")
                in_tool_call = False
            if source != current_source:
                if mid_line:
                    writeln()
                if is_subagent:
                    writeln(f"\n{gray}--- [{source}] ---{reset}")
                else:
                    write_inline(f"\n{bold}Agent:{reset} ")
                current_source = source
            write_inline(text)

    if in_tool_call:
        write_inline(")")
    if mid_line:
        writeln()
    writeln()

    return final_messages
