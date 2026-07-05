"""Inspect raw LangGraph v2 stream chunks and sandbox internals."""

from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any

from agent import build_agent


def _short_repr(obj: Any, max_len: int = 120) -> str:
    text = repr(obj)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _token_summary(token: Any) -> dict[str, Any]:
    return {
        "type": type(token).__name__,
        "text": getattr(token, "text", None),
        "content": getattr(token, "content", None),
        "tool_call_chunks": getattr(token, "tool_call_chunks", None),
        "name": getattr(token, "name", None),
    }


def inspect_stream_chunks() -> None:
    print("=" * 60)
    print("STREAM CHUNK INSPECTION")
    print("=" * 60)

    agent, sandbox, _mcp_meta = build_agent(with_subagents=False)
    history = [{"role": "user", "content": "Reply with exactly: STREAM_OK"}]

    chunk_types: Counter[str] = Counter()
    message_tokens: list[dict[str, Any]] = []
    values_count = 0
    final_messages = history
    raw_chunks: list[dict[str, Any]] = []

    try:
        for i, chunk in enumerate(
            agent.stream(
                {"messages": history},
                stream_mode=["messages", "values"],
                subgraphs=True,
                version="v2",
            )
        ):
            # Normalize chunk shape for reporting
            if isinstance(chunk, dict):
                ctype = chunk.get("type", "<no type>")
                ns = chunk.get("ns", ())
                data = chunk.get("data")
            else:
                ctype = type(chunk).__name__
                ns = ()
                data = chunk

            chunk_types[ctype] += 1
            entry: dict[str, Any] = {"index": i, "type": ctype, "ns": ns}

            if ctype == "values":
                values_count += 1
                if isinstance(data, dict) and "messages" in data:
                    final_messages = data["messages"]
                    entry["message_count"] = len(final_messages)
                raw_chunks.append(entry)
                continue

            if ctype == "messages" and isinstance(data, (list, tuple)) and len(data) >= 1:
                token, metadata = data[0], data[1] if len(data) > 1 else None
                summary = _token_summary(token)
                message_tokens.append(summary)
                entry["token"] = summary
                entry["metadata"] = _short_repr(metadata)
                raw_chunks.append(entry)
                continue

            entry["data"] = _short_repr(data)
            raw_chunks.append(entry)

        print(f"\nTotal chunks: {sum(chunk_types.values())}")
        print(f"Chunk type counts: {dict(chunk_types)}")
        print(f"Values chunks: {values_count}")
        print(f"Message token chunks: {len(message_tokens)}")

        ai_text_parts = []
        for t in message_tokens:
            text = t.get("text")
            if text is None and isinstance(t.get("content"), str):
                text = t["content"]
            if text and t["type"] in {"AIMessageChunk", "AIMessage"}:
                ai_text_parts.append(text)

        streamed_text = "".join(ai_text_parts)
        print(f"\nConcatenated AI token text ({len(ai_text_parts)} chunks):")
        print(f"  {streamed_text!r}")

        if final_messages:
            last = final_messages[-1]
            final_content = getattr(last, "content", None) or (
                last.get("content") if isinstance(last, dict) else None
            )
            print(f"\nFinal message content:")
            print(f"  {final_content!r}")

            if isinstance(final_content, str) and streamed_text:
                match = final_content.startswith(streamed_text) or streamed_text in final_content
                print(f"\nStream/final alignment: {'OK' if match else 'MISMATCH'}")

        print("\nFirst 8 message token summaries:")
        for t in message_tokens[:8]:
            print(f"  {json.dumps(t, default=str)}")

        if len(message_tokens) > 8:
            print(f"  ... ({len(message_tokens) - 8} more)")

        print("\nLast 3 raw chunk entries:")
        for entry in raw_chunks[-3:]:
            print(f"  {json.dumps(entry, default=str)}")

        # Validate streaming.py expectations
        print("\nstreaming.py compatibility checks:")
        checks = {
            "chunks are dicts with 'type'": all(
                isinstance(c, dict) and "type" in c for c in raw_chunks if "index" in c
            ),
            "has 'messages' chunks": chunk_types.get("messages", 0) > 0,
            "has 'values' chunks": chunk_types.get("values", 0) > 0,
            "AI tokens streamed incrementally": len(ai_text_parts) > 1,
            "no unexpected chunk types": set(chunk_types) <= {"messages", "values"},
        }
        for name, ok in checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    finally:
        sandbox.cleanup()


def inspect_sandbox_inside_container() -> None:
    print("\n" + "=" * 60)
    print("SANDBOX / CONTAINER INSPECTION")
    print("=" * 60)

    import os
    import shutil
    import subprocess

    print("\nHost/container environment:")
    print(f"  cwd: {os.getcwd()}")
    print(f"  bwrap: {shutil.which('bwrap')}")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  DEEPAGENT_WORKDIR: {os.environ.get('DEEPAGENT_WORKDIR')}")

    _, sandbox, _mcp_meta = build_agent(with_subagents=False)
    try:
        print(f"\nSandbox instance:")
        print(f"  id: {sandbox.id}")
        print(f"  workdir (host): {sandbox._workdir}")
        print(f"  sandbox_root: {sandbox.sandbox_root}")
        print(f"  network: {sandbox.network}")

        tests = [
            ("whoami", "whoami"),
            ("pwd", "pwd"),
            ("ls workspace", "ls -la /workspace"),
            ("write+read", "echo hello_sandbox > /workspace/_probe.txt && cat /workspace/_probe.txt"),
            ("host escape probe", "test -d /app && echo APP_VISIBLE || echo APP_HIDDEN"),
            ("network probe", "curl -s --max-time 2 https://example.com >/dev/null && echo NET_OK || echo NET_BLOCKED"),
        ]

        print("\nSandbox execute() probes:")
        for label, cmd in tests:
            result = sandbox.execute(cmd)
            out = result.output.strip().replace("\n", " | ")
            print(f"  [{label}] exit={result.exit_code}  {out[:200]}")

        # Verify file persisted on host workdir
        probe = sandbox._workdir / "_probe.txt"
        print(f"\nHost-side probe file exists: {probe.exists()}")
        if probe.exists():
            print(f"  content: {probe.read_text().strip()!r}")
            probe.unlink(missing_ok=True)

        # Show bwrap argv shape (first few args)
        argv = sandbox._build_bwrap_argv("echo bwrap_ok")
        print(f"\nbwrap argv (first 12): {' '.join(argv[:12])} ...")

    finally:
        sandbox.cleanup()


if __name__ == "__main__":
    inspect_stream_chunks()
    inspect_sandbox_inside_container()
