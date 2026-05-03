# Alpha Test Plan

TAC-FUSE alpha quality is measured by one operator story: a route is being
guarded, outside connectivity is gone, and the local edge kit still commands
the swarm. This test list keeps the demo improving toward that story while
making the accelerator lanes real instead of decorative.

## Alpha Gates

### Route Guard C2

Pass criteria:

- The first screen starts in the Route Guard scenario with no cloud dependency.
- Patrol, Hold, Return, and Abort write local mission state,
  audit log entries, and staged sync records before any upload path can run.
- Offline and Degraded modes block external sync; Online only releases staged
  packets by operator action.
- Alpha, Bravo, Charlie, Delta, and Team 1 remain known tracks with object
  permanence across cue updates.
- Corridor path safety is automatic; operators should not have to manually
  trigger geometry work to keep the route guarded.

Validation:

```bash
uv run pytest tests/test_local_c2_authority.py tests/test_mission_state.py tests/test_connectivity.py -q
```

### Visual Polish

Pass criteria:

- All visible UI copy uses capitalized display labels.
- No label, chip, telemetry line, or contact annotation escapes its container.
- The 3D Field C2 View is the primary working map; keep the 2D AOI Overview on a
  separate tab instead of showing both maps on the same screen.
- The field view shows only the information needed for the current operator
  decision; detail moves to hover, selection, or secondary panels.
- Aerial contacts enter from the AOI edge and ground contacts move along
  plausible field paths.

Validation:

```bash
node --check web/app.js
npm run test:visual
```

### RTX Pathing

Pass criteria:

- Automatic corridor guard consumes the same fused contacts that the cue labeler sees.
- The pathing lane scores corridor edges, line of sight, RF-denial volumes,
  unknown contacts, standoff, battery, and latency.
- On Strix, RTX ray-tracing cores or CUDA geometry back the spatial-query
  path when available.
- Deterministic software validation returns the same decision shape for offline tests.
- The UI names the corridor state, not a vague compute stage or manual route action.

Validation:

```bash
uv run pytest tests/test_ray_query.py -q
uv run python scripts/check_ray_runtime.py
```

Strix hardware proof:

```bash
uv run python scripts/check_ray_runtime.py --require-rtx
```

### NPU Zero-Shot Labels

Pass criteria:

- Alpha, Bravo, Charlie, and Delta model onboard cueing as local device outputs;
  Strix is the proof rig for that lane.
- The NPU path uses the zero-shot labeler as a naive cue source for rendered
  local objects such as wheeled vehicles, small UAS, personnel, RF sources, and
  obstructions.
- Zero-shot results remain pseudo-classifications unless a caller explicitly
  opts into detection payloads.
- The fusion node ties cues to persistent tracks and sources; the labeler does
  not own object permanence.

Validation:

```bash
uv run pytest tests/test_zero_shot_vision.py tests/test_npu_siglip.py -q
```

Strix hardware proof:

```bash
TAC_FUSE_SIGLIP_DEVICE=NPU uv run python scripts/check_npu_runtime.py --device NPU --model-dir models/siglip2-field-npu
```

### Trained Model Readiness

Pass criteria:

- The zero-shot and future trained classifiers share one output contract:
  track ID, source ID, frame path, class label, confidence, optional box or
  mask, device, model ID, and inference latency.
- The trained model can replace the zero-shot labeler without changing local
  C2, route pathing, sync, or alert contracts.
- Missing model assets fail clearly in the hardware lane and never block core
  route-guard C2.

Validation:

```bash
uv run pytest tests/test_zero_shot_vision.py tests/test_npu_siglip.py tests/test_npu_trainer_int8.py -q
```

### Scenario Portfolio

Route Guard remains the judging path. The alpha loop must also keep these
scenarios available so the demo does not become a single hard-coded scene:

- Route Guard: maintain a protected corridor while cut off.
- Convoy Overwatch: deconflict moving vehicles and drones under degraded comms.
- Checkpoint Resupply: preserve relay, cue triage, and staged sync for a remote
  checkpoint.
- Downed Drone Recovery: retask remaining assets after one platform drops out.
- Perimeter Unknowns: classify and track unknown air and ground contacts near
  protected movement.

## Alpha Run Order

1. Explore the current dashboard, local C2 state path, ray-query path, and NPU
   label path.
2. Create missing contracts and scenario fixtures.
3. Beautify the operator view with Playwright screenshots and assertions.
4. Cleanup copy, dead panels, duplicate map stories, and fragile demo branches.

Use `tasks/alpha_test_polish_tasks.yaml` as the queueable AlphaHENG task list
for the next polish run.
