# Tier-1 web upgrade

Full implementation record (decisions, architecture, API, out-of-scope):
[web-migration-implementation.md](./web-migration-implementation.md).

Existing installs migrate automatically on first web start:

- Legacy `.env` values are copied into `DEEPAGENT_DATA_DIR/settings.json` and
  `secrets.json` when `settings.json` does not exist.
- Repository `.mcp.json` remains readable; API edits are saved to
  `DEEPAGENT_DATA_DIR/.mcp.json`. Empty data-dir `mcpServers` are skipped so a
  seeded repo `.mcp.json` still loads.
- Legacy `sessions.json` entries are imported into `app.sqlite` with their
  original session IDs, so matching LangGraph checkpoint thread IDs continue
  to work.

```bash
git pull origin main
docker compose up -d --build
# open http://localhost:8011 (or http://<vps-ip>:8011)
```

The web API now uses background runs and resumable SSE instead of a
connection-owned chat stream. Bubblewrap requires Linux, so macOS and Windows
users should use Docker Compose rather than launching the sandbox directly on
the host.

## Tier-2 tooling

The Compose image now includes Chromium and ``officecli`` for HTML QA
(``inspect_html`` / ``screenshot_html`` / ``bundle_html``) and Office
deliverables. Chromium HTML QA runs on the app container host (not inside
bwrap). Bundled skills under ``skills/`` (grillme, officecli,
chrome-devtools-axi) are copied into the workspace on agent start.
