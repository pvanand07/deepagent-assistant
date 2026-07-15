---
topic: runtime-topology
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 1
tokens: 280
code-paths:
  - src-tauri/src/lib.rs
  - src-tauri/src/sidecar.rs
  - src-tauri/tauri.conf.json
  - src/deep_agent/api/app.py
  - desktop-stub/
  - frontend/
related-topics: [sandbox-microsandbox, chat-runs-sse, desktop-packaging-ci, frontend-vue-static, settings-and-secrets, persistence-sqlite]
---

## overview

Desktop app is a thin Tauri shell that spawns a FastAPI/uvicorn sidecar; the product Vue UI is served by FastAPI after health, not by Tauri's `frontendDist`.

## current behavior

- Tauri `frontendDist` points at `desktop-stub/` (boot chrome only).
- Rust spawns Python sidecar, polls `/health`, then navigates WebView to `http://127.0.0.1:<port>/`.
- FastAPI mounts API routes first, then `StaticFiles(frontend/, html=True)` at `/`.
- Preferred port 8010 with free-port fallback; health timeout ~90s.
- Desktop data dir: AppData `DeepAgent`; workspace: Documents `DeepAgent/workspace`.
- Close window quits app and kills sidecar (no tray).

## decisions

- Hybrid Tauri + FastAPI sidecar instead of rewriting UI in Rust/React — why: keep existing Vue GUI and Python agent stack.
- Split AppData (SQLite/settings) from Documents workspace — why: user-visible files stay out of app data.
- Bind loopback only in desktop — why: no product auth; CORS `*` is acceptable only locally.

## gotchas

- Product UI is FastAPI `/`, not the Tauri stub — debugging blank UI usually means sidecar health/nav failed, not a frontendDist build issue.
- `tauri dev` forces repo `uv run` / system Python and ignores a leftover packaged `sidecar/` tree.

## references

- `docs/tauri-migration.md`
- `docs/project-architecture/BUILD_FROM_SCRATCH.md`
