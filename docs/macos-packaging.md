# macOS packaging plan

Agreed design for packaging Deep Agent as an **unsigned arm64 macOS `.dmg`**, with
dual-OS GitHub Actions producing Windows + Mac artifacts. Complements
[tauri-migration.md](./tauri-migration.md) (Windows Phase 0–3 complete).

**Status:** Decision record agreed. Implementation tracks this document.

---

## Decision record

| # | Topic | Choice |
|---|--------|--------|
| 1 | Ambition | Direct-download shaped (DMG); **unsigned** on all platforms for now |
| 2 | CPU | Apple Silicon only (`arm64`) |
| 3 | Mac artifact | `.dmg` only |
| 4 | Signing / notarization | Deferred |
| 5 | Sidecar Python | Relocatable CPython (`uv` / python-build-standalone) under `sidecar/` |
| 6 | Build | Dual-OS GitHub Actions (`windows-latest` + `macos-14`) |
| 7 | Scripts | Parallel `package-sidecar.ps1` + `package-sidecar.sh` |
| 8 | Bundle targets | CLI `--bundles nsis` (Win) / `--bundles dmg` (Mac) |
| 9 | CI trigger | `workflow_dispatch` only |
| 10 | Entitlements | Research + wire Hypervisor-related entitlements before Mac package is “done” |
| 11 | Licenses | Parallel track (not blocking green CI); gate before public share — see [LICENSES.md](./LICENSES.md) |
| 12 | Windows CI | NSIS + portable zip |
| 13 | UX | Platform menu label + macOS degraded virt copy |
| 14 | Unix sidecar stop | `process_group(0)` + group `SIGKILL` |
| 15 | CI smoke | `from deep_agent.api.app import app` + brief `/health` |
| 16 | Min macOS | `11.0` (matches microsandbox `macosx_11_0_arm64` wheel) |
| 17 | Releases | Prerelease tag `unsigned-YYYYMMDD-HHMM` (UTC); assets named below |
| 18 | Docs | This file + Phase 5 stub in `tauri-migration.md` |
| 19 | Version | Keep `0.1.0` |
| 20 | Auto-update | None |
| 21 | Linux | Out of scope; next phase after Mac |

**Release assets:**

| Asset | Platform |
|-------|----------|
| `Deep-Agent-0.1.0-windows-x64-setup.exe` | Windows NSIS |
| `Deep-Agent-0.1.0-windows-x64-portable.zip` | Windows portable |
| `Deep-Agent-0.1.0-macos-arm64.dmg` | macOS arm64 |

**Deferred:** notarization, App Store, Intel/universal Mac, Linux installers,
license hard-gate, updater, custom DMG artwork.

---

## Architecture

```mermaid
flowchart LR
  dispatch[workflow_dispatch]
  subgraph win [windows-latest]
    ps1[package-sidecar.ps1]
    nsis["tauri build --bundles nsis"]
    zip[package-portable.ps1]
    smokeW[import plus health]
  end
  subgraph mac [macos-14]
    sh[package-sidecar.sh]
    dmg["tauri build --bundles dmg"]
    smokeM[import plus health]
  end
  release[GitHub prerelease unsigned-timestamp]
  dispatch --> win
  dispatch --> mac
  win --> release
  mac --> release
```

**Packaged Mac process model** (same as Windows):

| Direction | Method |
|-----------|--------|
| WebView → FastAPI | HTTP REST + SSE on `127.0.0.1` |
| Rust → FastAPI | Health wait, then navigate WebView |
| Rust → Python | Spawn `$RESOURCE/sidecar/bin/python3 -m uvicorn` |
| Data dirs | `~/Library/Application Support/DeepAgent`, `~/Documents/DeepAgent/workspace` |

---

## Local / CI commands

```bash
# macOS (Apple Silicon)
pnpm package:sidecar          # scripts/package-sidecar.sh
pnpm build:release            # sidecar + tauri build --bundles dmg

# Windows
pnpm package:sidecar          # scripts/package-sidecar.ps1
pnpm build:release            # sidecar + --bundles nsis + portable zip
```

CI: Actions → **Desktop build (unsigned)** → Run workflow. Downloads appear on the
prerelease tagged `unsigned-YYYYMMDD-HHMM`.

**Unsigned Gatekeeper note:** macOS will warn or block unknown developers. For
internal testing, right-click → Open, or clear quarantine after verifying the
artifact. Notarization is required before normal public distribution.

---

## Entitlements

`src-tauri/Entitlements.plist` is wired for Hypervisor / bundled native libs
(microsandbox `msb` + libkrunfw). Entitlements apply fully when the app is
code-signed; they are still configured now so CI DMGs match the intended
capability set.

Do **not** enable App Sandbox (conflicts with microVM + sidecar).

---

## Manual Apple Silicon check

After downloading the unsigned DMG from a CI prerelease:

1. Open the DMG and copy Deep Agent to Applications (or run from the volume).
2. Clear quarantine if needed: `xattr -dr com.apple.quarantine "/Applications/Deep Agent.app"`.
3. Launch; confirm WebView reaches `/health` and the Vue UI loads.
4. With OpenRouter configured, confirm chat works; sandbox should create a VM on
   Apple Silicon with Hypervisor, or show platform-aware degraded copy.
5. Quit and confirm no leftover `uvicorn` / Python sidecar processes.

---

## Next phase (Linux)

Linux AppImage/deb + relocatable Linux CPython sidecar and KVM-oriented degraded
UX are explicitly out of scope here. Track as a follow-on after Mac packaging is
stable.
