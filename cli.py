"""Interactive REPL for the sandboxed deep agent.

Usage:
    python cli.py
    python cli.py --model "openai/gpt-5"
    python cli.py --network   # allow the sandbox outbound internet access

Type 'exit' or Ctrl-D to quit. Type '/reset' to clear conversation history
(the sandbox filesystem persists across turns within one run either way).
"""

from __future__ import annotations

import argparse
import sys

from agent import _default_workdir, build_agent
from streaming import DEFAULT_STYLE, stream_agent_turn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="OpenRouter model id, e.g. anthropic/claude-sonnet-4.5")
    parser.add_argument("--network", action="store_true", help="Allow sandbox outbound network access")
    parser.add_argument("--workdir", default=None, help="Host directory to use as the sandbox workspace")
    args = parser.parse_args()

    workdir = args.workdir or _default_workdir()
    network = True if args.network else None

    try:
        agent, sandbox = build_agent(model_name=args.model, network=network, workdir=workdir)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print("Sandboxed deep agent ready.")
    print(f"  sandbox id : {sandbox.id}")
    print(f"  workdir    : {sandbox._workdir}")
    print(f"  network    : {sandbox.network}")
    print("Type your request, '/reset' to clear history, or 'exit' to quit.\n")

    history: list[dict] = []
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
                history = []
                print("History cleared (sandbox files are untouched).\n")
                continue

            history.append({"role": "user", "content": user_input})
            history = stream_agent_turn(agent, history, style=DEFAULT_STYLE)

    finally:
        sandbox.cleanup()
        print("\nSandbox cleaned up. Bye.")


if __name__ == "__main__":
    main()
