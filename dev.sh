#!/usr/bin/env bash
set -euo pipefail

# uv creates/syncs backend/.venv from backend/pyproject.toml + uv.lock on each
# run, so a fresh checkout boots without a manual install step.
cd "$(dirname "$0")"
exec uv run --project backend python dev.py "$@"
