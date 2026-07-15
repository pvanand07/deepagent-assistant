---
topic: sandbox-microsandbox
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 2
tokens: 420
code-paths:
  - src/deep_agent/sandbox/
  - Dockerfile.sandbox
  - skills/officecli/
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
- Guest image (`Dockerfile.sandbox`) ships `officecli` at `/usr/local/bin` plus `libicu` (required by the .NET binary), Chromium, and `fonts-liberation` for `officecli view screenshot`. Agent skill: `skills/officecli/` (copied into workdir by `ensure_skills_in_workdir`).

## decisions

- Hard-replace bubblewrap/Docker packaging with microsandbox microVM — why: native desktop virt (WHP/KVM) without shipping a full container stack. *Supersedes: bubblewrap sandbox.*
- One shared VM for the whole app — why: cost/complexity of per-session VMs.
- Host-direct upload/download; VM for shell only — why: Windows virtiofs/9p Permission denied on guest open of bind mount.
- No host-filesystem stub when VM down — why: avoid false sense of sandbox; keep chat usable.
- Bake `officecli` into the guest image (not install-on-demand) — why: sandbox network is often off; document work must work offline. Install to `/usr/local/bin`, never under `/workspace` (bind mount).
- Bake Chromium (+ liberation fonts) into the guest image — why: pptx/docx Gate 3 `view screenshot` needs a headless browser; apt Chromium is the lightest auto-detected backend (~350–450 MiB). Prefer over Playwright.

## gotchas

- Calling sync `MicrosandboxSandbox.execute()` on the FastAPI event-loop thread raises — use `aexecute()`.
- Shared VM + concurrent runs: without `sandbox_wait`, agents can interleave shell state.
- `CODEX_GUI_WORKSPACE` still accepted as workdir env alias.
- After changing `Dockerfile.sandbox`, rebuild/push the image and recreate the VM — an old tag will not have `officecli` / Chromium.

## references

- `docs/microsandbox-migration.md`
- `docs/LICENSES.md` (redistribution constraints)
