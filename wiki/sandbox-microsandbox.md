---
topic: sandbox-microsandbox
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 2
tokens: 340
code-paths:
  - src/deep_agent/sandbox/
  - Dockerfile.sandbox
  - docs/microsandbox-migration.md
related-topics: [runtime-topology, agent-factory-subagents, chat-runs-sse]
---

## overview

One shared microsandbox microVM backs all sessions: host-direct file I/O, guest shell exec, app-wide network toggle, and degraded chat-only mode when virt fails.

## current behavior

- `SandboxManager` owns VM lifecycle at app lifespan; shared sandbox named `deepagent`.
- Host workdir bind-mounted at `/workspace`.
- `MicrosandboxSandbox`: `read_file`/`write_file` on host paths; `execute`/`aexecute` in guest.
- Network is app-wide (`Network.none()` vs `Network.public_only()`), not per-session.
- Parallel agent runs share one VM; exec is serialized — agents use lock/`sandbox_wait` tools.
- Stub backend via `DEEPAGENT_SANDBOX_BACKEND=stub` for tests.
- Degraded virt: no host-filesystem stub tools; chat + MCP only; `POST /api/sandbox/retry` to recover.
- Defaults: 1024 MiB / 2 CPUs / idle 300s / exec timeout 120s; Windows DNS pinned to `1.1.1.1`/`8.8.8.8`.

## decisions

- Hard-replace bubblewrap/Docker packaging with microsandbox microVM — why: native desktop virt (WHP/KVM) without shipping a full container stack. *Supersedes: bubblewrap sandbox.*
- One shared VM for the whole app — why: cost/complexity of per-session VMs.
- Host-direct upload/download; VM for shell only — why: Windows virtiofs/9p Permission denied on guest open of bind mount.
- No host-filesystem stub when VM down — why: avoid false sense of sandbox; keep chat usable.

## gotchas

- Calling sync `MicrosandboxSandbox.execute()` on the FastAPI event-loop thread raises — use `aexecute()`.
- Shared VM + concurrent runs: without `sandbox_wait`, agents can interleave shell state.
- `CODEX_GUI_WORKSPACE` still accepted as workdir env alias.

## references

- `docs/microsandbox-migration.md`
- `docs/LICENSES.md` (redistribution constraints)
