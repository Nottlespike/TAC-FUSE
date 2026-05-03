# TAC-FUSE

TAC-FUSE is a local-first edge command-and-control emulator for hardened field laptops and backpack-class kits. It targets **Problem Statement 2: Edge Deployments and Drone Operation**: keep a front-line operator in control of autonomous systems when connectivity to central infrastructure is intermittent, degraded, or fully denied.

The core demo is the local C2 loop: cached theater view, drone swarm state, operator tasking, local mission database, prioritized alerts, and deferred Maven/Foundry sync. Local inference is a supporting capability. The SigLIP/OpenVINO path shows that the edge node can classify or prioritize identifiable objects from local feeds, but the application must remain useful without Intel NPU hardware, cloud inference, or model downloads.

See `docs/problem_statement_alignment.md` for the project-level targeting rules.

## Quick Start

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run python scripts/cache_visual_assets.py --dry-run
uv run python scripts/check_ray_runtime.py
```

Open `web/index.html` directly in a browser for the emulator. The left pane is the live swarm world; the right pane is the selected drone's POV. Operator commands change drone behavior. Offline mode queues commands and export records while the local graphics, collision BVH route solver, and sensor-cue paths keep running.

To populate the first real Earth-raster layer for the browser view:

```bash
uv run python scripts/cache_visual_assets.py --source nasa_blue_marble_january
```

The script only downloads catalog entries that are non-manual and eligible for
automatic download under the catalog policy. Large cached rasters stay under
`assets/visual/` and are ignored by git.

## Supporting Inference Path

Object detection and scene classification are supporting proof points, not the main product. The hardened laptop remains the C2 authority when inference is unavailable. Use the optional SigLIP2/OpenVINO path to show that once objects are visible in local drone feeds, the edge kit can classify and prioritize them without cloud infrastructure.

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

The demo treats connectivity and acceleration independently. When the laptop is offline, SQLite state, operator tasking, drone coordination, cached maps, and local alerting continue. The BVH path is the collision and route-optimization solver: it checks drone paths against hazards, nearby assets, and route corridors. Ray-tracing cores are useful because they accelerate those spatial queries; without RTX/CUDA availability the CPU parity path stays available for offline validation.
