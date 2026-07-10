"""Debug harness for streaming + sandbox probes (native microsandbox)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agent import build_agent
from sandbox_manager import get_manager
from streaming import iter_agent_turn_events


async def inspect_stream() -> None:
    manager = get_manager()
    await manager.startup()
    try:
        agent, sandbox, _meta = build_agent(with_subagents=False)
        print(f"sandbox id: {sandbox.id}")
        print(f"workdir: {sandbox._workdir}")
        print(f"network: {sandbox.network}")
        print(f"status: {manager.status_dict()}")

        result = await sandbox.aexecute("echo STREAM_PROBE && pwd")
        print(f"exec output:\n{result.output}")
        print(f"exit_code={result.exit_code} truncated={result.truncated}")

        history = [{"role": "user", "content": "Reply with exactly: STREAM_OK"}]
        async for event in iter_agent_turn_events(
            agent, history, thread_id="inspect-stream"
        ):
            if event.get("type") == "token":
                print(event.get("text", ""), end="", flush=True)
            elif event.get("type") == "done":
                print("\n[done]")
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    # Ensure src imports resolve when run as a script.
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("DEEPAGENT_WORKDIR", str(root.parent / "workspace"))
    asyncio.run(inspect_stream())
