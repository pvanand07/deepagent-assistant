# Deep Agent — project conventions

Agent-facing notes. Prefer `wiki/` and code for depth.

## Config

- Source of truth: `data/settings.json` + `data/secrets.json` (AppData data dir in desktop mode).
- Do **not** put LLM/sandbox prefs in `.env` — ignored after migration. Process env overrides only for CI/tests.
- New installs seed from `default_settings()` using `DEFAULT_*` in `src/deep_agent/sandbox/config.py`.

## Sandbox

- Shared microsandbox microVM (`deepagent`), not Docker Compose/bubblewrap.
- Default guest image: `pvanand09/deepagent-workspace:latest` (`DEFAULT_IMAGE`). Override with `sandbox.image` in settings.
- Host workdir at `/workspace` (host file I/O; guest shell). Exec is serialized across runs.
- Sandbox setting changes (image, memory, CPUs, network, DNS, idle) recreate the VM — restart API or save Settings; verify `GET /api/config` → `sandbox_status.image`.
- Degraded virt: chat/MCP only; `POST /api/sandbox/retry`. Stub (`DEEPAGENT_SANDBOX_BACKEND=stub`) is for tests only.

### Build / push guest image

```powershell
docker build -f Dockerfile.sandbox -t pvanand09/deepagent-workspace:latest .
docker push pvanand09/deepagent-workspace:latest
```

Then recreate the VM so microsandbox pulls new layers. Local-only tags: `docker save … | msb load` (see `Dockerfile.sandbox`).

## Dev run

```powershell
$env:PYTHONPATH = "src"
uv run uvicorn deep_agent.api.app:app --host 127.0.0.1 --port 8010 --reload
```

## Other

- Task workspace rules: `agents/AGENT.md`.
- Durable architecture updates: `wiki/` (`.cursor/skills/code-wiki/`).
