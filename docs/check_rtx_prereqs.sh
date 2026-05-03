#!/usr/bin/env bash
# Validate optional RTX runtime readiness before the TAC-FUSE demo.

set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

echo "=== TAC-FUSE RTX Prerequisite Check ==="

if ! command -v uv >/dev/null 2>&1; then
    echo "[FAIL] uv not found on PATH"
    echo "       Add \$HOME/.local/bin to PATH or run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo "[OK]   uv: $(command -v uv)"

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
gpu_memory_mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')"
min_memory_mib="${TAC_FUSE_MIN_GPU_MEMORY_MIB:-7500}"

echo "[OK]   Driver version: ${driver_version}"
echo "[OK]   GPU: ${gpu_name}"
echo "[OK]   VRAM: ${gpu_memory_mib} MiB"

if [[ "${gpu_memory_mib}" =~ ^[0-9]+$ ]] && (( gpu_memory_mib < min_memory_mib )); then
    echo "[FAIL] GPU memory ${gpu_memory_mib} MiB is below ${min_memory_mib} MiB target"
    exit 1
fi

if uv run python scripts/check_ray_runtime.py --require-rtx >/tmp/tac-fuse-rtx-status.json 2>/tmp/tac-fuse-rtx-status.err; then
    echo "[OK]   TAC-FUSE RTX runtime boundary is available"
else
    echo "[FAIL] TAC-FUSE RTX runtime boundary unavailable on Strix target"
    cat /tmp/tac-fuse-rtx-status.err || true
    cat /tmp/tac-fuse-rtx-status.json || true
    exit 1
fi

echo
echo "=== Prerequisite check complete ==="
