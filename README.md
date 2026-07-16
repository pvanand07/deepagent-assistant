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
| `src/deep_agent/sandbox/` | MicroVM lifecycle, backend adapter, configuration, paths, and sandbox tools |
| `src/deep_agent/chat/` | Sessions, runs, stream events, and message summaries |
| `src/deep_agent/api/` | FastAPI application and API models |
| `src/deep_agent/integrations/` | MCP loading and model-provider integration |
| `src/deep_agent/persistence/` | SQLite checkpoints, session metadata, messages, and event storage |
| `src/deep_agent/agent_factory.py` | Wires model, sandbox, MCP, and subagents |
| `src/deep_agent/cli.py` | Interactive terminal chat loop |
| `Dockerfile.sandbox` | Guest OCI image definition (dev build / release pull) |
| `frontend/` | Static HTML/CSS/JS GUI (served by FastAPI) |
| `desktop-stub/` | Tauri boot chrome only (“Starting Deep Agent…”) |
| `src-tauri/` | Tauri 2 shell (sidecar spawn, menu, single-instance) |
| `workspace/` | Host directory mounted as `/workspace` |
| `docs/microsandbox-migration.md` | Agreed migration design |
| `docs/tauri-migration.md` | Tauri desktop shell plan |

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
DEEPAGENT_WORKDIR="$PWD/workspace" PYTHONPATH=src uv run uvicorn deep_agent.api.app:app --host 127.0.0.1 --port 8010
# Open http://127.0.0.1:8010
```

CLI:

```bash
DEEPAGENT_WORKDIR="$PWD/workspace" PYTHONPATH=src uv run python -m deep_agent.cli
```

## Desktop shell (Tauri)

Browser + `uvicorn` and the CLI remain supported for daily debug. Use Tauri when working on
the native shell (window, menu, sidecar lifecycle). See [docs/tauri-migration.md](docs/tauri-migration.md)
and [docs/macos-packaging.md](docs/macos-packaging.md) (macOS arm64 DMG + dual-OS CI).

```bash
# One-time: Node deps for the shell
pnpm install

# Dev: Tauri spawns uvicorn (prefers `uv run`) on 127.0.0.1:8010 (+ fallback),
# waits for /health, then navigates the WebView to the API UI.
pnpm tauri dev

# Packaged release build (platform-aware)
pnpm build:release
# Windows: embeddable CPython sidecar → NSIS + portable zip
# macOS arm64: relocatable CPython sidecar → DMG
# Or step-by-step:
#   pnpm package:sidecar
#   pnpm exec tauri build --bundles nsis   # Windows
#   pnpm exec tauri build --bundles dmg    # macOS
#   pnpm package:portable                  # Windows only
#   pnpm package:smoke                     # import deep_agent.api.app:app + /health
```

**CI:** GitHub Actions → **Desktop build (unsigned)** (`workflow_dispatch`) builds Windows +
macOS and publishes a prerelease tagged `unsigned-YYYYMMDD-HHMM`.

**Artifacts (unsigned):**

| Artifact | Path / name |
|----------|-------------|
| NSIS installer | `src-tauri/target/release/bundle/nsis/…setup.exe` → CI: `Deep-Agent-0.1.0-windows-x64-setup.exe` |
| Portable zip | `src-tauri/target/release/bundle/portable/Deep-Agent-0.1.0-windows-x64-portable.zip` |
| macOS DMG | `src-tauri/target/release/bundle/dmg/…dmg` → CI: `Deep-Agent-0.1.0-macos-arm64.dmg` |

`sidecar/` is generated and gitignored (except `sidecar/README.md`). Re-run `pnpm package:sidecar`
after dependency or app-source changes before a release build.

**Dev vs packaged spawn:** `tauri dev` uses `uv run uvicorn` (or system Python). Release builds
spawn bundled sidecar Python (`python.exe` on Windows, `bin/python3` on macOS) with
`DEEPAGENT_DESKTOP=1`, platform data dir, Documents workspace, and `PYTHONPATH` → bundled `src`.

**Unsigned macOS:** Gatekeeper will warn. For internal testing see
[docs/macos-packaging.md](docs/macos-packaging.md) (quarantine / manual checks). Notarization is deferred.
## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEPAGENT_LLM_PROVIDER` | `openrouter` | `openrouter` \| `ollama` \| `custom` |
| `DEEPAGENT_LLM_BASE_URL` | provider default | OpenAI-compatible base URL (required for `custom`) |
| `OPENROUTER_API_KEY` | — | API key (optional for Ollama) |
| `OPENROUTER_MODEL` | provider default | Model id |
| `DEEPAGENT_WORKDIR` | `./workspace` | Host path bind-mounted at `/workspace` |
| `DEEPAGENT_NETWORK_ACCESS` | `false` | Guest egress (`public_only` vs `none`) |
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

The custom guest image also includes Chromium, Node.js/npm, and the
`chrome-devtools-axi` browser automation CLI with its `chrome-devtools-mcp`
bridge dependency. The bundled Agent Skill is copied to
`/workspace/skills/chrome-devtools-axi/` on sandbox startup. Browser access to
external sites still requires enabling sandbox network access; the default
remains network-disabled.

## Exec output

- Tool results include the **last 100 lines** of stdout/stderr
- Full output is written under `/workspace/.deepagent/logs/` (retained ~7 days / 100 MB)

## Tests

```bash
# Default E2E uses StubSandbox (no VM)
DEEPAGENT_SANDBOX_BACKEND=stub PYTHONPATH=src uv run pytest

# Optional real microsandbox integration (requires virt + guest image)
DEEPAGENT_MSB_INTEGRATION=1 PYTHONPATH=src uv run pytest tests/sandbox/test_integration.py
```

## Security notes

- Isolation is a **microVM**, stronger than process namespaces alone.
- LLM/MCP credentials stay on the host; nothing is injected into the guest in v1.
- Parallel chats share one workspace and one VM; exec is serialized to avoid races.
- Fail-hard at startup if virtualization/runtime is unavailable (no unsandboxed fallback).

## License / redistribution

See [docs/LICENSES.md](docs/LICENSES.md) for microsandbox / libkrun / libkrunfw obligations.
