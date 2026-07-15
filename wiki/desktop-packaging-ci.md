---
topic: desktop-packaging-ci
status: verified
last-verified: 2026-07-15
confidence_score: 1.0
priority: extended
rank: 9
tokens: 270
code-paths:
  - sidecar/
  - scripts/
  - .github/workflows/desktop-build.yml
  - .github/workflows/desktop-release.yml
  - src-tauri/
  - package.json
related-topics: [runtime-topology, settings-and-secrets]
---

## overview

Packaged desktop embeds a directory CPython sidecar (not PyInstaller); dual-OS CI builds unsigned installers on demand and ships updater artifacts on `v*` tags.

## current behavior

- `pnpm package:sidecar` builds embeddable/relocatable CPython under `sidecar/` (gitignored binaries).
- Sidecar copies `src/`, `frontend/`, `agents/` for packaged runs.
- Windows: NSIS + portable; macOS: DMG (arm64); Linux installers out of scope.
- `desktop-build.yml` (workflow_dispatch) → prerelease `unsigned-YYYYMMDD-HHMM`.
- `desktop-release.yml` on tag `v*` → release + updater artifacts.
- Smoke: import `deep_agent.api.app` + `/health`.
- Unit pytest suite is not gated in these desktop workflows.

## decisions

- Directory sidecar over PyInstaller single-file — why: simpler debugging, native Python layout, clearer resource embedding.
- Split manual smoke builds vs tagged ship releases — why: unsigned OS builds for testing; signed updater floor from tagged releases.
- Parallel PS1/SH packaging scripts — why: Windows vs macOS host requirements.

## gotchas

- Must re-run `pnpm package:sidecar` after Python dep/source changes before release — stale sidecar ships old code.
- Desktop CI green ≠ unit tests green — packaging smoke only.

## references

- `docs/macos-packaging.md`
- `docs/tauri-migration.md`
- `sidecar/README.md`
