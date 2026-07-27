# Sandboxed Deep Agent (bubblewrap + OpenRouter)

A `deepagents` agent whose filesystem and shell tools (`ls`, `read_file`,
`write_file`, `edit_file`, `glob`, `grep`, `execute`) run inside a
[bubblewrap](https://github.com/containers/bubblewrap) namespace jail
instead of directly on your machine, using any tool-calling model on
[OpenRouter](https://openrouter.ai) as the LLM.

## What's isolated

Every `execute()` call (and everything the file tools do under the hood)
runs in a fresh `bwrap` sandbox with:

- **Its own mount namespace** — only the sandbox's own workdir is writable
  (mounted at `/workspace`); the rest of your filesystem is invisible, not
  just "denied."
- **Its own network namespace** — no network access at all by default
  (`--network` flag to opt in).
- **Its own PID namespace** — can't see or signal host processes.
- **An unprivileged user namespace** — no real privilege escalation path.
- **Best-effort memory/process `ulimit` caps** (1024MB / 64 procs by
  default) — see the note in `src/deep_agent/sandbox/bubblewrap.py` about
  pairing this with `systemd-run --scope` + cgroups v2 for hard quota
  enforcement under untrusted/adversarial load.

## Files

| Path | Purpose |
|------|---------|
| `src/deep_agent/sandbox/` | Bubblewrap backend + `SandboxBackend` / manager seam |
| `src/deep_agent/settings/` | JSON settings/secrets (dual-read from legacy `.env`) |
| `src/deep_agent/integrations/` | MCP + multi-provider LLM catalog |
| `src/deep_agent/chat/` | Sessions, background runs, resumable SSE |
| `src/deep_agent/persistence/` | SQLite AppDB + LangGraph checkpoints |
| `src/deep_agent/api/app.py` | FastAPI HTTP API for the web GUI |
| `src/deep_agent/agent_factory.py` | Wires model + sandbox + skills into the agent |
| `agents/` | Research → plan → build pipeline (`source.md` / `spec.md` / `output/`) |
| `skills/grillme/` | Bundled skill loaded into the workspace |
| `pyproject.toml` / `uv.lock` | Python dependencies (managed with [uv](https://docs.astral.sh/uv/)) |
| `frontend/` | Vue static GUI (chat, settings, MCP) |
| `Dockerfile` / `docker-compose.yml` | Linux Bubblewrap runtime |
| `docs/upgrade-web-tier1.md` | Upgrade notes for existing installs |
| `workspace/` | Host directory mounted as `/workspace` |

## Docker (recommended on Windows/macOS)

Bubblewrap needs Linux user namespaces. On Windows and macOS, run the agent
inside Docker instead of on the host. Docker Desktop (or any Docker engine with
Compose v2) is required.

Existing installations: see [Tier-1 web upgrade](docs/upgrade-web-tier1.md) for
the automatic settings, MCP, and session migration behavior.

### Quick start

```bash
# 1. Configure OpenRouter (compose reads .env automatically)
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY

# 2. Build and start the web API (default)
docker compose up -d --build

# Open http://localhost:8011 for the GUI.

# Optional: interactive terminal REPL
docker compose run --rm cli
```

Inside the CLI container, type your request, `/reset` to clear history, or `exit` to quit.

### Workspace

Agent files are written to `./workspace` on your host, mounted read-write at
`/workspace` inside the container. The sandbox persists across container
restarts — only conversation history resets when you quit or run `/reset`.

### Network access

By default the sandbox has **no** outbound network (same as native CLI).
To allow pip, curl, git clone, etc., either:

```bash
# one-off
DEEPAGENT_NETWORK_ACCESS=true docker compose up -d --build

# or add to .env
DEEPAGENT_NETWORK_ACCESS=true
```

You can also pass `--network` when invoking `python -m deep_agent.cli` inside the
container (overrides the env var).

### Configuration

Compose passes these from your `.env` file:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | Required. Your OpenRouter API key |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4.5` | Model id |
| `OPENROUTER_TEMPERATURE` | `0.3` | Sampling temperature |
| `DEEPAGENT_NETWORK_ACCESS` | `false` | Allow outbound network in the sandbox |

Model and flags can also be passed at runtime:

```bash
docker compose run --rm cli python -m deep_agent.cli --model "openai/gpt-5"
docker compose run --rm cli python -m deep_agent.cli --network
```

Use `docker compose up -d` for the API in the background; use
`docker compose run --rm cli` for an interactive terminal session.

### How it works

The compose file:

- mounts `./workspace` → `/workspace` (writable sandbox root)
- sets `security_opt: apparmor:unconfined, seccomp:unconfined` so `bwrap` can
  create user namespaces inside the container
- installs bubblewrap in the image (`Dockerfile`)

See `reference_sandboxing.md` for troubleshooting (namespace errors, network
issues, `BWRAP_SETUID` rebuild arg).

## Setup (native Linux)

```bash
# 1. Install bubblewrap (Debian/Ubuntu shown; see below for other distros)
sudo apt-get update && sudo apt-get install -y bubblewrap

# 2. Install Python deps ([uv](https://docs.astral.sh/uv/))
uv sync

# 3. Configure your OpenRouter key
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY

# 4. Run CLI or API (PYTHONPATH so imports resolve from src/)
export PYTHONPATH=src
uv run python -m deep_agent.cli
# or: uv run uvicorn deep_agent.api.app:app --host 127.0.0.1 --port 8010
```

Other distros:
- Fedora/RHEL: `sudo dnf install bubblewrap`
- Arch: `sudo pacman -S bubblewrap`
- macOS: bubblewrap is Linux-only (needs Linux user namespaces). Run this
  inside a Linux VM/container (Docker Desktop's Linux VM, Lima, WSL2, etc.)
- WSL2: works the same as native Linux, install via apt inside WSL

## Usage (native Linux)

```bash
export PYTHONPATH=src
uv run python -m deep_agent.cli                                  # default model, no network
uv run python -m deep_agent.cli --model "openai/gpt-5"           # pick a different OpenRouter model
uv run python -m deep_agent.cli --network                        # allow the sandbox outbound internet
uv run python -m deep_agent.cli --workdir /home/me/agent-scratch # persist workspace across runs
```

Inside the REPL:
- Type any request — the agent can write files, run shell commands, install
  packages (if `--network` is on), run tests, etc., all inside `/workspace`.
- `/reset` clears conversation history (sandbox files are untouched).
- `exit` or Ctrl-D quits and cleans up the sandbox's temp workdir (unless
  you passed `--workdir`, which is never deleted automatically).

## Using it as a library

```python
from deep_agent.agent_factory import build_agent
from deep_agent.chat.streaming import stream_agent_turn

# Run with PYTHONPATH=src (or `uv run` from the repo)
agent, sandbox, mcp_meta = build_agent(model_name="anthropic/claude-sonnet-4.5", network=False)
history = [{"role": "user", "content": "Write and run a fibonacci script"}]
history = stream_agent_turn(agent, history)  # token-level streaming to stdout
sandbox.cleanup()
```

For a one-shot result without streaming:

```python
result = agent.invoke({"messages": history})
print(result["messages"][-1].content)
```

## Customizing

- **Sub-agents**: edit TOMLs under `agents/` (loaded by `agent_factory.py`).
- **Resource limits**: `BubblewrapSandbox(rlimit_as_mb=..., rlimit_nproc=...)`
  in `agent_factory.py`.
- **Extra read-only mounts** (e.g. to expose a shared dataset dir):
  `BubblewrapSandbox(extra_ro_binds=["/path/on/host"])`.
- **Model**: any tool-calling model id from https://openrouter.ai/models,
  via `--model` or `OPENROUTER_MODEL` in `.env`.

## Security notes

- This is real OS-level isolation (Linux namespaces), not just a "best
  practice" wrapper — verified filesystem/network/PID isolation, see the
  chat history this was built in for live test output.
- It is **not** a substitute for running on a disposable VM/container if
  you're executing fully untrusted, adversarial code at scale — bubblewrap
  has no built-in cgroup resource accounting, so a determined adversary
  could still exhaust host CPU/memory before ulimits kick in under
  concurrent load. For that threat model, wrap the whole thing in
  `systemd-run --scope -p MemoryMax=... -p CPUQuota=...` or run it inside
  its own VM.
