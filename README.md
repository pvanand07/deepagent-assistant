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
  default) — see the note in `src/bubblewrap_sandbox.py` about pairing this
  with `systemd-run --scope` + cgroups v2 for hard quota enforcement under
  untrusted/adversarial load.

## Files

| Path                    | Purpose                                                        |
|-------------------------|-----------------------------------------------------------------|
| `src/bubblewrap_sandbox.py` | `BubblewrapSandbox` — the sandboxed backend (`BaseSandbox` impl) |
| `src/openrouter_model.py`   | Builds a `ChatOpenAI` client pointed at OpenRouter               |
| `src/agent.py`              | Wires model + sandbox into a `deepagents` agent (+ example sub-agent) |
| `src/cli.py`                | Interactive terminal chat loop (token-level streaming)          |
| `src/streaming.py`          | Reusable `stream_agent_turn()` helper for v2 message streaming  |
| `src/api.py`                | FastAPI HTTP API for the web GUI                                |
| `frontend/`             | Static HTML/CSS/JS GUI                                          |
| `Dockerfile`            | Linux runtime image with bubblewrap and CLI tools               |
| `docker-compose.yml`    | Runs the agent with namespace-friendly security opts            |
| `workspace/`            | Host directory mounted as the agent's writable `/workspace`   |

## Docker (recommended on Windows/macOS)

Bubblewrap needs Linux user namespaces. On Windows and macOS, run the agent
inside Docker instead of on the host. Docker Desktop (or any Docker engine with
Compose v2) is required.

### Quick start

```bash
# 1. Configure OpenRouter (compose reads .env automatically)
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY

# 2. Build and start the interactive REPL
docker compose up --build
```

Inside the container you get the same `src/cli.py` REPL as native Linux. Type your
request, `/reset` to clear history, or `exit` to quit.

### Workspace

Agent files are written to `./workspace` on your host, mounted read-write at
`/workspace` inside the container. The sandbox persists across container
restarts — only conversation history resets when you quit or run `/reset`.

### Network access

By default the sandbox has **no** outbound network (same as native `src/cli.py`).
To allow pip, curl, git clone, etc., either:

```bash
# one-off
DEEPAGENT_NETWORK_ACCESS=true docker compose up --build

# or add to .env
DEEPAGENT_NETWORK_ACCESS=true
```

You can also pass `--network` when invoking `src/cli.py` directly inside the
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
docker compose run --rm deepagent python src/cli.py --model "openai/gpt-5"
docker compose run --rm deepagent python src/cli.py --network
```

Use `docker compose up` for an attached interactive session; use
`docker compose run --rm` for one-off commands.

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

# 2. Install Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure your OpenRouter key
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY

# 4. Run (set PYTHONPATH so imports resolve from src/)
export PYTHONPATH=src
python src/cli.py
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
python src/cli.py                                  # default model, no network
python src/cli.py --model "openai/gpt-5"           # pick a different OpenRouter model
python src/cli.py --network                        # allow the sandbox outbound internet
python src/cli.py --workdir /home/me/agent-scratch # persist the sandbox workspace across runs
```

Inside the REPL:
- Type any request — the agent can write files, run shell commands, install
  packages (if `--network` is on), run tests, etc., all inside `/workspace`.
- `/reset` clears conversation history (sandbox files are untouched).
- `exit` or Ctrl-D quits and cleans up the sandbox's temp workdir (unless
  you passed `--workdir`, which is never deleted automatically).

## Using it as a library

```python
from agent import build_agent
from streaming import stream_agent_turn

# Run with PYTHONPATH=src (or from a shell where src/ is on PYTHONPATH)
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

- **Sub-agents**: edit `SUBAGENTS` in `src/agent.py` (see the `code-reviewer`
  example) to add more predefined, on-demand specialist agents — this
  follows the same task-delegation pattern as
  [`deep-agents-from-scratch`](https://github.com/langchain-ai/deep-agents-from-scratch).
- **Resource limits**: `BubblewrapSandbox(rlimit_as_mb=..., rlimit_nproc=...)`
  in `src/agent.py`.
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
