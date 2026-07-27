# Web migration implementation (tauri → main)

Record of the selective port of desktop/`tauri` product features onto the
Docker + Bubblewrap **web** product on `main`. Landed via PR
[#1](https://github.com/pvanand07/deepagent-assistant/pull/1)
(`migrate/web-tier1-skeleton` → `main`, merged 2026-07-27).

For operators upgrading an existing Compose install, see also
[upgrade-web-tier1.md](./upgrade-web-tier1.md).

---

## Goal

Keep `main` as the **single-tenant Docker/web** app. Port web-relevant
behavior and package shape from the `tauri` line **without** replacing the
web sandbox with microsandbox or bringing Tauri packaging.

Long-term stance: **soft-share** — web and desktop stay separate for now, but
web uses a pluggable `SandboxBackend` so a later shared core is cheap.

---

## Locked decisions

| Topic | Decision |
| --- | --- |
| Product on `main` | Keep Docker/web; selective port from `tauri` (not wholesale replace) |
| Isolation | **Bubblewrap** inside the Compose container (not microsandbox) |
| Layout | Adopt `src/deep_agent/` package + pluggable `SandboxBackend` |
| Tenancy | Single-tenant self-host |
| Config | Dual-read (settings/secrets first when present; else `.env` / `.mcp.json`); migrate toward settings-first |
| Chat API | Run-based only (`202` + `/runs/{id}/events`); no `chat/stream` shim |
| Landing mechanics | Hand-port from `main` on a feature branch; series of commits → one PR |
| Python deps | `pyproject.toml` + `uv` / `uv.lock` (drop `requirements.txt` as source of truth) |
| Data migrate | Best-effort on first web start |
| Compose | One primary `api` container; port `8011→8010` |
| Setup UI | Auto-skip when config already exists |
| Models | Prefer tauri-era model catalog / pins |
| Desktop CI | Keep `desktop-build.yml` on `main` |
| Skills (initial) | Skill loader + grillme; then full officecli / chrome-devtools-axi |
| Out of scope (this land) | Tauri/sidecar/updater; microsandbox guest baking; code-wiki polish |

---

## What shipped

### Commits (on `main`)

1. `be3adee` — Restructure flat `src/*.py` → `src/deep_agent/` (content-identical renames).
2. `89717a6` — Tier 1: run API, settings/MCP, Bubblewrap seam, Vue frontend, pipeline, grillme, uv/Compose/docs.
3. `40ba721` — Tier 2: HTML QA, officecli, Chromium/Node/axi in Docker, binary downloads.
4. `6a31282` — MCP Compose seed/mount + empty-config fallthrough.
5. `12b4320` — Merge PR #1.

### Tier 1 (product core)

- **`deep_agent` package**: `api`, `chat`, `sandbox`, `settings`, `integrations`, `persistence`, `diagnostics`.
- **Run-based chat**: `POST .../chat` → `202 { run_id }`; agent continues in background; UI attaches via resumable SSE `GET .../runs/{run_id}/events` (`after` / `Last-Event-ID`). Cancel via run cancel / `chat/stop`.
- **Settings + secrets**: JSON under `DEEPAGENT_DATA_DIR`; dual-read from legacy `.env` when settings missing.
- **MCP**: load/test/save APIs; mid-run degrade on transport failure; writable config under data dir.
- **Vue static frontend**: chat, settings, MCP UI (replaces CDN one-file GUI).
- **Pipeline contract**: `source.md` → `spec.md` → `output/` + `agents/protocol.md` (replaces `research/brief.md` / `build/` for new work).
- **Bubblewrap backend**: `SandboxBackend` protocol + `BubblewrapBackend`; manager with lock / wait / cancel / `ExecResult`.
- **Skills**: loader + bundled `grillme`.
- **Tests**: API smoke, settings/MCP, runs, pipeline contract, MCP integration helpers.
- **Packaging**: `pyproject.toml`, `uv.lock`, Dockerfile `uv sync`, Compose mounts for live `src`/`frontend`/`agents`/`skills`.

### Tier 2 (tooling)

- **HTML QA tools**: `inspect_html`, `screenshot_html`, `bundle_html`.
  - Chromium runs on the **app host (container)**, not inside Bubblewrap — nested Docker+bwrap Chromium hit SIGTRAP.
- **officecli**: installed in image; works inside Bubblewrap; skills under `skills/officecli/**`.
- **chrome-devtools-axi**: Node + global package in image; skill under `skills/chrome-devtools-axi/`.
- **Binary downloads**: `GET .../files/download` for any workspace file; `/files/open` returns a download URL (no native OS open on web).
- **Builder prompts**: Office / HTML validation guidance wired in agent factory / builder TOML.

### MCP Compose fix

Problem: empty `/app/data/.mcp.json` was preferred over repo `.mcp.json`, so MCP tools never loaded.

Fix:

- Seed `data/.mcp.json` from example when missing / empty.
- Mount host `./.mcp.json` read-only at `/app/.mcp.json`.
- `read_mcp_servers_raw()` **skips** files whose `mcpServers` is empty so a blank data-dir file falls through to the repo config.

---

## Architecture (after land)

```
┌─────────────────────────────────────────────────────────────┐
│  Browser  →  http://host:8011  (Vue static + FastAPI)        │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  deep_agent.api.app                                         │
│    settings / MCP / sessions / runs / files / config        │
└───────┬─────────────────────┬───────────────────┬───────────┘
        │                     │                   │
        ▼                     ▼                   ▼
  settings store        chat.runs            integrations
  (JSON + .env)         (background + SSE)   (MCP, models)
        │                     │
        ▼                     ▼
  DEEPAGENT_DATA_DIR     SandboxManager
  settings.json          ┌────────────────┐
  secrets.json           │ SandboxBackend │
  .mcp.json              │ Bubblewrap…    │
  app.sqlite             └────────┬───────┘
                                  │
                                  ▼
                           bwrap → /workspace
```

### Package map

| Path | Role |
| --- | --- |
| `src/deep_agent/api/` | FastAPI app + Pydantic models |
| `src/deep_agent/chat/` | Sessions, runs, streaming helpers |
| `src/deep_agent/sandbox/` | Backend protocol, Bubblewrap, HTML tools, manager |
| `src/deep_agent/settings/` | Settings/secrets dual-read store |
| `src/deep_agent/integrations/` | MCP, model catalog/provider, OpenRouter |
| `src/deep_agent/persistence/` | AppDB + LangGraph checkpoints |
| `src/deep_agent/agent_factory.py` | Model + sandbox + skills wiring |
| `agents/` | Research → plan → build TOMLs + protocol |
| `skills/` | grillme, officecli, chrome-devtools-axi |
| `frontend/` | Vue GUI |
| `docs/` | Upgrade + this implementation note |

### Sandbox seam

```python
class SandboxBackend(Protocol):
    async def start(self) -> None: ...
    async def exec(self, command: str, *, timeout: int | None = None) -> ExecuteResponse: ...
    async def stop(self) -> None: ...
    def status(self) -> dict[str, object]: ...
```

Web implements `BubblewrapBackend`. Desktop microsandbox stays on the `tauri`
branch for now.

---

## Breaking / behavioral changes vs pre-migration `main`

| Before | After |
| --- | --- |
| Flat `src/api.py`, `sessions.py`, … | `src/deep_agent/...` |
| `POST .../chat/stream` (connection-owned SSE) | `POST .../chat` → run + `GET .../runs/{id}/events` |
| `requirements.txt` + pip | `pyproject.toml` + `uv.lock` |
| CDN one-file `frontend/index.html` | Multi-file Vue app + vendor assets |
| Pipeline `research/brief.md` → `build/` | `source.md` → `spec.md` → `output/` |
| Env / `.mcp.json` only | Settings dual-read + MCP API; empty data MCP skipped |
| Text-ish file content endpoints | Dedicated binary `/files/download` |
| uvicorn import `api:app` | `deep_agent.api.app:app` |

---

## HTTP surface (web)

Health / config:

- `GET /health`
- `GET /api/config`

Settings / MCP / sandbox:

- `GET|PUT /api/settings`
- `GET|PUT /api/mcp`, `POST /api/mcp/{name}/test`
- `POST /api/sandbox/retry`

Sessions / chat / runs:

- `GET|POST /api/sessions`, `GET|PATCH|DELETE /api/sessions/{id}`
- `GET .../messages`, `POST .../reset`
- `POST .../chat` → **202** `RunResponse`
- `GET .../runs/active`, `GET .../runs/{run_id}`
- `POST .../runs/{run_id}/cancel`, `POST .../chat/stop`
- `GET .../runs/{run_id}/events` (SSE, resumable)

Files:

- `GET .../files`, `.../files/content`, `.../files/raw`, `.../files/download`
- `GET .../preview/{file_path}`
- `POST .../files/open` (returns download URL on web)
- folders list/create

---

## Config & data layout

Environment (Compose / `.env`):

- `OPENROUTER_API_KEY` (required)
- `OPENROUTER_MODEL`, `OPENROUTER_TEMPERATURE`, site URL/name
- `DEEPAGENT_WORKDIR` / `CODEX_GUI_WORKSPACE` → `/workspace`
- `DEEPAGENT_DATA_DIR` → `/app/data`
- `DEEPAGENT_NETWORK_ACCESS` (sandbox outbound; default false)
- `DEEPAGENT_MCP_ENABLED`
- `IRESEARCHER_MCP_URL`, `IRESEARCHER_MCP_BEARER_TOKEN`

On disk under data dir (after migrate / use):

- `settings.json`, `secrets.json`
- `.mcp.json` (writable API edits; empty skipped when reading)
- `app.sqlite` (sessions / runs / events / messages)
- LangGraph checkpoint DB (unchanged thread-id story when sessions import)

MCP read order: data-dir `.mcp.json` (non-empty) → project `.mcp.json` →
`.deepagents/.mcp.json`. Compose mounts host `./.mcp.json` and seeds data dir.

---

## Docker / VPS

```bash
git fetch origin && git checkout main && git pull origin main
# keep existing .env, workspace/, data/
docker compose up -d --build
# GUI: http://<host>:8011
```

Image includes: bubblewrap, Chromium, officecli, Node, chrome-devtools-axi.
Compose sets `apparmor:unconfined` + `seccomp:unconfined` for nested user
namespaces. See `reference_sandboxing.md` for bwrap troubleshooting.

macOS/Windows hosts: use Compose only — Bubblewrap is Linux namespaces.

---

## Automatic migrate (existing installs)

On first start after upgrade:

1. Copy legacy `.env` into `settings.json` / `secrets.json` if settings absent.
2. Keep reading repo `.mcp.json`; API writes go to data-dir `.mcp.json`.
3. Import `sessions.json` into `app.sqlite` preserving session IDs (checkpoint continuity).

No manual data rewrite required for the common Compose layout.

---

## Intentionally not in this land

- Tauri shell, sidecar, updater, desktop packaging
- Microsandbox / guest baking on web
- Multi-tenant auth / per-user isolation
- Compatibility shim for old `chat/stream`
- code-wiki / wiki polish (deferred)

---

## Verification checklist

- [ ] `docker compose up -d --build` → `GET /health` ok
- [ ] UI at `:8011`; settings + MCP pages load
- [ ] MCP tools visible when `.mcp.json` / data config is non-empty (e.g. iresearcher, context7)
- [ ] Chat creates a run; SSE events; cancel works
- [ ] Workspace file download via `/files/download`
- [ ] Optional: officecli / HTML screenshot inside a session on Linux Compose

---

## Related docs

- [upgrade-web-tier1.md](./upgrade-web-tier1.md) — short operator upgrade notes
- [../README.md](../README.md) — day-to-day setup
- [../agents/protocol.md](../agents/protocol.md) — pipeline handoff contract
- [../reference_sandboxing.md](../reference_sandboxing.md) — Bubblewrap / namespace issues
