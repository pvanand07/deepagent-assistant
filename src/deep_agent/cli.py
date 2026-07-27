"""Interactive REPL for the sandboxed deep agent.

Usage:
    PYTHONPATH=src python -m deep_agent.cli
    PYTHONPATH=src python -m deep_agent.cli --model "openai/gpt-5"
    PYTHONPATH=src python -m deep_agent.cli --network   # allow the sandbox outbound internet access

Type 'exit' or Ctrl-D to quit. Type '/reset' to clear conversation history
(the sandbox filesystem persists across turns within one run either way).
Conversation history is persisted under ``data/checkpoints.sqlite`` (see
``DEEPAGENT_DATA_DIR``).
"""

from __future__ import annotations

import argparse
import os
import sys

from deep_agent.agent_factory import _default_workdir, build_agent
from deep_agent.persistence.session_persistence import CheckpointManager
from deep_agent.chat.streaming import DEFAULT_STYLE, stream_agent_turn

CLI_THREAD_ID = os.environ.get("DEEPAGENT_CLI_THREAD_ID", "cli")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="OpenRouter model id, e.g. anthropic/claude-sonnet-4.5")
    parser.add_argument("--network", action="store_true", help="Allow sandbox outbound network access")
    parser.add_argument("--workdir", default=None, help="Host directory to use as the sandbox workspace")
    args = parser.parse_args()

    workdir = args.workdir or _default_workdir()
    network = True if args.network else None

    try:
        checkpointer = CheckpointManager.get().checkpointer
        agent, sandbox, mcp_meta = build_agent(
            model_name=args.model,
            network=network,
            workdir=workdir,
            checkpointer=checkpointer,
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

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break
            if user_input == "/reset":
                CheckpointManager.get().delete_thread(CLI_THREAD_ID)
                print("History cleared (sandbox files are untouched).\n")
                continue

            stream_agent_turn(
                agent,
                [{"role": "user", "content": user_input}],
                thread_id=CLI_THREAD_ID,
                style=DEFAULT_STYLE,
            )

    finally:
        sandbox.cleanup()
        print("\nSandbox cleaned up. Bye.")


if __name__ == "__main__":
    main()
