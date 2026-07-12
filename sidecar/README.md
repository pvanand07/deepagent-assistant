# Sidecar runtime (generated)

This directory holds a **platform Python runtime** plus installed dependencies
and a copy of `src/`, `frontend/`, and `agents/` for packaged Deep Agent builds.

| Host | Runtime layout | Regenerate |
|------|----------------|------------|
| Windows | Embeddable CPython → `python.exe` | `pnpm package:sidecar` / `scripts/package-sidecar.ps1` |
| macOS (arm64) | Relocatable CPython → `bin/python3` | `pnpm package:sidecar` / `scripts/package-sidecar.sh` |

Do not commit the generated binaries or site-packages — see `.gitignore`.
