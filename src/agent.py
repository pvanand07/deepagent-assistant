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
import tomllib
from pathlib import Path
from typing import Any

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

UI preview buttons:
- When you create or modify a previewable workspace file (HTML, CSS, Markdown,
  images, etc.), you may offer a one-click preview button in your reply using
  this XML tag (rendered as a button that opens the preview pane):

  <preview path="relative/workspace/path">Button label</preview>

  Self-closing form (label via attribute):

  <preview path="relative/workspace/path" label="Button label" />

- Rules:
  - `path` is required and must be relative to /workspace (no leading slash).
  - Only use for files that exist in the workspace at reply time.
  - Use a short, action-oriented label (e.g. "View preview", "Open landing page").
  - Place the tag after explaining what was built; one tag per file is enough.
  - Do not wrap the tag in code fences — it must appear as raw markup in prose.
"""

_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


def load_subagents_from_toml(agents_dir: Path | None = None) -> list[SubAgent]:
    """Load codex-style agent TOML definitions as deepagents SubAgent specs."""
    root = agents_dir or _AGENTS_DIR
    subagents: list[SubAgent] = []

    for path in sorted(root.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        system_prompt = data.get("system_prompt") or data.get("developer_instructions")
        if not system_prompt:
            msg = f"{path}: missing system_prompt"
            raise ValueError(msg)

        subagent: SubAgent = {
            "name": data["name"],
            "description": data["description"],
            "system_prompt": system_prompt.strip(),
        }

        model_name = data.get("model")
        reasoning_effort = data.get("model_reasoning_effort")
        if model_name or reasoning_effort:
            subagent["model"] = get_openrouter_model(
                model=model_name,
                reasoning_effort=reasoning_effort,
            )

        subagents.append(subagent)

    return subagents


def build_agent(
    *,
    model_name: str | None = None,
    network: bool | None = None,
    workdir: str | None = None,
    with_subagents: bool = True,
    mcp_tools: list | None = None,
    mcp_servers: list[str] | None = None,
    checkpointer: Any | None = None,
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

    subagents = load_subagents_from_toml() if with_subagents else []

    agent = create_deep_agent(
        model=model,
        backend=sandbox,
        system_prompt=MAIN_SYSTEM_PROMPT,
        subagents=subagents or None,
        tools=mcp_tools or None,
        middleware=[PwdContextMiddleware()],
        context_schema=AgentContext,
        checkpointer=checkpointer,
    )
    mcp_meta = {
        "servers": resolved_servers,
        "tool_names": [getattr(t, "name", str(t)) for t in (mcp_tools or [])],
        "subagent_names": [s["name"] for s in subagents],
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
