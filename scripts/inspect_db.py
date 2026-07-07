#!/usr/bin/env python3
"""Quick inspection of session/run/checkpoint DB state."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "data" / "app.sqlite"
MSG = ROOT / "data" / "messages.sqlite"
CKPT = ROOT / "data" / "checkpoints.sqlite"


def main() -> None:
    if APP.exists():
        conn = sqlite3.connect(APP)
        conn.row_factory = sqlite3.Row
        print("=== sessions ===")
        for r in conn.execute(
            "SELECT id, title, preview, message_count, updated_at FROM sessions ORDER BY updated_at DESC LIMIT 10"
        ):
            print(dict(r))
        print("\n=== runs ===")
        for r in conn.execute(
            "SELECT id, session_id, status, error, created_at FROM runs ORDER BY created_at DESC LIMIT 10"
        ):
            print(dict(r))
        print("\n=== run_events (terminal) ===")
        for r in conn.execute(
            "SELECT run_id, seq, type FROM run_events WHERE type IN ('done','error','cancelled') ORDER BY run_id DESC, seq DESC LIMIT 10"
        ):
            print(dict(r))
        row = conn.execute(
            "SELECT payload FROM run_events WHERE type='done' ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if row:
            p = json.loads(row["payload"])
            msgs = p.get("messages") or []
            print(f"\nlatest done: {len(msgs)} messages, reply={p.get('reply', '')[:80]!r}")
        conn.close()
    else:
        print("no app.sqlite")

    if MSG.exists():
        conn = sqlite3.connect(MSG)
        conn.row_factory = sqlite3.Row
        print("\n=== session_messages ===")
        for r in conn.execute(
            "SELECT session_id, id, role, seq, created_at FROM session_messages ORDER BY seq DESC LIMIT 10"
        ):
            d = dict(r)
            d["session_id"] = d["session_id"][:8]
            print(d)
        conn.close()
    else:
        print("no messages.sqlite")

    if CKPT.exists():
        conn = sqlite3.connect(CKPT)
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print("\n=== checkpoint tables ===", tables)
        if "checkpoints" in tables:
            for r in conn.execute(
                "SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 10"
            ):
                print(dict(r))
        conn.close()
    else:
        print("no checkpoints.sqlite")


if __name__ == "__main__":
    main()
