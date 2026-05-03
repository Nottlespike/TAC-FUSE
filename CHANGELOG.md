# Changelog

All notable changes to TAC-FUSE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- Local ray-query/BVH boundary with RTX-runtime inspection and CPU parity output shape.
- RTX prerequisite script referenced by the live demo runbook.
- Browser-based graphics emulator with a live swarm world, selected-drone POV, operator commands, online/offline queue behavior, BVH nodes, and local ray-query visualization.
- Offline-first hackathon UI that foregrounds local C2, cached maps, drone tasking, sensor cues, SQLite persistence, and staged enterprise export without live/degraded mode controls.
- Web demo reframed as laptop-local fused sensor array: fusion node is the authority (not cloud), drones shown as contributor feeds with freshness/confidence/latency, POV is one feed among several fused sources, staged Maven/Foundry mission packet shown, reconnect upload presented as operator-gated sync action (not live dependency), sync idle/staged pill in topbar, contributor feed latency badges inline, no empty-card placeholders, no tech-stack advertising in UI copy.
- Foundry-compatible local export artifacts for mission events, asset states, tasks, alerts, and sync manifest.
- Seeded restricted-zone entries, dashboard-state writes, and idempotent local persistence APIs for route conflicts and restricted entries.
- Durable offline fusion spool (`tac_fuses.fusion_node.spool.FusionSpool`) with append-only event log (SQLite WAL + JSONL side-car), deterministic fused-state snapshots at configurable intervals, sync watermarks per contributor, upload receipt tracking, idempotency keys for reconnect dedup, corruption-tolerant JSONL read path that skips bad records by checksum, and redacted inspection output for operator debugging.
- Inspection script (`scripts/inspect_fusion_spool.py`) that prints a redacted spool view or JSONL integrity stats from the command line.
- Test suite for the offline fusion spool (29 tests) covering schema init, WAL mode, event append/idempotency, JSONL health stats, corruption-tolerant reads, snapshot intervals, watermarks, receipt tracking, pending events, replay-to-target, redacted inspection, concurrent reads, and custom timestamps/keys.

### Changed
- Formatted contributor-feed latency and POV telemetry as human-readable values
  and replaced the stretched world-raster POV with a local terrain/corridor view.
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

### Removed
- Removed the single-file TAC-FUSE hackathon playbook from the repo surface.
