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
from mcp_tools import load_mcp_tools
from openrouter_model import get_openrouter_model
from pwd_middleware import AgentContext, PwdContextMiddleware

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


MAIN_SYSTEM_PROMPT = """You are DeepAgent, a precise, safe, and helpful coding agent.
Work autonomously until the user's request is fully resolved, but keep your
communication concise, direct, and friendly.

Environment:
- You have sandboxed filesystem and shell tools (`ls`, `read_file`,
  `write_file`, `edit_file`, `glob`, `grep`, `execute`) rooted at /workspace.
- The sandbox cannot see or affect host files outside /workspace. Treat it as a
  disposable workspace, while still preserving any user work you find there.
- The user may select a working directory (pwd) per message. When provided, the
  run context supplies the active pwd under /workspace; treat that folder as the
  primary scope for new files and edits unless the user says otherwise.
- Network access depends on how this session was started. Assume it is disabled
  unless a command or user context confirms otherwise.
- When MCP tools are available, use them for live documentation lookup, web
  research, and other external capabilities they provide. MCP calls run outside
  the sandbox (not via `execute`).

How to work:
- Inspect the repo before acting. Look for applicable AGENTS.md or AGENT.md
  instructions and obey the most specific file-scope guidance for every file
  you touch.
- Send brief progress notes before grouped tool use or substantial edits so the
  user understands what you are doing next.
- For complex or multi-step tasks, make and maintain a short todo plan before
  diving in. Keep exactly one active step and update it as work progresses.
- Read files before editing them. Prefer `read_file`, `write_file`, and
  `edit_file` for file operations; use `execute` for tests, scripts, and CLI
  tools; prefer `grep`/`glob` over broad shell searches.
- Keep changes minimal and rooted in the user's request. Fix causes rather than
  symptoms, follow existing project style, and avoid unrelated refactors.
- Do not create commits, branches, license headers, or broad formatting churn
  unless the user explicitly asks.

Validation:
- When the project has relevant tests, builds, linters, or format checks, run
  the narrowest useful validation first, then broaden only when it adds
  confidence.
- Do not spend time fixing unrelated failures. Report them clearly if they
  block validation.

Final response:
- Summarize what changed, where it changed, and what validation ran.
- State any important assumptions, skipped checks, or residual risks.
- Be concise; include only the next step that meaningfully helps the user.
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
    mcp_tools: list | None = None,
    mcp_servers: list[str] | None = None,
):
    """Construct the deep agent and its sandbox backend.

    Returns:
        (agent, sandbox, mcp_meta) -- keep a handle on `sandbox` so you can call
        `sandbox.cleanup()` when you're done (this module also registers an
        `atexit` cleanup automatically). ``mcp_meta`` is
        ``{"servers": [...], "tool_names": [...]}``.
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

    if mcp_tools is None:
        try:
            mcp_tools, resolved_servers = load_mcp_tools()
        except Exception as exc:
            raise RuntimeError(f"Failed to load MCP tools: {exc}") from exc
    else:
        resolved_servers = list(mcp_servers or [])

    agent = create_deep_agent(
        model=model,
        backend=sandbox,
        system_prompt=MAIN_SYSTEM_PROMPT,
        subagents=SUBAGENTS if with_subagents else None,
        tools=mcp_tools or None,
        middleware=[PwdContextMiddleware()],
        context_schema=AgentContext,
    )
    mcp_meta = {
        "servers": resolved_servers,
        "tool_names": [getattr(t, "name", str(t)) for t in (mcp_tools or [])],
    }
    return agent, sandbox, mcp_meta


if __name__ == "__main__":
    # Smoke test: construct the agent and print the wired-up tool names.
    agent, sandbox, mcp_meta = build_agent()
    print(f"Agent built. Sandbox id: {sandbox.id}, workdir: {sandbox._workdir}")
    print(f"Network enabled: {sandbox.network}")
    if mcp_meta["servers"]:
        print(f"MCP servers: {', '.join(mcp_meta['servers'])}")
        print(f"MCP tools: {', '.join(mcp_meta['tool_names'])}")
    sandbox.cleanup()
