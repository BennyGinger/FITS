#!/usr/bin/env bash
# Keep the updater outside .venv so it can repair or replace that environment.
set -euo pipefail
fits_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$fits_root"
bootstrap_python=""
if [[ -f startup/logs/bootstrap-python.txt ]]; then
    IFS= read -r bootstrap_python < startup/logs/bootstrap-python.txt || true
fi
if [[ ! -x "$bootstrap_python" ]]; then
    bootstrap_python="$(uv python find --system --managed-python 3.12)"
fi
exec "$bootstrap_python" startup/launcher.py "$@"
