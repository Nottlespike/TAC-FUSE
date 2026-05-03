#!/usr/bin/env bash
# Compatibility wrapper for the canonical Strix hardware bring-up path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/check_strix_bringup.sh" "$@"
