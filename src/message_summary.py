"""Derive chat title and preview text from LangGraph message history."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import messages_to_dict


def serialize_messages(messages: list) -> list[dict[str, Any]]:
    if not messages:
        return []
    if isinstance(messages[0], dict):
        return messages
    return messages_to_dict(messages)


def message_id(msg: dict[str, Any]) -> str | None:
    data = msg.get("data", msg)
    mid = data.get("id")
    return str(mid) if mid else None


def messages_after_baseline(
    messages: list, baseline_ids: set[str]
) -> list[dict[str, Any]]:
    """Messages written during one agent turn (excludes pre-turn checkpoint state)."""
    out: list[dict[str, Any]] = []
    for msg in serialize_messages(messages):
        mid = message_id(msg)
        if mid and mid in baseline_ids:
            continue
        out.append(msg)
    return out


def user_message_payload(content: str, message_id: str) -> dict[str, Any]:
    return {
        "type": "human",
        "data": {
            "content": content,
            "type": "human",
            "id": message_id,
        },
    }


def _truncate_text(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def first_user_text(messages: list) -> str:
    for msg in serialize_messages(messages):
        role = msg.get("type") or msg.get("role")
        if role not in {"human", "user"}:
            continue
        data = msg.get("data", msg)
        content = data.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            text = "".join(parts).strip()
            if text:
                return text
    return ""


def last_assistant_text(messages: list) -> str:
    for msg in reversed(serialize_messages(messages)):
        role = msg.get("type") or msg.get("role")
        if role in {"ai", "assistant"}:
            data = msg.get("data", msg)
            content = data.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                return "".join(parts)
    return ""


def title_from_messages(messages: list) -> str:
    title = first_user_text(messages)
    if not title:
        return "New chat"
    return _truncate_text(title, 48)


def preview_from_messages(messages: list) -> str:
    reply = last_assistant_text(messages)
    if not reply or not reply.strip():
        return "No session yet"
    return _truncate_text(reply.strip(), 72)


def summary_from_messages(messages: list) -> tuple[str, str, int]:
    return (
        title_from_messages(messages),
        preview_from_messages(messages),
        len(messages),
    )
