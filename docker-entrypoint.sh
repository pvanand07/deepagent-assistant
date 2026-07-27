#!/bin/sh
set -eu

SEED="/app/seed/AGENT.md"
TARGET="/workspace/AGENT.md"
MCP_SEED="/app/seed/.mcp.json"
MCP_HOST="/app/.mcp.json"
DATA_DIR="${DEEPAGENT_DATA_DIR:-/app/data}"
MCP_TARGET="${DATA_DIR}/.mcp.json"

mkdir -p /workspace "$DATA_DIR"

if [ -f "$SEED" ] && [ ! -f "$TARGET" ]; then
  cp "$SEED" "$TARGET"
fi

# Seed MCP config into the data dir once (Settings/API writes stay there).
if [ ! -f "$MCP_TARGET" ]; then
  if [ -f "$MCP_HOST" ]; then
    cp "$MCP_HOST" "$MCP_TARGET"
  elif [ -f "$MCP_SEED" ]; then
    cp "$MCP_SEED" "$MCP_TARGET"
  fi
fi

exec "$@"
