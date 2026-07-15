---
topic: agent-factory-subagents
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 6
tokens: 270
code-paths:
  - src/deep_agent/agent_factory.py
  - src/deep_agent/agent_context.py
  - src/deep_agent/cli.py
  - agents/
  - src/deep_agent/integrations/mcp.py
related-topics: [sandbox-microsandbox, llm-providers, chat-runs-sse]
---

## overview

`create_deep_agent` wires deepagents + shared microsandbox backend + MCP tools + TOML subagents; research/web work is delegated to subagents, and MCP runs outside the VM.

## current behavior

- Filesystem/shell tools from deepagents `FilesystemMiddleware` backed by `MicrosandboxSandbox`.
- Degraded: `backend=None`, `HostWorkspace` placeholder, no FS/shell tools — chat + MCP only.
- Subagents loaded from `agents/*.toml` (research_agent → output_planner → builder; fetch_extract for web).
- Main system prompt routes research/web away from the main agent.
- MCP loaded in-process from `.mcp.json` (env → AppData → repo search); stdio + HTTP/SSE; `${ENV}` expansion.
- Optional IResearcher URL + bearer for fetch pipeline.

## decisions

- Subagent research always delegated; main agent must not web-search — why: keep main agent focused; isolate fetch/extract pipeline.
- MCP outside sandbox — why: MCP needs host/network process access; sandbox is for agent shell/files.

## gotchas

- Degraded mode still allows MCP — tools that assume a workspace path may fail without a VM.
- Shared MCP cache across sessions — MCP server process lifetime is app-scoped, not per-chat.

## references

- `agents/*.toml`
- `docs/microsandbox-migration.md`
