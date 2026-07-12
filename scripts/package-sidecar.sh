#!/usr/bin/env bash
# Build the macOS arm64 directory sidecar: relocatable CPython 3.12 + locked deps + app sources.
#
# Uses `uv python install` (python-build-standalone) and copies the managed install
# into sidecar/, then installs deps from uv.lock. Packaged Deep Agent runs:
#
#   ./sidecar/bin/python3 -m uvicorn api:app --host 127.0.0.1 --port 8010
#
# Usage:
#   ./scripts/package-sidecar.sh
#   ./scripts/package-sidecar.sh --force
#   pnpm package:sidecar
#
# Output is gitignored (except sidecar/README.md).

set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.12.10}"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --python=*) PYTHON_VERSION="${arg#--python=}" ;;
    -h|--help)
      echo "Usage: $0 [--force] [--python=3.12.10]"
      exit 0
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO_ROOT/sidecar"
CACHE_DIR="$REPO_ROOT/.cache/python-standalone"

step() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || die "Required command not found on PATH: uv"

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "package-sidecar.sh is for macOS. On Windows use scripts/package-sidecar.ps1"
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  die "Apple Silicon (arm64) only. Got: $(uname -m)"
fi

mkdir -p "$OUT_DIR" "$CACHE_DIR"
README_PATH="$OUT_DIR/README.md"

if [[ "$FORCE" -eq 1 ]]; then
  step "Cleaning sidecar/ (preserving README.md)"
  find "$OUT_DIR" -mindepth 1 -maxdepth 1 ! -name 'README.md' -exec rm -rf {} +
fi

if [[ ! -f "$README_PATH" ]]; then
  cat > "$README_PATH" <<'EOF'
# Sidecar runtime (generated)

This directory holds a relocatable CPython runtime plus installed dependencies
and a copy of `src/`, `frontend/`, and `agents/` for packaged Deep Agent builds.

Regenerate with:

```bash
pnpm package:sidecar
# macOS: ./scripts/package-sidecar.sh
# Windows: pwsh -File scripts/package-sidecar.ps1
```

Do not commit the generated binaries or site-packages — see `.gitignore`.
EOF
fi

PYTHON_BIN=""
if [[ -x "$OUT_DIR/bin/python3" ]]; then
  PYTHON_BIN="$OUT_DIR/bin/python3"
elif [[ -x "$OUT_DIR/bin/python" ]]; then
  PYTHON_BIN="$OUT_DIR/bin/python"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  step "Installing managed CPython $PYTHON_VERSION via uv"
  uv python install "$PYTHON_VERSION"

  FOUND="$(uv python find "$PYTHON_VERSION")"
  [[ -n "$FOUND" && -x "$FOUND" ]] || die "uv python find failed for $PYTHON_VERSION"
  # Managed layout: <prefix>/bin/python3
  PREFIX="$(cd "$(dirname "$FOUND")/.." && pwd)"
  [[ -d "$PREFIX/bin" ]] || die "Unexpected Python layout at $PREFIX"

  step "Copying relocatable Python from $PREFIX → sidecar/"
  # Copy contents (not the versioned folder name) so paths stay sidecar/bin/python3
  rsync -a --delete --exclude 'README.md' "$PREFIX"/ "$OUT_DIR"/

  PYTHON_BIN="$OUT_DIR/bin/python3"
  [[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="$OUT_DIR/bin/python"
  [[ -x "$PYTHON_BIN" ]] || die "python binary missing after copy under $OUT_DIR/bin"

  # Relocatable shebangs for scripts in bin/
  step "Rewriting bin/ shebangs for relocation"
  if [[ -d "$OUT_DIR/bin" ]]; then
    while IFS= read -r -d '' script; do
      if head -n1 "$script" | grep -q '^#!.*python'; then
        # Prefer env-based shebang so the packaged tree can move with the .app
        printf '%s\n' '#!/usr/bin/env python3' > "$script.tmp"
        tail -n +2 "$script" >> "$script.tmp"
        mv "$script.tmp" "$script"
        chmod +x "$script"
      fi
    done < <(find "$OUT_DIR/bin" -type f -print0 2>/dev/null || true)
  fi

  # Fix libpython install name so the .app bundle can relocate (macOS).
  step "Fixing libpython dylib id for relocation"
  shopt -s nullglob
  for dylib in "$OUT_DIR"/lib/libpython*.dylib; do
    base="$(basename "$dylib")"
    install_name_tool -id "@executable_path/../lib/$base" "$dylib" 2>/dev/null || true
  done
  shopt -u nullglob
  # Point the interpreter at the relative dylib when needed
  if [[ -x "$PYTHON_BIN" ]]; then
    for dylib in "$OUT_DIR"/lib/libpython*.dylib; do
      base="$(basename "$dylib")"
      # Re-link load commands that still point at absolute uv cache paths
      old_ids="$(otool -L "$PYTHON_BIN" 2>/dev/null | awk '/libpython/{print $1}' || true)"
      for old in $old_ids; do
        if [[ "$old" == *libpython* ]]; then
          install_name_tool -change "$old" "@executable_path/../lib/$base" "$PYTHON_BIN" 2>/dev/null || true
        fi
      done
    done
  fi
fi

step "Exporting locked dependencies from uv.lock (no dev)"
REQ_PATH="$OUT_DIR/requirements.txt"
(
  cd "$REPO_ROOT"
  uv export --frozen --no-dev --no-emit-project --no-hashes -o "$REQ_PATH"
)

step "Installing dependencies into sidecar (uv pip)"
(
  cd "$REPO_ROOT"
  uv pip install --python "$PYTHON_BIN" -r "$REQ_PATH"
)

step "Copying src/, frontend/, agents/ into sidecar/"
rm -rf "$OUT_DIR/src" "$OUT_DIR/frontend" "$OUT_DIR/agents"
cp -R "$REPO_ROOT/src" "$OUT_DIR/src"
cp -R "$REPO_ROOT/frontend" "$OUT_DIR/frontend"
cp -R "$REPO_ROOT/agents" "$OUT_DIR/agents"
find "$OUT_DIR" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

step "Smoke: import api:app"
export PYTHONPATH="$OUT_DIR/src"
export DEEPAGENT_DESKTOP=1
"$PYTHON_BIN" -c "from api import app; print('api:app ok')"

step "Smoke: brief uvicorn /health"
PORT=18765
"$PYTHON_BIN" -m uvicorn api:app --host 127.0.0.1 --port "$PORT" &
UV_PID=$!
cleanup() { kill "$UV_PID" 2>/dev/null || true; wait "$UV_PID" 2>/dev/null || true; }
trap cleanup EXIT
ok=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    ok=1
    break
  fi
  sleep 0.25
done
[[ "$ok" -eq 1 ]] || die "uvicorn /health smoke failed on port $PORT"
cleanup
trap - EXIT
printf 'health ok\n'

printf '\nSidecar ready at %s\n' "$OUT_DIR"
printf '  python:  %s\n' "$PYTHON_BIN"
printf '  run:     PYTHONPATH=%s/src %s -m uvicorn api:app --host 127.0.0.1 --port 8010\n' "$OUT_DIR" "$PYTHON_BIN"
printf 'Next:      pnpm exec tauri build --bundles dmg\n'
