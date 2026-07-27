# Tier-1 web upgrade

Existing installs migrate automatically on first web start:

- Legacy `.env` values are copied into `DEEPAGENT_DATA_DIR/settings.json` and
  `secrets.json` when `settings.json` does not exist.
- Repository `.mcp.json` remains readable; API edits are saved to
  `DEEPAGENT_DATA_DIR/.mcp.json`.
- Legacy `sessions.json` entries are imported into `app.sqlite` with their
  original session IDs, so matching LangGraph checkpoint thread IDs continue
  to work.

Run `docker compose up -d --build`, then open `http://localhost:8011`. The web
API now uses background runs and resumable SSE instead of a connection-owned
chat stream. Bubblewrap requires Linux, so macOS and Windows users should use
Docker Compose rather than launching the sandbox directly on the host.
