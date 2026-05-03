#!/usr/bin/env bash
# Validate optional RTX runtime readiness before the TAC-FUSE demo.

set -euo pipefail

echo "=== TAC-FUSE RTX Prerequisite Check ==="

if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[FAIL] nvidia-smi not found; RTX driver is not installed"
    exit 1
fi

if ! nvidia-smi >/dev/null 2>&1; then
    echo "[FAIL] nvidia-smi returned non-zero"
    exit 1
fi

driver_version="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
gpu_name="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"

echo "[OK]   Driver version: ${driver_version}"
echo "[OK]   GPU: ${gpu_name}"

if uv run python scripts/check_ray_runtime.py --require-rtx >/tmp/tac-fuse-rtx-status.json 2>/tmp/tac-fuse-rtx-status.err; then
    echo "[OK]   TAC-FUSE RTX runtime boundary is available"
else
    echo "[WARN] TAC-FUSE RTX runtime boundary unavailable; CPU spatial fallback remains valid"
    cat /tmp/tac-fuse-rtx-status.err || true
fi

echo
echo "=== Prerequisite check complete ==="
