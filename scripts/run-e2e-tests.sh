#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH=src
export DEEPAGENT_SANDBOX_BACKEND="${DEEPAGENT_SANDBOX_BACKEND:-stub}"
exec uv run pytest "$@"
