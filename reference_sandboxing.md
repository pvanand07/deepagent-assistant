---
name: ""
metadata: 
  node_type: memory
  originSessionId: d0222d6a-60e6-4604-affa-69a0a0c669e8
---

# Codex-v2 Sandboxing — Agent Setup Reference

Reference guide for running Codex agents with sandboxed shell commands inside the Codex-v2 Docker container. Enable process isolation via bubblewrap, workspace write access, and optional network access.

## What sandboxing enables

| Layer | Mechanism |
|-------|-----------|
| Codex sandbox mode | `Sandbox.workspace_write` — agent can read/write inside cwd, shell runs isolated |
| Process isolation | **bubblewrap** (`bwrap`) — Linux user namespaces + bind mounts |
| Network in sandbox | `sandbox_workspace_write.network_access=true` (config + env override) |
| Workspace trust | `trust_level = "trusted"` in `config.toml` for the workspace path |
| Container host | Docker with relaxed AppArmor/seccomp so `bwrap` can create namespaces |

Without bubblewrap inside the container **and** the docker-compose security options, agents cannot launch sandboxed commands.

---

## Implementation checklist

- [ ] **Dockerfile** installs `bubblewrap` and required CLI tools (git, curl, ripgrep, etc.)
- [ ] **docker-compose.yml** sets `security_opt: apparmor:unconfined, seccomp:unconfined`
- [ ] **docker-compose.yml** mounts `/app` → container `/app` for live agent workspace
- [ ] **docker-compose.yml** mounts `codex-home/` → `CODEX_HOME` for auth/config
- [ ] **docker-compose.yml** sets `CODEX_GUI_WORKSPACE`, `CODEX_HOME`, `CODEX_GUI_NETWORK_ACCESS` env vars
- [ ] **codex-home/config.toml** includes `[sandbox_workspace_write]` block with `network_access = true`
- [ ] **codex-home/config.toml** marks `/app` workspace as `trust_level = "trusted"`
- [ ] **Agent backend** starts threads with `Sandbox.workspace_write` (not read-only)
- [ ] **Agent backend** does NOT pass `sandbox=` on subsequent `thread.turn()` calls
- [ ] **Agent backend** passes `sandbox_workspace_write.network_access=true` via `CodexConfig.config_overrides` when needed
- [ ] **Verify** — run `echo ok && pwd` inside a chat turn; expect sandbox execution in `/app`

---

## Dockerfile additions

In the runtime stage (Python image), install bubblewrap and CLI dependencies:

```dockerfile
ARG BWRAP_SETUID=0

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bash \
    bubblewrap \
    ca-certificates \
    curl \
    git \
    ripgrep \
  && rm -rf /var/lib/apt/lists/*

# Only when host blocks unprivileged user namespaces (rare; see troubleshooting)
RUN if [ "$BWRAP_SETUID" = "1" ]; then chmod u+s /usr/bin/bwrap; fi

ENV CODEX_HOME=/root/.codex
ENV CODEX_GUI_WORKSPACE=/app
```

---

## docker-compose.yml updates

Update `codex-service` (or your service name) with security opts and environment:

```yaml
services:
  codex-service:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        BWRAP_SETUID: "0"
    ports:
      - "8004:8000"
    environment:
      CODEX_HOME: /root/.codex
      CODEX_GUI_WORKSPACE: /app
      CODEX_GUI_NETWORK_ACCESS: "true"
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    volumes:
      - ./app:/app
      - ./codex-home:/root/.codex
    security_opt:
      - apparmor:unconfined
      - seccomp:unconfined
    restart: unless-stopped
```

**Required lines:**
- `security_opt: apparmor:unconfined, seccomp:unconfined` — allows user namespaces inside container
- `./app:/app` — agent workspace (cwd for sandboxed commands)
- `./codex-home:/root/.codex` — Codex auth, sessions, config
- `CODEX_GUI_NETWORK_ACCESS: "true"` — enables pip/npm/curl/git inside sandbox

---

## codex-home/config.toml (minimal)

Create or update `codex-home/config.toml`:

```toml
[sandbox_workspace_write]
network_access = true

[projects."/app"]
trust_level = "trusted"
```

Note: `projects` is a map keyed by workspace path (`HashMap<String, ProjectConfig>` in `codex-rs/config/src/config_toml.rs`), not an array — `[[projects]]` fails with `invalid type: sequence, expected a map`.

Add authentication, provider keys, and MCP sections as your agent implementation requires.

---

## Backend implementation (Python async)

### Thread initialization

Always use `Sandbox.workspace_write` when starting a thread:

```python
from openai_codex import AsyncCodex, CodexConfig, Sandbox
import os

DEFAULT_SANDBOX = Sandbox.workspace_write

def build_codex_config(cwd: str) -> CodexConfig:
    overrides: list[str] = []
    if os.environ.get("CODEX_GUI_NETWORK_ACCESS", "true").lower() in {"1", "true", "yes"}:
        overrides.append("sandbox_workspace_write.network_access=true")
    return CodexConfig(
        cwd=cwd,
        client_name="codex_v2",
        config_overrides=tuple(overrides),
    )

# On session/thread start:
config = build_codex_config("/app")
thread = await codex.thread_start(config, model, sandbox=DEFAULT_SANDBOX)
```

### Chat turns

**Do NOT pass `sandbox=` on subsequent turns.** This resets network_access and breaks networked commands:

```python
# Correct — sandbox config persists from thread_start
turn = await thread.turn(message, model=model_id)

# Wrong — overrides network_access to false
turn = await thread.turn(message, sandbox=Sandbox.workspace_write)
```

---

## Project layout

```
codex-v2/
├── app/                 # mounted → /app (agent workspace)
│   ├── main.py          # entry point
│   └── [agent code]
├── codex-home/          # mounted → /root/.codex (config, auth)
│   └── config.toml
├── Dockerfile           # includes bubblewrap install
├── docker-compose.yml   # security_opt + volumes
└── .gitignore           # excludes .env, codex-home/sessions/*
```

---

## Troubleshooting

### Agent commands fail with "bwrap" or namespace errors

1. Verify bubblewrap is installed:
   ```sh
   docker compose exec codex-service which bwrap
   ```
2. Confirm `security_opt: apparmor:unconfined, seccomp:unconfined` in compose.
3. Rebuild the image:
   ```sh
   docker compose up --build codex-service
   ```

### `bwrap: Can't mount proc on /newroot/proc: Operation not permitted`

This happens when bubblewrap runs **inside** a Docker container and tries to
mount a fresh procfs with `--proc /proc`. Linux denies that nested mount even
with `security_opt` relaxed.

**Fix (deepagent-assistant):** `BubblewrapSandbox` uses `--ro-bind /proc /proc`
instead of `--proc`. Rebuild and restart after updating:

```sh
docker compose up --build api
```

Symptoms when unfixed: every `execute`, `ls`, `grep`, `glob`, and `write_file`
call fails with the proc mount error (writes that only use `upload_files` may
still partially work, but `write_file` runs a preflight check via `execute`).

### Network fails inside sandbox (pip, curl, git clone)

- Verify `CODEX_GUI_NETWORK_ACCESS=true` in docker-compose environment
- Verify `[sandbox_workspace_write] network_access = true` in config.toml
- **Do not** pass `sandbox=` on `thread.turn()` — it resets the setting
- Restart the container to reload config

### Agent cannot write files

- Ensure `[[projects]]` with `path = "/app"` and `trust_level = "trusted"` in config.toml
- Confirm agent cwd is `/app` (inside the mounted volume)
- Confirm `Sandbox.workspace_write` (not read-only) on thread start

### Works in Docker, fails on bare host (Windows/macOS)

Local development on Windows/macOS **does not** support bubblewrap or user namespaces. Run agents inside Docker. For UI-only dev, run frontend locally and point it at the Docker backend.

---

## Verification steps

After `docker compose up --build`:

1. Start a chat session in the agent
2. Ask the agent to run: `echo sandbox-ok && pwd`
3. Expect: output contains `/app` and success status
4. Optional network test: `curl -fsSL https://example.com | head -1` (requires `CODEX_GUI_NETWORK_ACCESS=true`)

If tests fail, check container logs for `bwrap` errors before modifying code.

---

## Environment variables reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `CODEX_HOME` | `/root/.codex` | Codex config, auth, session history |
| `CODEX_GUI_WORKSPACE` | `/app` | Sandbox workspace root and default cwd |
| `CODEX_GUI_NETWORK_ACCESS` | `true` | Enable network inside workspace_write sandbox |
| `BWRAP_SETUID` (build arg) | `0` | Set to `1` only if host blocks user namespaces |
