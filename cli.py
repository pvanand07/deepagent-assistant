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

CYAN = "\033[36m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _print_new_messages(messages: list, already_printed: int) -> int:
    """Print messages beyond `already_printed`, return the new count."""
    for msg in messages[already_printed:]:
        msg_type = type(msg).__name__
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                print(f"  {CYAN}→ calling {tc['name']}({tc['args']}){RESET}")
        elif msg_type == "ToolMessage":
            content = str(getattr(msg, "content", ""))
            preview = content if len(content) < 500 else content[:500] + " …[truncated]"
            print(f"  {GRAY}← {preview}{RESET}")
        elif msg_type == "AIMessage" and getattr(msg, "content", None):
            print(f"\n{BOLD}Agent:{RESET} {msg.content}\n")
    return len(messages)


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

            printed = len(history) - 1  # don't re-print the human message we just added
            final_messages = history
            for state in agent.stream({"messages": history}, stream_mode="values"):
                final_messages = state["messages"]
                printed = _print_new_messages(final_messages, printed)
            history = final_messages

    finally:
        sandbox.cleanup()
        print("\nSandbox cleaned up. Bye.")


if __name__ == "__main__":
    main()
