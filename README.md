# Sandboxed Deep Agent (microsandbox + OpenRouter)

A `deepagents` agent whose filesystem and shell tools (`ls`, `read_file`,
`write_file`, `edit_file`, `glob`, `grep`, `execute`) run inside a
[microsandbox](https://github.com/superradcompany/microsandbox) microVM
instead of directly on your machine, using any tool-calling model on
[OpenRouter](https://openrouter.ai) as the LLM.

Designed as a **native desktop** app for Linux, Windows, and macOS (hardware
virtualization required). See [docs/microsandbox-migration.md](docs/microsandbox-migration.md)
for the architecture decisions.

## What's isolated

One shared microVM per app process:

- **Hardware-isolated guest** (libkrun) with its own kernel view
- **Host workspace bind-mounted** at `/workspace` (all chats share it)
- **App-wide network policy** — `Network.none()` by default, or
  `Network.public_only()` when `DEEPAGENT_NETWORK_ACCESS=true`
- **Serialized exec** across chats (agent can wait / ask before cancel)
- **Resource caps** via microsandbox memory/CPU settings (defaults 1024 MiB / 2 vCPUs)

## Files

| Path | Purpose |
|------|---------|
| `src/sandbox_manager.py` | App-scoped VM lifecycle, exec lock, command logs |
| `src/microsandbox_sandbox.py` | `BaseSandbox` impl (async `aexecute`, host-direct files) |
| `src/sandbox_tools.py` | `sandbox_status` / `sandbox_wait` / `cancel_sandbox_holder` |
| `src/agent.py` | Wires model + sandbox + MCP + subagents |
| `src/api.py` | FastAPI HTTP API for the web GUI |
| `src/cli.py` | Interactive terminal chat loop |
| `Dockerfile.sandbox` | Guest OCI image definition (dev build / release pull) |
| `frontend/` | Static HTML/CSS/JS GUI |
| `workspace/` | Host directory mounted as `/workspace` |
| `docs/microsandbox-migration.md` | Agreed migration design |

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Hardware virtualization:
  - **Linux:** KVM (`/dev/kvm`)
  - **macOS:** Apple Silicon
  - **Windows:** Windows Hypervisor Platform (WHP)
- Docker (or another OCI builder) **only** to build the guest image locally

## Quick start

```bash
# 1. Install Python deps
uv sync --group dev

# 2. Configure OpenRouter
cp .env.example .env
# edit .env → OPENROUTER_API_KEY

# 3. Ensure microsandbox runtime (first time)
uv run python -c "import asyncio; from microsandbox import install, is_installed; \
asyncio.run(install() if not is_installed() else asyncio.sleep(0)); print('runtime ok')"
# Optional: msb doctor

# 4. Run the API + GUI (default guest image: python:3.12-slim, pulled on first start)
mkdir -p workspace data
DEEPAGENT_WORKDIR="$PWD/workspace" PYTHONPATH=src uv run uvicorn api:app --host 127.0.0.1 --port 8010
# Open http://127.0.0.1:8010
```

CLI:

```bash
DEEPAGENT_WORKDIR="$PWD/workspace" PYTHONPATH=src uv run python src/cli.py
```

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | Required |
| `OPENROUTER_MODEL` | `anthropic/claude-sonnet-4.5` | Model id |
| `DEEPAGENT_WORKDIR` | `./workspace` | Host path bind-mounted at `/workspace` |
| `DEEPAGENT_NETWORK_ACCESS` | `false` | Guest egress (`none` vs `public_only`) |
| `DEEPAGENT_SANDBOX_IMAGE` | `python:3.12-slim` | Guest OCI image (Docker Hub by default) |
| `DEEPAGENT_SANDBOX_MEMORY` | `1024` | MiB |
| `DEEPAGENT_SANDBOX_CPUS` | `2` | vCPUs |
| `DEEPAGENT_SANDBOX_IDLE_TIMEOUT` | `300` | Auto-stop unused VM (seconds; `0` = never) |
| `DEEPAGENT_SANDBOX_LOCK_WAIT` | `120` | Default exec-lock wait (agent can override) |
| `DEEPAGENT_EXEC_TIMEOUT` | `120` | Default command timeout (`0` = none) |
| `DEEPAGENT_SANDBOX_BACKEND` | `microsandbox` | Set `stub` for tests without a VM |
| `DEEPAGENT_MSB_INTEGRATION` | unset | Set `1` to run real-VM integration tests |

## Guest image

- **Default:** `python:3.12-slim` (pulled from Docker Hub on first sandbox create)
- **Optional custom:** build `Dockerfile.sandbox`, load into msb, set `DEEPAGENT_SANDBOX_IMAGE`:

```bash
docker build -f Dockerfile.sandbox -t deepagent-workspace:dev .
docker save deepagent-workspace:dev | msb load --tag deepagent-workspace:dev
export DEEPAGENT_SANDBOX_IMAGE=deepagent-workspace:dev
```

## Exec output

- Tool results include the **last 100 lines** of stdout/stderr
- Full output is written under `/workspace/.deepagent/logs/` (retained ~7 days / 100 MB)

## Tests

```bash
# Default E2E uses StubSandbox (no VM)
DEEPAGENT_SANDBOX_BACKEND=stub PYTHONPATH=src uv run pytest

# Optional real microsandbox integration (requires virt + guest image)
DEEPAGENT_MSB_INTEGRATION=1 PYTHONPATH=src uv run pytest tests/test_msb_integration.py
```

## Security notes

- Isolation is a **microVM**, stronger than process namespaces alone.
- LLM/MCP credentials stay on the host; nothing is injected into the guest in v1.
- Parallel chats share one workspace and one VM; exec is serialized to avoid races.
- Fail-hard at startup if virtualization/runtime is unavailable (no unsandboxed fallback).

## License / redistribution

See [docs/LICENSES.md](docs/LICENSES.md) for microsandbox / libkrun / libkrunfw obligations.
