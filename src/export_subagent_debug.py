"""Export subagent checkpoint runs to debug JSON (truncates large tool results)."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import messages_to_dict
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

MAX_TOOL_CONTENT = 2000
MAX_AI_CONTENT = 4000
MAX_ARG_LEN = 2000

SESSIONS = [
    {
        "id": "467ad3d2c0664578a93db82a0b40b19e",
        "label": "programming-languages-research",
        "user_query": "run a sample task with saubagent",
    },
    {
        "id": "f839c77e363745baab907e22000044fe",
        "label": "lizmotors-research",
        "user_query": "perform research on lizmotors use subagent",
    },
]


def _truncate(value: Any, limit: int) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[: limit - 1] + f"\n… [truncated, {len(value)} chars total]"
    if isinstance(value, list):
        return [_truncate(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _truncate(v, limit) for k, v in value.items()}
    text = str(value)
    if len(text) <= limit:
        return value
    return text[: limit - 1] + f"… [truncated, {len(text)} chars total]"


def _sanitize_message(msg: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(msg, default=str))
    data = out.get("data", out)
    role = out.get("type") or data.get("type")

    if role == "tool":
        content = data.get("content")
        if isinstance(content, str):
            data["content"] = _truncate(content, MAX_TOOL_CONTENT)
        elif content is not None:
            data["content"] = _truncate(json.dumps(content, default=str), MAX_TOOL_CONTENT)

    if role == "ai":
        content = data.get("content")
        if isinstance(content, str) and len(content) > MAX_AI_CONTENT:
            data["content"] = _truncate(content, MAX_AI_CONTENT)
        tool_calls = data.get("tool_calls") or []
        for tc in tool_calls:
            args = tc.get("args")
            if args is not None:
                serialized = json.dumps(args, default=str)
                if len(serialized) > MAX_ARG_LEN:
                    tc["args"] = _truncate(serialized, MAX_ARG_LEN)

    return out


def _serialize_messages(messages: list) -> list[dict[str, Any]]:
    if not messages:
        return []
    if isinstance(messages[0], dict):
        raw = messages
    else:
        raw = messages_to_dict(messages)
    return [_sanitize_message(m) for m in raw]


def _tool_call_rows(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        data = msg.get("data", msg)
        role = msg.get("type") or data.get("type")
        if role == "ai":
            for tc in data.get("tool_calls") or []:
                rows.append(
                    {
                        "message_index": i,
                        "name": tc.get("name"),
                        "id": tc.get("id"),
                        "args": _truncate(tc.get("args"), MAX_ARG_LEN),
                    }
                )
        elif role == "tool":
            content = data.get("content", "")
            rows.append(
                {
                    "message_index": i,
                    "name": data.get("name"),
                    "tool_call_id": data.get("tool_call_id"),
                    "status": data.get("status"),
                    "content_chars": len(str(content)),
                    "content_preview": _truncate(str(content), 300),
                }
            )
    return rows


def _messages_from_blob(serde: JsonPlusSerializer, blob: bytes) -> list:
    data = serde.loads_typed(("msgpack", blob))
    return list((data.get("channel_values") or {}).get("messages") or [])


def _best_main_messages(
    conn: sqlite3.Connection, serde: JsonPlusSerializer, thread_id: str
) -> list:
    """Latest root checkpoint may be empty; pick the richest main-thread snapshot."""
    rows = conn.execute(
        """
        SELECT checkpoint
        FROM checkpoints
        WHERE thread_id = ? AND checkpoint_ns = ''
        ORDER BY checkpoint_id
        """,
        (thread_id,),
    ).fetchall()
    best: list = []
    for (blob,) in rows:
        messages = _messages_from_blob(serde, blob)
        if len(messages) >= len(best):
            best = messages
    return best


def _fetch_main_messages_from_api(session_id: str) -> list[dict[str, Any]] | None:
    try:
        import urllib.request

        url = f"http://127.0.0.1:8010/api/sessions/{session_id}/messages"
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("messages") or []
    except Exception:
        return None


def _latest_checkpoint_by_ns(
    conn: sqlite3.Connection, thread_id: str
) -> dict[str, bytes]:
    rows = conn.execute(
        """
        SELECT checkpoint_ns, checkpoint
        FROM checkpoints
        WHERE thread_id = ?
        ORDER BY checkpoint_id
        """,
        (thread_id,),
    ).fetchall()
    by_ns: dict[str, bytes] = {}
    for ns, blob in rows:
        by_ns[ns or "main"] = blob
    return by_ns


def export_session(
    *,
    conn: sqlite3.Connection,
    serde: JsonPlusSerializer,
    session_id: str,
    label: str,
    user_query: str,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    by_ns = _latest_checkpoint_by_ns(conn, session_id)
    subagent_ns = [ns for ns in by_ns if ns.startswith("tools:")]

    main_messages: list[dict[str, Any]] = []
    api_messages = _fetch_main_messages_from_api(session_id)
    if api_messages:
        main_messages = [_sanitize_message(m) for m in api_messages]
    else:
        checkpoint_messages = _best_main_messages(conn, serde, session_id)
        main_messages = _serialize_messages(checkpoint_messages)

    subagent_runs: list[dict[str, Any]] = []
    for ns in subagent_ns:
        data = serde.loads_typed(("msgpack", by_ns[ns]))
        messages = _serialize_messages(
            (data.get("channel_values") or {}).get("messages") or []
        )
        tool_rows = _tool_call_rows(messages)
        ai_tool_calls = [
            r for r in tool_rows if "message_index" in r and "args" in r
        ]
        counts = Counter(r["name"] for r in ai_tool_calls if r.get("name"))

        subagent_runs.append(
            {
                "namespace": ns,
                "message_count": len(messages),
                "tool_call_count": len(ai_tool_calls),
                "tool_call_summary": dict(counts),
                "messages": messages,
                "tool_timeline": tool_rows,
            }
        )

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "label": label,
        "user_query": user_query,
        "session_meta": meta,
        "truncation_limits": {
            "tool_content_max_chars": MAX_TOOL_CONTENT,
            "ai_content_max_chars": MAX_AI_CONTENT,
            "tool_args_max_chars": MAX_ARG_LEN,
        },
        "main_thread": {
            "message_count": len(main_messages),
            "messages": main_messages,
            "tool_timeline": _tool_call_rows(main_messages),
        },
        "subagent_runs": subagent_runs,
    }


def main() -> int:
    data_dir = Path(
        __import__("os").environ.get("DEEPAGENT_DATA_DIR", "/app/data")
    )
    db_path = data_dir / "checkpoints.sqlite"
    out_dir = data_dir / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)

    meta_by_id: dict[str, Any] = {}
    sessions_path = data_dir / "sessions.json"
    if sessions_path.is_file():
        raw = json.loads(sessions_path.read_text(encoding="utf-8"))
        meta_by_id = raw.get("sessions") or {}

    serde = JsonPlusSerializer()
    conn = sqlite3.connect(db_path)

    written: list[str] = []
    for spec in SESSIONS:
        payload = export_session(
            conn=conn,
            serde=serde,
            session_id=spec["id"],
            label=spec["label"],
            user_query=spec["user_query"],
            meta=meta_by_id.get(spec["id"]),
        )
        out_path = out_dir / f"subagent-run-{spec['label']}.json"
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        written.append(str(out_path))
        print(
            f"Wrote {out_path.name}: "
            f"main={payload['main_thread']['message_count']} msgs, "
            f"subagents={len(payload['subagent_runs'])}, "
            f"subagent_tools={sum(r['tool_call_count'] for r in payload['subagent_runs'])}"
        )

    conn.close()
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
