#!/usr/bin/env bash
# Bootstrap with uv's Python; FITS and its environment need not exist yet.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# Desktop sessions may not include uv's default install directory in PATH.
if [[ -d "$HOME/.local/bin" ]]; then
    export PATH="$PATH:$HOME/.local/bin"
fi
pause_on_exit() {
    local result=$?
    if [[ " ${*:-} " == *" --pause "* && -t 0 ]]; then
        read -r -p "Press Enter to close..." _ || true
    fi
    return "$result"
}
# Keep prerequisite and bootstrap failures visible as well as successful installs.
trap 'pause_on_exit "$@"' EXIT
install_fits() {
    local bootstrap_python
    if ! command -v git >/dev/null 2>&1; then
        echo "Git is required. Install Git, then run this installer again."
        return 1
    fi
    echo "uv is required by FITS and will be installed if missing."
    echo "uv is maintained independently; FITS does not manage its updates or removal."
    if command -v uv >/dev/null 2>&1; then
        echo "Reusing uv: $(command -v uv)"
    else
        echo "Downloading uv from its official installer..."
        local uv_installer
        uv_installer="$(mktemp "${TMPDIR:-/tmp}/fits-uv.XXXXXX")" || return "$?"
        if command -v curl >/dev/null 2>&1; then
            curl --proto '=https' --tlsv1.2 -fLsS https://astral.sh/uv/install.sh -o "$uv_installer" || {
                rm -f -- "$uv_installer"; return 1;
            }
        elif command -v wget >/dev/null 2>&1; then
            wget -q https://astral.sh/uv/install.sh -O "$uv_installer" || {
                rm -f -- "$uv_installer"; return 1;
            }
        else
            echo "curl or wget is required to download uv. Install one and rerun."
            rm -f -- "$uv_installer"
            return 1
        fi
        UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$uv_installer" || {
            rm -f -- "$uv_installer"; return 1;
        }
        rm -f -- "$uv_installer"
        export PATH="$PATH:$HOME/.local/bin"
        hash -r
        if ! command -v uv >/dev/null 2>&1; then
            echo "uv installation did not produce a usable executable."
            return 1
        fi
    fi
    if ! bootstrap_python="$(uv python find --system --managed-python 3.12 2>/dev/null)"; then
        uv python install 3.12 || return "$?"
        bootstrap_python="$(uv python find --system --managed-python 3.12)" || return "$?"
    fi
    local argument
    local -a arguments=()
    for argument in "$@"; do
        [[ "$argument" == --pause ]] || arguments+=("$argument")
    done
    "$bootstrap_python" startup/setup.py ${arguments[@]+"${arguments[@]}"}
}
if install_fits "$@"; then
    exit 0
else
    result=$?
    echo "FITS installation failed. See startup/logs/install.log if it was created."
    exit "$result"
fi
