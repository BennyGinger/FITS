#!/usr/bin/env bash
# The shared Unix supervisor also handles macOS.
set -euo pipefail
exec "$BASH" "$(dirname -- "${BASH_SOURCE[0]}")/launch_linux.sh" "$@"
