"""Assembles the deep agent: OpenRouter model + bubblewrap-sandboxed backend.

The agent gets `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`,
and `execute` tools for free from `deepagents.FilesystemMiddleware`, all
backed by `BubblewrapSandbox` -- so every shell command and file operation
the agent runs happens inside an isolated bwrap namespace jail, not on your
host.
"""

from __future__ import annotations

import atexit
import os

from deepagents import SubAgent, create_deep_agent
from dotenv import load_dotenv

from bubblewrap_sandbox import BubblewrapSandbox
from openrouter_model import get_openrouter_model

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes"}


def _default_workdir() -> str | None:
    return os.environ.get("DEEPAGENT_WORKDIR") or os.environ.get("CODEX_GUI_WORKSPACE")


def _default_network() -> bool:
    return _env_bool("DEEPAGENT_NETWORK_ACCESS") or _env_bool("CODEX_GUI_NETWORK_ACCESS")


MAIN_SYSTEM_PROMPT = """You are a careful, autonomous coding and research agent.

You have a sandboxed filesystem and shell (`ls`, `read_file`, `write_file`,
`edit_file`, `glob`, `grep`, `execute`) rooted at /workspace. This sandbox has
NO network access and cannot see or affect anything on the host machine
outside /workspace -- treat it as a clean, disposable scratch environment.

Guidelines:
- Always `ls`/`read_file` before editing a file you haven't seen yet.
- Prefer `write_file`/`edit_file` over echoing content through `execute`.
- Use `execute` for running scripts, tests, and installed CLI tools.
- If a task is complex or multi-step, break it down with the todo tools
  before diving in.
- Be explicit about assumptions and report clearly what you did and why.
"""

# Example of a predefined, on-demand sub-agent (see the task-delegation
# pattern from deep-agents-from-scratch) -- remove or extend this list as
# needed. Sub-agents share the same sandboxed backend/tools as the parent.
SUBAGENTS: list[SubAgent] = [
    {
        "name": "code-reviewer",
        "description": (
            "Reviews code in the sandbox for correctness, style, and bugs. "
            "Use for a second-opinion pass after writing or editing code."
        ),
        "system_prompt": (
            "You are a meticulous code reviewer. Read the relevant files with "
            "read_file, run any tests with execute, and report concrete, "
            "actionable issues. Do not rewrite the code yourself unless asked."
        ),
    },
]


def build_agent(
    *,
    model_name: str | None = None,
    network: bool | None = None,
    workdir: str | None = None,
    with_subagents: bool = True,
):
    """Construct the deep agent and its sandbox backend.

    Returns:
        (agent, sandbox) -- keep a handle on `sandbox` so you can call
        `sandbox.cleanup()` when you're done (this module also registers an
        `atexit` cleanup automatically).
    """
    model = get_openrouter_model(model=model_name)

    sandbox = BubblewrapSandbox(
        workdir=workdir or _default_workdir(),
        network=network if network is not None else _default_network(),
        timeout=120,
        rlimit_as_mb=1024,
        rlimit_nproc=64,
    )
    atexit.register(sandbox.cleanup)

    agent = create_deep_agent(
        model=model,
        backend=sandbox,
        system_prompt=MAIN_SYSTEM_PROMPT,
        subagents=SUBAGENTS if with_subagents else None,
    )
    return agent, sandbox


if __name__ == "__main__":
    # Smoke test: construct the agent and print the wired-up tool names.
    agent, sandbox = build_agent()
    print(f"Agent built. Sandbox id: {sandbox.id}, workdir: {sandbox._workdir}")
    print(f"Network enabled: {sandbox.network}")
    sandbox.cleanup()
