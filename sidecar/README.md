# Sidecar runtime (generated)

This directory holds the Windows **embeddable CPython** runtime plus installed
dependencies and a copy of `src/`, `frontend/`, and `agents/` for packaged
Deep Agent builds.

Regenerate with:

```powershell
pnpm package:sidecar
# or: pwsh -File scripts/package-sidecar.ps1
```

Do not commit the generated binaries or `Lib/` tree — see `.gitignore`.
