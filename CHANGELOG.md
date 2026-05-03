# Changelog

All notable changes to TAC-FUSE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Deterministic sensor emulation module (`tac_fuse.sensors`) with EO/RGB camera, IR/thermal, depth/range, and GNSS/IMU emulators that produce `SensorObservation` objects with covariance/uncertainty metadata convertible to fusion bus `SensorEvent` envelopes.
- Sensor degradation modeling for field conditions: haze, smoke, dust, rain, fog, low light, and occlusion modes affecting confidence, uncertainty, and quality scores.
- Dropped frame and stale track simulation with configurable drop rates and deterministic replay via seeded RNG.
- Multi-sensor platform emulator for coordinating observations from multiple sensors on a single drone or ground station.
- Test suite for sensor models covering determinism, degradation modes, covariance output, and fusion bus integration.
- Standalone GitHub repository metadata, CI, README, license, issue template, and PR template.
- Controlled Earth-imagery cache path (`scripts/cache_visual_assets.py`, `tac_fuse.assets.download`) that downloads only explicitly approved `auto_download: true` / `restriction: none` catalog entries, writes a local manifest, and keeps tests offline with local `file://` fixtures.
- NASA Blue Marble starter source in `configs/assets/visual_asset_sources.yaml` for immediate real Earth-raster visualization.
- Drone POV replay projection with deterministic field-condition labels.
- Intel NPU SigLIP2 adapter boundary and runtime inspection script.
- Local ray-query/BVH boundary with RTX-runtime inspection and CPU parity output shape.
- RTX prerequisite script referenced by the live demo runbook.
- Browser-based graphics emulator with a live swarm world, selected-drone POV, operator commands, online/offline queue behavior, BVH nodes, and local ray-query visualization.
- Offline-first hackathon UI that foregrounds local C2, RTX BVH, Intel NPU inference, SQLite persistence, and staged Foundry export without live/degraded mode controls.
- Foundry-compatible local export artifacts for mission events, asset states, tasks, alerts, and sync manifest.
- Seeded restricted-zone entries, dashboard-state writes, and idempotent local persistence APIs for route conflicts and restricted entries.

### Changed
- Replaced the hackathon playbook with runnable repo structure and offline validation.
- Block external sync unless connectivity is fully ONLINE; DEGRADED is now local-state-only.
- Reworked the browser emulator from a block/grid status dashboard into a more cinematic offline field-node theater with terrain styling, compact panels, and visible local hardware proof points.
- Wired the browser theater to use the cached Earth imagery layer when present, with procedural terrain retained as the offline fallback.

### Removed
- Removed the single-file TAC-FUSE hackathon playbook from the repo surface.
