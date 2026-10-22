#!/usr/bin/env bash
# Bootstrap with uv's Python; FITS and its environment need not exist yet.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "Git is required. Install Git, then run this installer again."
    exit 1
fi
if uv run --no-project --python 3.12 python installation/setup.py "$@"; then
    exit 0
else
    result=$?
    echo "FITS installation failed. See installation/logs/install.log if it was created."
    if [[ -t 0 ]]; then read -r -p "Press Enter to close..." _; fi
    exit "$result"
fi
