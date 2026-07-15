---
topic: chat-runs-sse
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 3
tokens: 300
code-paths:
  - src/deep_agent/api/app.py
  - src/deep_agent/chat/sessions.py
  - src/deep_agent/chat/runs.py
  - src/deep_agent/chat/streaming.py
  - src/deep_agent/chat/messages.py
related-topics: [persistence-sqlite, agent-factory-subagents, frontend-vue-static, sandbox-microsandbox, runtime-topology]
---

## overview

Chat is run-based: POST starts a background run, SSE streams durable events (resumable), and only explicit cancel stops work — disconnect does not.

## current behavior

- `POST /api/sessions/{sid}/chat` → 202 `{run_id}`.
- `GET …/runs/{run_id}/events` SSE; resume via `?after=<seq>` or `Last-Event-ID`.
- `POST …/runs/{run_id}/cancel` → cancel + checkpoint rollback.
- `GET …/runs/active` for reconnect discovery.
- One active run per session; global semaphore `DEEPAGENT_MAX_CONCURRENT_RUNS` (default 8).
- Per-session hydration locks; shared MCP cache and shared sandbox across sessions.
- Legacy `POST …/chat/stop` still present alongside run-scoped cancel.
- Token bursts coalesced in event log; `usage_estimate` is ephemeral.

## decisions

- Run/SSE over request-scoped streaming — why: client disconnect must not cancel agent work; reconnects replay from durable log.
- Keep legacy `/chat/stop` temporarily — why: older clients; migrate to run cancel.

## gotchas

- SSE disconnect ≠ cancel — operators may think closing the tab stops the agent; it does not.
- Dual cancel surfaces (`/chat/stop` vs run cancel) can confuse new frontend code.
- Hydration builds agent once per session — settings/model changes may require new session (hot-reload not fully verified).

## references

- `docs/project-architecture/BUILD_FROM_SCRATCH.md` (chat contract)
