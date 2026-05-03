# TAC-FUSE Agents Local Operating Guide

TAC-FUSE is a standalone local-first demo repo under AlphaHENG. Treat this file as the local operating contract when editing anything below `contrib/TAC-FUSE/`.

## Working Defaults

- Use Python 3.12 and `uv`.
- Run `uv sync --extra dev` for local development.
- Run `uv run pytest` and `uv run ruff check src tests` before handing off changes.
- Keep tests offline. They must not require Foundry, internet access, Hugging Face downloads, OpenVINO, an Intel NPU, or RTX hardware.
- Update `CHANGELOG.md` for behavior, interface, demo workflow, dependency, and validation changes.

## Problem Fit

- Target **Problem Statement 2: Edge Deployments and Drone Operation**.
- Optimize for a hardened laptop/backpack edge kit that preserves C2 when central connectivity is degraded or denied.
- The core product is local operator authority over drones: tasking, retasking, state, alerts, audit, and sync queue continuity.
- Treat object detection and accelerator inference as supporting examples after the C2 loop works. Do not make Intel NPU availability, model accuracy, or detection benchmarks the center of the application.
- Keep `docs/problem_statement_alignment.md` aligned with README, runbook, and UI copy when the project thesis changes.

## Demo Rules

- Core actions write local SQLite state before any external sync attempt.
- Foundry integration stays behind export/upload boundaries. Core runtime must not depend on Foundry API responses.
- Intel NPU SigLIP2 support stays optional and lazy. Import OpenVINO only inside the NPU adapter path, and never gate core C2 behavior on it.
- `google/siglip2-base-patch16-224` model assets are not committed. Use `models/` or `TAC_FUSE_SIGLIP_MODEL_DIR` for local OpenVINO IR files.
- The POV visualization should work from static files with deterministic local demo data.
- RTX and CPU spatial parity work may be added, but CPU fallback tests remain mandatory.

## Repository Shape

- `src/tac_fuse/` contains state management, replay generation, POV projection, and accelerator adapters.
- `web/` contains the local operator visualization.
- `tests/` contains focused offline validation.
- `.github/` contains GitHub workflow and collaboration metadata.
