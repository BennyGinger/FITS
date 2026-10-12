#!/usr/bin/env bash
# Launch from the repository's environment, including from the Applications menu.
set -euo pipefail
fits_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$fits_root"
exec "$fits_root/.venv/bin/python" -m fits.gui.main "$@"
