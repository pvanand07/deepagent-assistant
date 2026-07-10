"""Interactive REPL for the sandboxed deep agent.

Usage:
    uv run --directory . python -c "import sys; sys.path.insert(0,'src'); from cli import main; main()"
    # or with PYTHONPATH:
    PYTHONPATH=src uv run python src/cli.py

Network and workdir are app-wide (``DEEPAGENT_NETWORK_ACCESS``,
``DEEPAGENT_WORKDIR``). Type 'exit' or Ctrl-D to quit. Type '/reset' to clear
conversation history.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from agent import build_agent
from sandbox_manager import get_manager
from session_persistence import CheckpointManager
from streaming import iter_agent_turn_events

CLI_THREAD_ID = os.environ.get("DEEPAGENT_CLI_THREAD_ID", "cli")


async def _print_turn(agent, message: str) -> None:
    async for event in iter_agent_turn_events(
        agent,
        [{"role": "user", "content": message}],
        thread_id=CLI_THREAD_ID,
    ):
        et = event.get("type")
        if et == "token":
            print(event.get("text", ""), end="", flush=True)
        elif et == "tool_call_start":
            print(f"\n[tool {event.get('name', '?')}]", flush=True)
        elif et == "tool_result":
            preview = (event.get("content") or "")[:200]
            print(f"\n[tool result] {preview}", flush=True)
        elif et == "done":
            print("\n", flush=True)


async def _amain() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", default=None, help="OpenRouter model id, e.g. anthropic/claude-sonnet-4.5"
    )
    args = parser.parse_args()

    manager = get_manager()
    await manager.startup()
    try:
        checkpoints = await CheckpointManager.get()
        try:
            agent, sandbox, mcp_meta = build_agent(
                model_name=args.model,
                checkpointer=checkpoints.checkpointer,
            )
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print("Sandboxed deep agent ready.")
        print(f"  sandbox id : {sandbox.id}")
        print(f"  workdir    : {sandbox._workdir}")
        print(f"  network    : {sandbox.network}")
        if mcp_meta["servers"]:
            print(f"  mcp        : {', '.join(mcp_meta['servers'])}")
            print(f"  mcp tools  : {', '.join(mcp_meta['tool_names'])}")
        print("Type your request, '/reset' to clear history, or 'exit' to quit.\n")

        while True:
            try:
                user_input = await asyncio.to_thread(lambda: input("You: ").strip())
            except EOFError:
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break
            if user_input == "/reset":
                await checkpoints.delete_thread(CLI_THREAD_ID)
                print("History cleared (sandbox files are untouched).\n")
                continue

            await _print_turn(agent, user_input)
    finally:
        await manager.shutdown()
        print("\nSandbox shut down. Bye.")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
