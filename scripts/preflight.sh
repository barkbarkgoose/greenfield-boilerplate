#!/usr/bin/env bash
set -euo pipefail

# Runs in the backend uv environment so the keychain (cryptography) imports.
cd "$(dirname "$0")/.."
exec uv run --quiet --project backend python scripts/preflight.py "$@"
