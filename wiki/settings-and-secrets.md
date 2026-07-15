---
topic: settings-and-secrets
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: core
rank: 5
tokens: 280
code-paths:
  - src/deep_agent/settings/store.py
  - src/deep_agent/sandbox/config.py
  - src/deep_agent/api/models.py
related-topics: [llm-providers, runtime-topology, desktop-packaging-ci, persistence-sqlite, frontend-vue-static]
---

## overview

App configuration lives in `settings.json` + `secrets.json` under the data dir; process env overrides for CI/tests; legacy `.env` is one-time migrated then ignored for settings keys.

## current behavior

- `settings.json` — platforms, models, sandbox, setup flag (non-secret).
- `secrets.json` — API keys per platform (mode 0600 when possible).
- One-time `.env` → JSON migration, then settings keys ignore `.env`.
- `apply_settings_to_environ` pushes active settings into `os.environ` for legacy readers.
- API still accepts flat legacy `values` and/or structured `config`; `env_path` deprecated.
- Under Tauri, leftover project `.env` must not reseed Setup (desktop load path).

## decisions

- JSON settings superseded AppData/project `.env` as source of truth — why: structured platforms/models + safer secrets file. *Supersedes: `.env`-as-primary config.*
- Keep env overrides for CI/tests — why: hermetic pytest and packaging smoke without writing JSON.
- Accept dual API payloads (flat + structured) during transition — why: older clients.

## gotchas

- `docs/tauri-migration.md` decisions still mention AppData `.env` in places — code uses JSON; trust `store.py` over that doc.
- Flat `values` and structured `config` both accepted — new code should prefer structured.

## references

- `docs/tauri-migration.md` (partially stale on `.env`)
- `.env.example` (dev template only)
