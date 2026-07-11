# Microsandbox reference (desktop)

This project uses [microsandbox](https://github.com/superradcompany/microsandbox)
microVMs via the Python SDK. The old bubblewrap + Docker Compose path has been
removed.

## Runtime check

```bash
uv run python -c "from microsandbox import is_installed; print(is_installed())"
msb doctor   # if msb is on PATH
```

If create fails at app startup, enable platform virtualization and retry:

| OS | Requirement |
|----|-------------|
| Linux | KVM (`/dev/kvm`), user in `kvm` group if needed |
| macOS | Apple Silicon |
| Windows | Windows Hypervisor Platform (WHP) |

## Guest image

Default is the public image `python:3.12-slim` (pulled on first create).

Optional custom image:

```bash
docker build -f Dockerfile.sandbox -t deepagent-workspace:dev .
docker save deepagent-workspace:dev | msb load --tag deepagent-workspace:dev
export DEEPAGENT_SANDBOX_IMAGE=deepagent-workspace:dev
```

## Shared sandbox behavior

- One VM named `deepagent` for the whole app process
- Host `DEEPAGENT_WORKDIR` bind-mounted at `/workspace`
- Idle auto-stop after `DEEPAGENT_SANDBOX_IDLE_TIMEOUT` (default 300s); recreated on next exec
- Exec lock: wait with `sandbox_wait`, cancel only after user confirmation

## Logs

Full command output: `/workspace/.deepagent/logs/<id>.log`  
Tool preview: last 100 lines + pointer to the log file

## Further reading

- [docs/microsandbox-migration.md](docs/microsandbox-migration.md)
- [Python SDK](https://github.com/superradcompany/skills/blob/main/microsandbox/references/sdk-python.md)
- [docs.microsandbox.dev](https://docs.microsandbox.dev/)
