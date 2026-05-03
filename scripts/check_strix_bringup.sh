#!/usr/bin/env bash
# Verify the TAC-FUSE Strix target is ready for the functional hardware demo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo "[FAIL] uv not found on PATH"
    echo "       Install uv or expose it to non-interactive SSH shells:"
    echo "       curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo '       export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"'
    exit 1
fi

cd "$PROJECT_ROOT"

echo "=== TAC-FUSE Strix Bring-Up ==="
echo "[OK]   uv: $(command -v uv)"

uv sync --extra dev --extra classifier-runtime

bash docs/check_rtx_prereqs.sh
uv run python scripts/check_classifier_package.py \
    --require-package \
    --require-runtime \
    --load-model
uv run python scripts/check_ray_runtime.py --require-rtx
TAC_FUSE_SIGLIP_DEVICE=NPU uv run python scripts/check_npu_runtime.py \
    --device NPU \
    --model-dir models/siglip2-field-npu \
    --require-npu
TAC_FUSE_SIGLIP_DEVICE=NPU uv run python scripts/write_edge_compute_status.py \
    --output web/edge_compute_status.js \
    --device NPU \
    --model-dir models/siglip2-field-npu \
    --host-label Strix \
    --source-label strix_bringup

echo "=== Strix bring-up complete ==="
