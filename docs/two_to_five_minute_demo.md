# Two To Five Minute Demo Script

## Demo Thesis

TAC-FUSE answers one field question:

> We are guarding a route, the internet is gone, higher command is gone, and enterprise systems are unreachable. What do we do now?

The answer is not "run a model." The answer is that the hardened laptop or backpack kit remains the local C2 authority: keep the corridor guarded, retask drones, triage local cues, manage power, and queue sync for later release.

## Pre-Demo Checks

Run these before judges arrive:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv run python scripts/check_npu_runtime.py --device NPU
```

The NPU check is a supporting proof point. The demo models Alpha, Bravo,
Charlie, and Delta as edge devices with simple onboard NPU cueing. Strix is the
development proof rig for the same distributed CV lane. If Strix reports
unavailable, say: "The Strix hard-readiness lane is still integration work; the
denied-connectivity C2 demo does not depend on it." If it reports ready, use it
in the sensor-cue beat below.

On Strix, use `--require-npu` only for the optional final hardware proof check:

```bash
# Optional proof only; not required for local C2.
TAC_FUSE_SIGLIP_DEVICE=NPU uv run python scripts/check_npu_runtime.py --device NPU --model-dir models/siglip2-field-npu --require-npu
```

## 2 Minute Version

### 0:00-0:20 - Set The Problem

Say: "This is Problem Statement 2. We are guarding a route, and we just lost internet, higher command, and enterprise sync."

Show: Dashboard title and evidence card: `Cut Off Route Guard`.

### 0:20-0:55 - Local C2 Still Works

Click: `Patrol`, then `Hold`, then `Return`.

Say: "The laptop issues commands locally. The drones do not wait for Foundry, Maven, cloud inference, or command reachback."

Show: Command count and sync gate update. The gate should show local queueing, not external upload.

### 0:55-1:25 - Guard The Corridor

Show: Route Guard Corridor on the AOI and 3D field view.

Say: "The operator sees moving air and ground contacts, route corridor state, and prioritized cues in one local view."

If Strix NPU is ready, say: "Each platform can run simple onboard CV; Strix is the hard proof rig for that distributed NPU lane." Then show the NPU readiness output or prepared local cue result.

If Strix NPU is not ready, say: "The onboard cue lane degrades to deterministic local cues; C2 and route guard continue."

### 1:25-2:00 - Close Against The Rubric

Say:

- "Technical Demo: local dashboard, moving assets, commands, sync gate, and tests."
- "Military Impact: route security continues while disconnected."
- "Creativity: the backpack kit becomes the local authority and syncs later."

End on the dashboard evidence cards.

## 5 Minute Version

### 0:00-0:35 - Scenario

Set the story: route guard, denied connectivity, no command reachback. Point at `Problem Statement 2` and `Cut Off Route Guard`.

### 0:35-1:25 - Local Authority

Toggle `Offline` and issue `Patrol`, `Hold`, and `Return`. Explain that state persists locally first, then sync is staged.

### 1:25-2:10 - Swarm Tasking

Switch between feeds and show that multiple drones and the ground team are still tracked. Explain that one operator can retask the small swarm from the edge device.

### 2:10-3:00 - Corridor And Cues

Show the corridor on both sides of the view. Call out the highest-priority contact and why it matters.

For distributed device CV with Strix as hard-readiness proof:

```bash
TAC_FUSE_SIGLIP_DEVICE=NPU uv run python scripts/check_npu_runtime.py --device NPU --model-dir models/siglip2-field-npu
```

If `ready` is true, describe the CV cue as the local NPU-supported
classification/prioritization input that each field platform should provide. If
`ready` is false, state that the hard NPU lane is still being integrated and the
C2 path remains fully demonstrable because the NPU proof is not required for
local command authority.

### 3:00-3:45 - Power And Latency

Move battery or CPU load controls. Explain what stays on in minimal power: local C2, spool, and alerting.

### 3:45-4:30 - Reconnect Boundary

Toggle `Online`, then release the staged packet. Explain that reconnect is a controlled sync action, not a dependency for local operations.

### 4:30-5:00 - Judge Close

Close with the three evidence cards:

- Technical Demo 35%: working local app, tests, visual proof, distributed onboard CV cues, and optional Strix hard-readiness proof.
- Military Impact 30%: route guard and drone C2 survive denied connectivity.
- Creativity 25%: edge kit as local authority with deferred enterprise sync.

## Scenario Portfolio

Keep Route Guard as the primary judging demo. The self-improvement loop should
also preserve these scenario families so the project does not become a single
scene:

- Route Guard: guard a route while cut off from internet and command.
- Convoy Overwatch: deconflict moving vehicles and drones under degraded comms.
- Checkpoint Resupply: keep relay, cue triage, and local sync for a remote checkpoint.
- Downed Drone Recovery: retask the remaining swarm when one asset drops out.
- Perimeter Unknowns: identify unknown air and ground contacts near protected movement.

## Do Not Say

- Do not lead with model accuracy.
- Do not say Intel NPU is required.
- Do not claim live Foundry/Maven dependency.
- Do not imply the dashboard is only a visualization; it represents the local C2 proof path.
