# Changelog

All notable changes to TAC-FUSE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- Reframed README, agent guidance, and demo copy around hardened-laptop C2 continuity instead of Intel NPU-centric inference.
- Replaced the hackathon playbook with runnable repo structure and offline validation.
- Block external sync unless connectivity is fully ONLINE; DEGRADED is now local-state-only.
- Reworked the browser emulator from a block/grid status dashboard into a more cinematic offline field-node theater with terrain styling, compact panels, and visible local hardware proof points.
- Wired the browser theater to use the cached Earth imagery layer when present, with procedural terrain retained as the offline fallback.
- Reframed BVH copy as collision prevention and route optimization, with ray-tracing cores shown as the acceleration path for local spatial queries.
- Restyled the web demo UI as a laptop-local fusion node with contributor feeds (freshness/confidence/latency), selected feed as POV, feed quality panel, staged packet panel, sync watermark, and operator-gated upload button.

### Removed
- Removed the single-file TAC-FUSE hackathon playbook from the repo surface.
