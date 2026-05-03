# TAC-FUSE

TAC-FUSE is a local-first command and control emulator for field laptops. It runs a small graphics environment with a drone swarm, operator commands, online/offline transitions, local BVH/ray-query checks, queued Foundry export records, and an Intel NPU vision path for a fine-tuned `google/siglip2-base-patch16-224` classifier.

The repo is usable without Palantir Foundry, internet access, or accelerator hardware. The NPU adapter is lazy: tests exercise deterministic emulation, while a field laptop can point it at an exported OpenVINO model.

## Quick Start

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run python scripts/cache_visual_assets.py --dry-run
uv run python scripts/check_ray_runtime.py
uv run python scripts/check_npu_runtime.py
```

Open `web/index.html` directly in a browser for the emulator. The left pane is the live swarm world; the right pane is the selected drone's POV. Operator commands change drone behavior. Offline mode queues commands and export records while the local graphics, BVH, and NPU-emulation paths keep running.

To populate the first real Earth-raster layer for the browser view:

```bash
uv run python scripts/cache_visual_assets.py --source nasa_blue_marble_january
```

The script only downloads catalog entries that explicitly opt in with
`auto_download: true` and `restriction: none`. Large cached rasters stay under
`assets/visual/` and are ignored by git.

## Intel NPU SigLIP2 Path

Expected local model layout:

```text
models/siglip2-field-npu/
  openvino_model.xml
  openvino_model.bin
```

Set `TAC_FUSE_SIGLIP_MODEL_DIR` if the exported model lives elsewhere. Set `TAC_FUSE_SIGLIP_DEVICE=NPU` on Intel NPU systems, or `CPU` for parity checks.

## Foundry Boundary

Core execution writes SQLite state first. Foundry integration is represented as export-ready records in the local `sync_queue` and by dataset-style files under an export directory:

- `mission_events.jsonl`
- `asset_states.jsonl`
- `operator_tasks.jsonl`
- `alerts.jsonl`
- `sync_manifest.json`

## Local Hardware Boundary

The demo treats connectivity and acceleration independently. When the laptop is offline, SQLite state, BVH geometry checks, and the NPU vision path remain local. The browser visualizes BVH nodes, ray fans, hazard-volume intersections, and command effects. `scripts/check_ray_runtime.py --require-rtx` is the hard gate for a field machine that must prove RTX/CUDA ray-query availability; without that flag the CPU parity path stays available for offline validation.
