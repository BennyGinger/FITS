#!/usr/bin/env bash
# Shared bootstrap: downloads uv if needed, then installs FITS.
set -euo pipefail
exec "$BASH" "$(dirname -- "${BASH_SOURCE[0]}")/startup/install_unix.sh" "$@"
