---
topic: frontend-vue-static
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: extended
rank: 8
tokens: 250
code-paths:
  - frontend/main.js
  - frontend/index.html
  - frontend/styles.css
  - frontend/vendor/
  - frontend/settings-mockup.html
related-topics: [chat-runs-sse, runtime-topology, settings-and-secrets]
---

## overview

Product UI is an intentionally unbundled three-file Vue app (vendored deps) served by FastAPI; `main.js` owns REST + resumable SSE + workspace tree + settings hash routing.

## current behavior

- No bundler: Vue + marked + DOMPurify + highlight from `frontend/vendor/`.
- Custom SSE client with sequence resume (`after` / Last-Event-ID).
- Settings via `#settings` for Tauri menu deep-link.
- Tauri `invoke` for version/updater surfaces.
- Sandbox retry UI calls `/api/sandbox/retry`.
- `settings-mockup.html` exists beside live `index.html` (design artifact).

## decisions

- Keep three-file Vue frontend (no React rewrite) — why: ship with FastAPI static mount; avoid frontend build pipeline in desktop packaging.
- Offline-first via vendored assets — why: packaged desktop must work without CDN.

## gotchas

- `frontend/main.js` (~2400+ LOC) is the dominant complexity hotspot — most UI regressions land here.
- `settings-mockup.html` is not the product UI — do not wire packaging or routes to it.
- CSP in `tauri.conf.json` still allows `cdn.jsdelivr.net` even though vendors exist — prefer vendor paths.

## references

- `docs/project-architecture/BUILD_FROM_SCRATCH.md` §11
