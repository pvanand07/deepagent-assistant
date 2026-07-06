#!/bin/sh
set -eu

SEED="/app/seed/AGENT.md"
TARGET="/workspace/AGENT.md"

mkdir -p /workspace

if [ -f "$SEED" ] && [ ! -f "$TARGET" ]; then
  cp "$SEED" "$TARGET"
fi

exec "$@"
