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
install_fits() {
    local bootstrap_python
    if ! bootstrap_python="$(uv python find --system --managed-python 3.12 2>/dev/null)"; then
        uv python install 3.12 || return "$?"
        bootstrap_python="$(uv python find --system --managed-python 3.12)" || return "$?"
    fi
    "$bootstrap_python" startup/setup.py "$@"
}
if install_fits "$@"; then
    exit 0
else
    result=$?
    echo "FITS installation failed. See startup/logs/install.log if it was created."
    if [[ -t 0 ]]; then read -r -p "Press Enter to close..." _; fi
    exit "$result"
fi
