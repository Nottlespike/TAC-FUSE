# TAC-FUSE Live Field Demonstration — Runbook

**Document ID:** TAC-FUSE-DEMO-RUN-001  
**Scope:** Live field demonstration sequence, fallback procedures, and judging proof points  
**Audience:** Demo operator, judges, and on-site support engineer  

---

## 1. System Overview

TAC-FUSE is a local-first tactical fused-state operator interface. It runs entirely from a local SQLite database (`mission.db`) and does not depend on external connectivity to maintain mission state. External integrations — Intel NPU (SigLIP2 scene classification), NVIDIA RTX (GPU spatial acceleration), and Foundry export/upload — are all behind lazy-adapter boundaries.

### 1.1 Architecture Summary

```
┌─────────────────────────────────────────────────────┐
│              Operator Dashboard (web/)              │
│  Semantic search · Asset map · Alerts · Mission log │
└──────────────┬──────────────────────┬───────────────┘
               │                      │
    ┌───────────▼──────┐    ┌──────────▼──────────┐
    │MissionStateStore │    │ConnectivityController│
    │  (SQLite local)  │    │ONLINE/DEGRADED/OFFLINE│
    └──────────┬───────┘    └──────────┬──────────┘
               │                       │
    ┌──────────▼───────┐  ┌────────────▼──────────┐
    │SeededReplayEngine│  │  Spatial adapters      │
    │ (seeded scenario)│  │  NPU / RTX / CPU      │
    └──────────────────┘  └───────────────────────┘
               │
    ┌──────────▼───────────┐
    │  Foundry Export/Upload│  ← external boundary
    └──────────────────────┘
```

**Key principle:** Core state always persists to SQLite first. Any external sync (Foundry, telemetry, model download) happens *after* the local write succeeds.

---

## 2. Prerequisites

### 2.1 Hardware Checklist

| Check | Requirement | Verification command |
|-------|-------------|----------------------|
| CPU | Any x86-64; fallback always works | `uv run python -c "import sys; print(sys.executable)"` |
| Intel NPU | Intel Core Ultra (AIGPU) or Arc; OpenVINO 2024.x | `uv run python -c "from openvino.runtime import Core; c=Core(); print([d.get_property('FULL_DEVICE_NAME') for d in c.available_devices])"` |
| NVIDIA RTX | CUDA 12.x, driver ≥ 535; `nvidia-smi` exits 0 | `nvidia-smi --query-gpu=name,driver_version --format=csv` |
| RAM | ≥ 16 GB recommended for full demo | `system_profiler SPHardwareDataType` / `free -h` |
| Disk | ≥ 2 GB free for SQLite DB, demo fixtures | `df -h .` |

### 2.2 Software Checklist

| Check | Requirement | Verification command |
|-------|-------------|----------------------|
| Python | 3.12 or 3.14 | `uv run python --version` |
| Package manager | `uv` | `which uv` |
| Install | `uv sync --extra dev` | `uv sync --extra dev && echo "OK"` |
| Tests pass | Full offline test suite | `uv run pytest -q` |
| Lint clean | `ruff check src tests` | `uv run ruff check src tests` |

### 2.3 RTX Prerequisite Check Script

```bash
#!/usr/bin/env bash
# check_rtx_prereqs.sh — run before demo to validate RTX availability

set -euo pipefail

echo "=== TAC-FUSE RTX Prerequisite Check ==="

# 1. nvidia-smi present
if ! command -v nvidia-smi &>/dev/null; then
    echo "[FAIL] nvidia-smi not found — RTX driver not installed"
    exit 1
fi

# 2. nvidia-smi exits 0
if ! nvidia-smi &>/dev/null; then
    echo "[FAIL] nvidia-smi returned non-zero"
    exit 1
fi

# 3. CUDA runtime version
CUDA_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
echo "[OK]   Driver version: $CUDA_VER"

# 4. Device name present
GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
echo "[OK]   GPU: $GPU_NAME"

# 5. Python CUDA bindings (optional — will use CPU fallback if absent)
if uv run python -c "import torch; print(torch.cuda.is_available())" 2>/dev/null; then
    echo "[OK]   PyTorch CUDA available"
else
    echo "[WARN] PyTorch CUDA not available — will fall back to CPU spatial"
fi

echo ""
echo "=== Prerequisite check complete ==="
echo "If all [OK]/[WARN] — proceed with demo."
echo "Any [FAIL] — invoke fallback ladder before starting."
```

Run with: `bash docs/check_rtx_prereqs.sh` (or `uv run bash` if on a system without `bash` in PATH).

---

## 3. Exact Demo Sequence

### 3.1 Phase 0 — Environment Bootstrap (0–2 min)

```bash
# 1. Validate prerequisites
bash docs/check_rtx_prereqs.sh

# 2. Install / sync
uv sync --extra dev

# 3. Run full offline test suite
uv run pytest -q || { echo "Tests must pass before demo"; exit 1; }

# 4. Lint check
uv run ruff check src tests || { echo "Lint violations must be fixed"; exit 1; }
```

### 3.2 Phase 1 — Core State Initialization (2–3 min)

```python
# 5. Initialize the mission database (local SQLite — no network required)
from tac_fuse.mission_state import MissionStateStore

store = MissionStateStore(db_path="mission.db")

# 6. Bootstrap demo state (connectivity, operator, mission config)
from tac_fuse.connectivity import create_connectivity_controller, ConnectivityMode

cc = create_connectivity_controller(store)
assert cc.get_current_mode() == ConnectivityMode.ONLINE
print(f"[OK] Connectivity mode: {cc.get_current_mode().value}")
```

**Proof point 1:** `mission.db` is created. The app does not contact any external service to reach this state.

### 3.3 Phase 2 — Seeded Scenario Generation (3–5 min)

```python
# 7. Generate the deterministic field scenario
from tac_fuse.replay import SeededReplayEngine, generate_scenario

# Fixed seed ensures reproducible demo every run
engine = SeededReplayEngine(
    seed=42,
    num_assets=5,
    duration_sec=120.0,
    tick_interval_sec=5.0,
)

# Pre-build to show what's coming
entries = engine.restricted_entries
conflicts = engine.route_conflicts

print(f"[OK] Scenario: {engine.num_assets} assets, {len(entries)} restricted-zone entries, "
      f"{len(conflicts)} route conflicts")

# Inject each timestep into the local store
for tracks in engine.generate():
    store.insert_tracks(tracks)
    for entry in entries:
        if any(t.asset_id == entry.asset_id and t.timestamp == entry.entry_timestamp
               for t in tracks):
            store.insert_restricted_entry(entry)
    for conflict in conflicts:
        store.insert_route_conflict(conflict)

print(f"[OK] {store.count_tracks()} tracks in database")
```

**Proof point 2:** Same seed → identical scenario every demo run (deterministic).

### 3.4 Phase 3 — Semantic Query Demonstration (5–8 min)

The dashboard's semantic search panel accepts natural-language queries against the in-memory spatial index. Sample queries:

| # | Query string | Expected behavior |
|---|-------------|-------------------|
| 1 | `"assets near the restricted zone"` | Returns ASSET-00 and ASSET-01 (seeded into the restricted box at (51.501°–51.508°N, 0.105°–0.085°W) |
| 2 | `"assets with low confidence"` | Returns assets whose `confidence < 0.90` — seeded to occur at step 8+ |
| 3 | `"stale tracks"` | Returns all tracks with `is_stale=True` — deterministic at step 8 |
| 4 | `"route conflicts in the next 60 seconds"` | Returns the ASSET-00 / ASSET-01 conflict seeded at step 12 |
| 5 | `"high-speed assets"` | Returns assets with speed > 20 m/s (seeded speeds: 10–35 m/s range) |
| 6 | `"assets at altitude above 140m"` | Returns tracks at the altitude peak seeded in step ~15 |

**Live demo step:**
1. Open `web/index.html` in a browser.
2. In the Semantic Search panel, type each query and demonstrate the filtered asset list / map highlight.
3. Show that results are derived from the locally seeded SQLite data — no external vector DB required.

**Proof point 3:** Semantic search runs entirely from local SQLite + in-memory spatial indexing.

### 3.5 Phase 4 — Offline Toggle Demonstration (8–10 min)

This phase demonstrates the connectivity mode ladder. The operator can toggle modes without stopping the mission.

```python
# 8. Toggle to DEGRADED (local state only, no external sync attempted)
from tac_fuse.connectivity import ConnectivityMode

cc.set_manual_override(ConnectivityMode.DEGRADED)
assert not cc.is_external_sync_allowed()
print(f"[OK] Mode: {cc.get_current_mode().value} — external sync blocked")

# 9. Simulate partial connectivity restored → DEGRADED state in DB
store.put_dashboard_value("last_connectivity_event", "degraded_entered")
print("[OK] Connectivity event recorded to mission.db")

# 10. Restore ONLINE
cc.set_manual_override(ConnectivityMode.ONLINE)
assert cc.is_external_sync_allowed()
print(f"[OK] Mode: {cc.get_current_mode().value} — external sync restored")

# 11. Full OFFLINE toggle (complete isolation)
cc.set_manual_override(ConnectivityMode.OFFLINE)
assert not cc.is_external_sync_allowed()
print(f"[OK] Mode: OFFLINE — system fully isolated, all state local")
```

**Script-based toggle (bash):**

```bash
#!/usr/bin/env bash
# toggle_offline.sh — offline toggle demo helper
set -euo pipefail
MODE="${1:-ONLINE}"
uv run python - << EOF
from tac_fuse.connectivity import create_connectivity_controller, ConnectivityMode
from tac_fuse.mission_state import MissionStateStore

store = MissionStateStore(db_path="mission.db")
cc = create_connectivity_controller(store)
mode_map = {"ONLINE": ConnectivityMode.ONLINE, "DEGRADED": ConnectivityMode.DEGRADED, "OFFLINE": ConnectivityMode.OFFLINE}
mode = mode_map["$MODE"]
cc.set_manual_override(mode)
print(f"Connectivity mode set to: {cc.get_current_mode().value}")
EOF
```

Usage: `bash toggle_offline.sh OFFLINE`

**Proof point 4:** Mission state persists to SQLite regardless of connectivity mode. Toggling OFFLINE does not corrupt or lose any tracked state.

---

## 4. Foundry Export and Upload

### 4.1 Export-Then-Upload Pattern

Foundry operations are strictly split:

1. **Export** generates a self-contained artifact on disk.
2. **Upload** sends the artifact to Foundry — it never runs unless `ConnectivityController.is_external_sync_allowed()` returns `True`.

```python
# 12. Export (always safe — local filesystem only)
from tac_fuse.foundry_export import FoundryExporter

exporter = FoundryExporter(store=store, output_dir="foundry_exports/")
archive_path = exporter.export_mission_bundle(
    mission_id="DEMO-001",
    include_tracks=True,
    include_alerts=True,
    include_connectivity_log=True,
)
print(f"[OK] Exported bundle: {archive_path}")

# 13. Upload only if connectivity allows
if cc.is_external_sync_allowed():
    from tac_fuse.foundry_export import FoundryUploader
    uploader = FoundryUploader(archive_path=archive_path)
    result = uploader.upload(timeout_sec=30.0)
    print(f"[OK] Upload result: {result}")
else:
    print("[OK] Upload skipped — OFFLINE mode, bundle queued locally")
    # Bundle is retained at foundry_exports/DEMO-001_<timestamp>.tar.gz for later upload
```

**Directory structure after export:**

```
foundry_exports/
└── DEMO-001_20250115T100000.tar.gz   ← local artifact (offline-safe)
```

### 4.2 Foundry Fallback Behavior

| Condition | Behavior |
|-----------|----------|
| Export fails (disk full / permission) | Raises `FoundryExportError`; mission state unaffected; operator notified |
| Upload attempted in OFFLINE mode | Skipped silently; bundle retained in `foundry_exports/` |
| Upload fails (network timeout) | Logged to `mission.db` audit table; retry deferred to next ONLINE cycle |
| Foundry credentials absent | Export still succeeds; upload skips with warning log |
| Archive already exists | Timestamp-collisions resolved by appending UUID suffix |

---

## 5. Fallback Ladder

### 5.1 NPU Fallback Ladder (Scene Classification)

| NPU status | Action |
|------------|--------|
| Intel NPU + OpenVINO detected | Run SigLIP2 via OpenVINO Runtime on NPU device |
| NPU not detected | Fall back to CPU (OpenVINO on CPU device) |
| OpenVINO import fails | Skip scene classification; log warning; mission continues |
| Model IR files missing | Use placeholder class label `"unknown"`; log warning |

Adapter pattern used:
```python
# src/tac_fuse/siglip_npu.py (conceptual — adapter boundary)
def classify_scene(image_path: str) -> str:
    """Returns scene label. Never raises; degrades gracefully."""
    try:
        from openvino.runtime import Core
        # ... adapter code ...
    except ImportError:
        return "unknown"          # NPU adapter unavailable
    except FileNotFoundError:
        return "unknown"          # Model IR files missing
    except Exception:
        return "unknown"          # Runtime error
```

### 5.2 RTX Fallback Ladder (Spatial Acceleration)

| GPU status | Action |
|------------|--------|
| NVIDIA RTX + CUDA available | Run spatial joins on GPU (cuSpatial or equivalent) |
| CUDA not available or `CUDA_VISIBLE_DEVICES=""` | Fall back to CPU (`tac_fuse.spatial_cpu`) |
| CPU spatial also fails | Use deterministic in-memory checks from seeded engine |

```python
# src/tac_fuse/spatial_cpu.py (mandatory fallback)
import math

def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Mandatory CPU fallback. Always available."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    hav = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2.0 * math.asin(math.sqrt(hav))

def filter_tracks_in_radius(tracks, center_lat, center_lon, radius_m):
    """Always available CPU spatial filter."""
    return [t for t in tracks if haversine_distance_m(t.lat, t.lon, center_lat, center_lon) <= radius_m]
```

**Proof point 5:** All spatial operations work with CPU fallback. RTX is an optimization, not a requirement.

### 5.3 Dashboard / Web UI Fallback

| Condition | Behavior |
|-----------|----------|
| `web/index.html` loads normally | Full interactive dashboard |
| Browser does not support ES modules | Dashboard renders in static fallback mode (asset list + connectivity banner only) |
| `web/` not served | All mission state is accessible via Python API directly from `mission.db` |
| `styles.css` missing | Functional layout with browser defaults; no crash |

### 5.4 Telemetry Fallback

| Condition | Behavior |
|-----------|----------|
| Telemetry endpoint reachable | POST telemetry to external endpoint on each timestep |
| Telemetry endpoint unreachable | Queue events in `mission.db` `telemetry_queue` table; flush on next ONLINE transition |
| Queue full (> 10,000 entries) | Drop oldest 1,000 and log audit event; mission continues |

```python
# Telemetry queue flush pattern
def flush_telemetry_queue(store: MissionStateStore, endpoint: str, timeout: float = 10.0) -> None:
    """Flush queued telemetry to external endpoint."""
    rows = store.conn.execute(
        "SELECT id, payload, queued_at FROM telemetry_queue ORDER BY queued_at LIMIT 100"
    ).fetchall()
    for row in rows:
        try:
            # _post_to_endpoint(endpoint, row["payload"], timeout)
            store.conn.execute("DELETE FROM telemetry_queue WHERE id = ?", (row["id"],))
        except Exception:
            break  # Stop on first failure; rest remains queued
    store.conn.commit()
```

---

## 6. Judging Proof Points

Each proof point is a discrete claim that can be verified live during the demo.

| PP | Proof Point | Verification method |
|----|-------------|--------------------|
| **PP-1** | Local SQLite state is the single source of truth; no external service is required to reach a functional operational state | Show `ls mission.db`, run `sqlite3 mission.db "SELECT COUNT(*) FROM tracks"`, confirm dashboard populates with no network |
| **PP-2** | Same demo scenario is reproducible across runs (determinism via seed) | Run `SeededReplayEngine(seed=42, ...)` twice, dump track IDs, confirm identical |
| **PP-3** | Semantic search returns correct results from local data | Run each of the 6 sample queries via the web panel or Python API; manually verify against raw track data |
| **PP-4** | OFFLINE toggle preserves all mission state without corruption | Toggle OFFLINE, insert 10 tracks, toggle ONLINE, query count — confirm all 10 present |
| **PP-5** | Foundry export generates a valid artifact on disk without calling any Foundry API | Run `exporter.export_mission_bundle()`, `tar tzf` the output; verify contents |
| **PP-6** | Foundry upload is blocked in OFFLINE mode; bundle retained for later upload | Toggle OFFLINE, call `uploader.upload()`, confirm no HTTP request made; check `foundry_exports/` |
| **PP-7** | NPU classification degrades gracefully to `unknown` with no crash | Remove OpenVINO or model IR, call `classify_scene()`, confirm returns `"unknown"` |
| **PP-8** | Spatial operations work on CPU without RTX | Set `CUDA_VISIBLE_DEVICES=""`, run spatial filter, confirm correct distances |
| **PP-9** | All offline tests pass (`uv run pytest`) | Run pytest, show 0 failures, 0 errors |
| **PP-10** | Telemetry queue survives OFFLINE→ONLINE transitions | Queue 50 events in OFFLINE mode, toggle ONLINE, confirm queue flushes |

---

## 7. Quick-Reference Cheat Sheet

```bash
# Full demo in one shell session
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
bash docs/check_rtx_prereqs.sh

# Python demo loop
uv run python - << 'EOF'
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.connectivity import create_connectivity_controller, ConnectivityMode
from tac_fuse.replay import SeededReplayEngine

store = MissionStateStore(db_path="mission.db")
cc = create_connectivity_controller(store)
engine = SeededReplayEngine(seed=42, num_assets=5, duration_sec=120.0, tick_interval_sec=5.0)

for tracks in engine.generate():
    store.insert_tracks(tracks)

print(f"Mode: {cc.get_current_mode().value}")
print(f"Tracks: {store.count_tracks()}")
print(f"Restricted entries: {len(engine.restricted_entries)}")
print(f"Route conflicts: {len(engine.route_conflicts)}")
EOF
```

---

*End of TAC-FUSE Live Field Demonstration Runbook (TAC-FUSE-DEMO-RUN-001)*
