# Deep Agent — project conventions

Agent-facing notes. Prefer `wiki/` and code for depth.

## Config

- Source of truth: `DEEPAGENT_DATA_DIR/settings.json` plus `secrets.json`.
- On first boot, `.env` is imported into those files; process environment remains an override.
- MCP uses the persisted data-dir `.mcp.json`, falling back to the repository `.mcp.json`.

## Sandbox

- Shared Bubblewrap sandbox rooted at `/workspace`; Docker supplies Linux user namespaces.
- The only bundled skill is `skills/grillme/`; no Office or Chromium tooling is installed.
- Sandbox setting changes recreate the Bubblewrap backend. Check `GET /api/config` for status.

## Dev run

```powershell
$env:PYTHONPATH = "src"
uv run uvicorn deep_agent.api.app:app --host 127.0.0.1 --port 8010 --reload
```

## Other

- Task workspace rules: `agents/AGENT.md`.
- Durable architecture updates: `wiki/` (`.cursor/skills/code-wiki/`).
