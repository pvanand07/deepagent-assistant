"""Assembles the deep agent: OpenRouter model + microsandbox backend.

The agent gets `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`,
and `execute` tools from `deepagents.FilesystemMiddleware`, backed by a
shared microsandbox microVM (see ``SandboxManager``).

Sandbox VM lifecycle is owned by ``SandboxManager`` (app lifespan), not by
individual sessions.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from deepagents import SubAgent, create_deep_agent

from mcp_tools import load_mcp_tools
from openrouter_model import get_openrouter_model
from pwd_middleware import AgentContext, PwdContextMiddleware
from sandbox_config import default_network, default_workdir
from sandbox_tools import build_sandbox_tools


def _default_workdir() -> str | None:
    return str(default_workdir())


def _default_network() -> bool:
    return default_network()


MAIN_SYSTEM_PROMPT = """You are DeepAgent, a precise, safe, and helpful coding agent.
Resolve the user's request fully; keep communication concise, direct, and friendly.

Environment:
- Filesystem and shell tools (`ls`, `read_file`, `write_file`, `edit_file`,
  `glob`, `grep`, `execute`) run inside a shared microsandbox microVM rooted at
  /workspace (host workspace bind-mounted). Preserve user work in /workspace.
- The run context may supply an active pwd under /workspace; treat it as the
  primary scope for new files and edits unless the user says otherwise.
- Shell network access follows the app-wide setting (often disabled). MCP tools
  (when available) run outside the sandbox; use them for live documentation
  lookup only. Web research always goes through `research_agent`, never the
  main agent.
- `execute` output returns only the last 100 lines. Full logs are saved under
  `/workspace/.deepagent/logs/`; read those files when you need more detail.
- You may set a longer per-command timeout when installs/builds need it.
- All chats share one sandbox. Exec is serialized. If you are blocked, use
  `sandbox_status` / `sandbox_wait` (configure wait_seconds) and wait by
  default. Ask the user before `cancel_sandbox_holder`.

How to work:
- Inspect the repo before acting; obey the most specific AGENTS.md / AGENT.md
  guidance for every file you touch.
- Send a brief progress note before grouped tool use or substantial edits.
- For multi-step tasks, keep a short todo plan with exactly one active step.
- Read files before editing. Use `read_file`/`write_file`/`edit_file` for file
  operations, `execute` for tests and CLI tools, `grep`/`glob` for search.
- Keep changes minimal and rooted in the request. Fix causes, not symptoms.
  Follow existing style. No unrelated refactors, commits, branches, license
  headers, or formatting churn unless the user asks.

Routing:
- Code work, workspace file tasks, and questions answerable from your own
  knowledge: handle yourself. No task folder, no subagents.
- Research tasks: ALWAYS delegate. A task is research when the user asks for
  research, or when answering requires web information not in the workspace
  and not in your knowledge. Never search or fetch the web yourself.
- Every research task runs the full pipeline in one `task_dir`:
  `research_agent` -> `output_planner` -> `builder`, ending in an HTML report
  under `<task_dir>/build/`. Do not stop to ask between stages; only pause if
  a subagent reports a blocker or the user interrupts.
- Deliverable-only tasks (no research needed): `output_planner` -> `builder`.

Task folders (whenever delegating or producing a multi-file deliverable):
- Create `tasks/<short-slug>-<ddmmyy>/` before the first handoff or artifact
  write. Slug: lowercase, hyphenated, ~3-6 words from the topic; date DDMMYY.
  Example: `tasks/lizmotors-research-060726/`. If taken, append `-2`, `-3`, ...
- Layout: `research/brief.md` + `research/sources/` (research_agent),
  `output/spec.md` (output_planner), `build/` (builder).
- Pass `task_dir` (relative to /workspace, no leading slash) in every handoff;
  subagents write only under it. Reuse the same `task_dir` for follow-ups on
  the same task; new folder for a clearly new topic.

Subagent handoffs:
- `research_agent` — pass the user's request verbatim plus `task_dir`. Do not
  add assumptions, scope, or deliverable choices.
- `output_planner` — pass `task_dir`, the user's goals, the output format
  (`html-report` unless the user specified another format), and
  `<task_dir>/research/brief.md` when it exists.
- `builder` — pass `task_dir`; it implements `<task_dir>/output/spec.md`.
  Do not re-plan or re-research unless it reports a blocker.

After the pipeline completes:
- Give a concise research summary in your reply.
- Offer preview buttons for the HTML report (`<task_dir>/build/...`) first,
  then `<task_dir>/research/brief.md` and any notable
  `<task_dir>/research/sources/*.md`.

Validation:
- When the project has relevant tests, builds, linters, or format checks, run
  the narrowest useful validation first; broaden only when it adds confidence.
- Report unrelated failures that block validation; do not fix them.

Final response:
- Summarize what changed, where, and what validation ran.
- State important assumptions, skipped checks, or residual risks.
- Include only the next step that meaningfully helps the user.

UI preview buttons:
- Offer a preview button for each previewable artifact you created or
  reference (HTML, CSS, Markdown, images):

  <preview path="relative/workspace/path">Button label</preview>

  or self-closing: <preview path="relative/workspace/path" label="Label" />

- `path` is required, relative to /workspace, and must exist at reply time.
- Short action-oriented labels ("View research brief", "Open HTML report").
- Place after explaining the artifact; one tag per artifact; raw markup in
  prose, never inside code fences.
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
    with_subagents: bool = True,
    mcp_tools: list | None = None,
    mcp_servers: list[str] | None = None,
    checkpointer: Any | None = None,
    sandbox: Any | None = None,
):
    """Construct the deep agent using the shared microsandbox backend.

    Returns:
        (agent, sandbox, mcp_meta). The VM is owned by ``SandboxManager``;
        ``sandbox.cleanup()`` is a no-op for the shared backend.
    """
    model = get_openrouter_model(model=model_name)

    if sandbox is None:
        from sandbox_manager import get_manager

        sandbox = get_manager().backend

    if mcp_tools is None:
        try:
            mcp_tools, resolved_servers = load_mcp_tools()
        except Exception as exc:
            raise RuntimeError(f"Failed to load MCP tools: {exc}") from exc
    else:
        resolved_servers = list(mcp_servers or [])

    subagents = load_subagents_from_toml() if with_subagents else []
    extra_tools = list(mcp_tools or []) + build_sandbox_tools()

    agent = create_deep_agent(
        model=model,
        backend=sandbox,
        system_prompt=MAIN_SYSTEM_PROMPT,
        subagents=subagents or None,
        tools=extra_tools or None,
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
    import asyncio

    from sandbox_manager import get_manager

    async def _main() -> None:
        mgr = get_manager()
        await mgr.startup()
        try:
            agent, sandbox, mcp_meta = build_agent()
            print(f"Agent built. Sandbox id: {sandbox.id}, workdir: {sandbox._workdir}")
            print(f"Network enabled: {sandbox.network}")
            if mcp_meta["servers"]:
                print(f"MCP servers: {', '.join(mcp_meta['servers'])}")
                print(f"MCP tools: {', '.join(mcp_meta['tool_names'])}")
        finally:
            await mgr.shutdown()

    asyncio.run(_main())
