# Changelog

All notable changes to TAC-FUSE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Edge compute display pipeline: `scripts/write_edge_compute_status.py`
  collects the ray-query and Intel NPU runtime inspectors and writes
  `web/edge_compute_status.js` so the static browser demo can display live
  accelerated-compute readiness from a script tag without requiring an HTTP
  server.
- Alpha test plan and queueable polish task pack focused on route-guard C2
  quality, RTX/BVH pathing, edge NPU zero-shot cue labels, and trained-model
  readiness.
- Two-to-five-minute judging demo script covering the route-guard denied
  connectivity story, the exact operator beats, rubric close, and edge Intel
  NPU real-CV integration lane with fallback language.
- Local C2 state-first proof path: every operator tasking or retasking action now persists to local mission state, audit log, and outbound sync queue BEFORE any enterprise export can run. Exports are deterministic offline artifacts derived from persisted state.
- `cancel_task()` method on `MissionStateStore` for retasking/cancellation that follows the same state-first guarantee: persists state, audit log, and sync queue entry before any export.
- `verify_state_first()` method on `MissionStateStore` for checking that all three proofs (state persisted, audit logged, sync enqueued) are complete for an entity — the first-class proof path for local C2 authority.
- Track ingestion (`insert_tracks`) now enqueues sync entries per asset track, so each track update is captured in the deferred sync queue.
- Dashboard value updates now also enqueue sync entries, ensuring local state changes are always queued for enterprise handoff.
- Test `test_local_c2_state_first_proof_path()` proving task persistence, audit logging, sync queue enrollment, and offline export derivation.
- Test `test_enterprise_sync_boundary_gated_by_connectivity()` proving exports work offline but external sync requires ONLINE mode.
- Test `test_audit_log_records_all_operator_commands()` proving all operator commands are audited with operator attribution.
- Test `test_cancel_task_state_first()` proving cancellation retasking follows state-first guarantee.
- Test `test_verify_state_first_proof_path()` for explicit verification of all three proofs.
- Test `test_track_sync_enqueue()` proving track ingestion enqueues sync entries.
- Module docstring guard on `tac_fuse.foundry_export` documenting the LOCAL C2 STATE-FIRST GUARANTEE.
- Problem Statement 2 self-improvement script that audits TAC-FUSE alignment
  and generates scoped AlphaHENG task packs around local C2 continuity.
- Maven Smart System / Foundry API configuration boundary (`tac_fuse.foundry`) with YAML + env-var loading, OAuth client-credentials support, token redaction, and a redacted env-check script. Tokens are never stored in git.
- Deterministic sensor emulation module (`tac_fuse.sensors`) with EO/RGB camera, IR/thermal, depth/range, and GNSS/IMU emulators that produce `SensorObservation` objects with covariance/uncertainty metadata convertible to fusion bus `SensorEvent` envelopes.
- Sensor degradation modeling for field conditions: haze, smoke, dust, rain, fog, low light, and occlusion modes affecting confidence, uncertainty, and quality scores.
- Dropped frame and stale track simulation with configurable drop rates and deterministic replay via seeded RNG.
- Multi-sensor platform emulator for coordinating observations from multiple sensors on a single drone or ground station.
- Test suite for sensor models covering determinism, degradation modes, covariance output, and fusion bus integration.
- Standalone GitHub repository metadata, CI, README, license, issue template, and PR template.
- Controlled Earth-imagery cache path (`scripts/cache_visual_assets.py`, `tac_fuse.assets.download`) that downloads only catalog-policy-eligible entries, writes a local manifest, and keeps tests offline with local `file://` fixtures.
- NASA Blue Marble starter source in `configs/assets/visual_asset_sources.yaml` for immediate real Earth-raster visualization.
- Drone POV replay projection with deterministic field-condition labels.
- Intel NPU SigLIP2 adapter boundary and runtime inspection script.
- Local ray-query/BVH boundary with RTX-runtime inspection and software-validation output shape.
- RTX prerequisite script referenced by the live demo runbook.
- Browser-based graphics emulator with a live swarm world, selected-drone POV, operator commands, online/offline queue behavior, BVH nodes, and local ray-query visualization.
- Offline-first hackathon UI that foregrounds local C2, cached maps, drone tasking, sensor cues, SQLite persistence, and staged enterprise export without live/degraded mode controls.
- Web demo reframed as laptop-local fused sensor array: fusion node is the authority (not cloud), drones shown as contributor feeds with freshness/confidence/latency, POV is one feed among several fused sources, staged Maven/Foundry mission packet shown, reconnect upload presented as operator-gated sync action (not live dependency), sync idle/staged pill in topbar, contributor feed latency badges inline, no empty-card placeholders, no tech-stack advertising in UI copy.
- Foundry-compatible local export artifacts for mission events, asset states, tasks, alerts, and sync manifest.
- Seeded restricted-zone entries, dashboard-state writes, and idempotent local persistence APIs for route conflicts and restricted entries.
- Durable offline fusion spool (`tac_fuses.fusion_node.spool.FusionSpool`) with append-only event log (SQLite WAL + JSONL side-car), deterministic fused-state snapshots at configurable intervals, sync watermarks per contributor, upload receipt tracking, idempotency keys for reconnect dedup, corruption-tolerant JSONL read path that skips bad records by checksum, and redacted inspection output for operator debugging.
- Inspection script (`scripts/inspect_fusion_spool.py`) that prints a redacted spool view or JSONL integrity stats from the command line.
- Test suite for the offline fusion spool (29 tests) covering schema init, WAL mode, event append/idempotency, JSONL health stats, corruption-tolerant reads, snapshot intervals, watermarks, receipt tracking, pending events, replay-to-target, redacted inspection, concurrent reads, and custom timestamps/keys.
- Test `test_single_operator_swarm_control_offline()` proving the full denied-operations workflow: a single operator tasks 4 drones, retasks mid-mission while offline, issues emergency abort, verifies complete proof chain, exports deterministically from local state, and confirms all sync entries remain pending (enterprise sync blocked until ONLINE).
- Playwright visual test verifying offline swarm control: commands issue while offline, sync gate holds staged packets, degraded mode transitions correctly, and the operator surface remains functional without connectivity.
- SigLIP2 INT8/OpenVINO NPU training scaffold, Hugging Face-native QAT dataset
  registry, and zero-shot image-text frame classification helpers.
- Zero-shot pseudo-classification SensorEvent output for `NPU_VISION` that keeps
  scene labels separate from object detections unless explicitly opted in.
- Pseudo-classification alert routing for tagathon workflows as low-priority
  scene context rather than a bounding-box detection claim.

### Changed
- The browser operator dock now includes an Edge Compute metric sourced from
  `web/edge_compute_status.js`; the default checked-in artifact shows
  accelerated compute pending, while hardware bring-up rewrites it after CUDA
  and NPU checks pass.
- Rendered object work now stays tied to classifier-training evidence: the 3D
  Field C2 view draws the wheeled vehicle as a four-wheel silhouette, counts
  vehicle frames for the local classifier story, and moves aerial contacts in
  from AOI edges instead of spawning them in the middle of the map.
- Removed the ambiguous manual route action from Local C2; corridor safety now
  presents as automatic route-guard monitoring backed by the BVH/RTX geometry
  lane, while operator commands stay limited to direct swarm intent.
- Split the browser demo into Field C2 and Overview tabs so the 3D working view
  and 2D AOI map no longer compete on the same screen; removed the bulky
  evidence-card overlay from the live operator map.
- Replaced generic friendly-node circles with platform-specific glyphs and gave
  scout-tasked drones an on-station movement pattern so a hovering platform
  reads as intentional field behavior.
- Corrected the Overview map projection to preserve 1.2 km x 1.2 km local scale
  inside wide canvases, and changed patrol/relay/scout movement to orbit fixed
  guard stations instead of drifting toward canvas corners.
- Reframed the static browser geometry label as pending unless a live hardware
  backend selects CUDA/RTX, avoiding a false claim that the standalone UI is
  directly driving ray-tracing cores.
- Added shared friendly identity handling in the field view so Alpha, Bravo,
  Charlie, Delta, and Team 1 remain known friendly tracks across edge-node
  perspectives instead of being reclassified as unknown detector objects.
- Extended the self-improvement generator to order work as Explore, Create,
  Beautify, and Cleanup; first-run tasks now include edge-kit `uv` bring-up,
  CUDA/RTX route optimization, multiple denied-connectivity scenarios, and
  Playwright-driven visual bug fixing before cleanup.
- Made the dashboard explicitly state the Problem Statement 2 route-guard
  scenario and judging evidence: cut off from internet and command, local C2
  holds the corridor, and visible Technical Demo, Military Impact, and
  Creativity proof points. Added the edge Intel NPU real-CV lane as an
  integration hook without making it a requirement for local C2.
- Standardized the browser demo on capitalized display copy and reframed the
  selected surface as a synthesized 3D Field C2 View with priority contacts.
- Replaced the selected-feed forward terrain/corridor POV with a 3D field view
  that labels priority contacts by class, confidence, range, and altitude delta.
- Replaced the global-looking theater raster with a local 1.2 km AOI view so
  scale, tracks, route zones, and the Fusion Node share one coherent field frame.
- Rendered the same Route Guard Corridor in both the AOI overview and 3D Field
  C2 View, with corridor edges and moving field contacts driven from shared
  synthesized state.
- Extended the TAC-FUSE self-improvement audit to guard the 3D field-C2
  quantification concept against regression back to terrain-camera rendering.
- Added explicit Explore/Create/Beautify/Cleanup workflow stages to generated
  self-improvement tasks, with demo polish treated as a first-class phase.
- Polished the browser demo top bar and 3D field view with non-wrapping mode
  controls, priority contact labels, and a local cue-pass quantification panel.
- Compact the Local C2 controls and metric strip so route, power, and sync
  status no longer consume a large empty row under the 3D map.
- Removed the redundant lower dashboard grid from the primary operator view;
  object classification now lives on the 3D map overlay while the status band
  stays focused on edge-C2 posture.
- Formatted contributor-feed latency and POV telemetry as human-readable values
  and removed the stretched world-raster POV.
- Preserved default Maven/Foundry OAuth scopes when no scope override is set.
- Made sensor emulator RNG derivation stable across Python processes and cleaned
  lint issues across current source/tests.
- Reframed README, agent guidance, and demo copy around hardened-laptop C2 continuity instead of Intel NPU-centric inference.
- Replaced the hackathon playbook with runnable repo structure and offline validation.
- Block external sync unless connectivity is fully ONLINE; DEGRADED is now local-state-only.
- Reworked the browser emulator from a block/grid status dashboard into a more cinematic offline field-node theater with terrain styling, compact panels, and visible local hardware proof points.
- Wired the browser theater to use the cached Earth imagery layer when present, with procedural terrain retained as the offline fallback.
- Reframed BVH copy as collision prevention and route optimization, with ray-tracing cores shown as the acceleration path for local spatial queries.
- Restyled the web demo UI as a laptop-local fusion node with contributor feeds (freshness/confidence/latency), selected feed as POV, feed quality panel, staged packet panel, sync watermark, and operator-gated upload button.
- **Deferred sync boundary tightened**: `foundry_export` reclassified from `REQUIRES_ONLINE` to `SAFE_OFFLINE` in `power_posture.py` because exports read from local persisted state and work in any connectivity mode. Only `enterprise_sync` (actual upload) requires ONLINE mode.
- Upload gate functions (`can_upload`, `assert_sync_allowed`, `has_upload_credentials`) in `tac_fuse.foundry.config` form a unified boundary requiring BOTH ONLINE mode AND valid Foundry/Maven credentials — missing configuration or partial OAuth never blocks local operator C2.
- Test `test_power_posture_classifies_export_as_safe_offline()` verifying workload classification.
- Test `test_upload_requires_both_online_mode_and_credentials()` verifying the unified upload gate requires both ONLINE mode AND valid credentials.
- Tests `test_assert_sync_allowed_*` and `test_export_always_works_regardless_of_sync_boundary()` proving the hard gate raises `SyncBoundaryViolation` on all boundary conditions while exports remain unaffected.
- **Reframed UI and demo scripts to position accelerators as optional supporting capabilities**: Changed "Detector"/"Object pass" metrics to "Sensor Cue"/"Local cue pass"; updated POV labels from "3D OBJECT MAP"/"DET" to "3D FUSION MAP"/"CUE"; made RTX prerequisite check optional in demo sequence; removed mandatory RTX validation from quick-start and demo bootstrap.
- Tightened the self-improvement inference-centrality audit to match bounded
  centrality terms, preventing false positives from words like score/remains
  while keeping edge NPU proof copy explicitly optional.

### Removed
- Removed the single-file TAC-FUSE hackathon playbook from the repo surface.
