# Changelog

All notable changes to TAC-FUSE will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Standalone GitHub repository metadata, CI, README, license, issue template, and PR template.
- Drone POV replay projection with deterministic field-condition labels.
- Intel NPU SigLIP2 adapter boundary and runtime inspection script.
- Local ray-query/BVH boundary with RTX-runtime inspection and CPU parity output shape.
- RTX prerequisite script referenced by the live demo runbook.
- Browser-based graphics emulator with a live swarm world, selected-drone POV, operator commands, online/offline queue behavior, BVH nodes, and local ray-query visualization.
- Foundry-compatible local export artifacts for mission events, asset states, tasks, alerts, and sync manifest.
- Seeded restricted-zone entries, dashboard-state writes, and idempotent local persistence APIs for route conflicts and restricted entries.

### Changed
- Replaced the hackathon playbook with runnable repo structure and offline validation.
- Block external sync unless connectivity is fully ONLINE; DEGRADED is now local-state-only.

### Removed
- Removed the single-file TAC-FUSE hackathon playbook from the repo surface.
