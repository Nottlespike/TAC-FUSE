# Problem Statement Alignment

TAC-FUSE targets **Problem Statement 2: Edge Deployments and Drone Operation**.

The project thesis is not "run a model on an Intel NPU." The thesis is:

> A front-line operator keeps command-and-control authority over autonomous
> systems from a hardened laptop or backpack-class kit when connectivity to
> central infrastructure is intermittent, degraded, or fully denied.

## Core Scenario

The demo should prove that a single operator can:

- see the local tactical picture from cached maps, local state, and drone feeds,
- task or retask a small autonomous swarm from the edge device,
- preserve mission state, audit events, and outbound sync records locally,
- receive prioritized local alerts from sensor and geometry processing,
- continue operating when Foundry, Maven, internet, or central C2 links are down,
- reconcile/export when connectivity returns.

Route Guard is the primary two-to-five-minute scenario, but it is not the only
valid mission. TAC-FUSE should also support Convoy Overwatch, Checkpoint
Resupply, Downed Drone Recovery, and Perimeter Unknowns. Each scenario keeps
the same structure: denied connectivity, local C2 authority, BVH/ray geometry
for route or movement safety, and distributed onboard CV cues for identifying
unknowns.

## Priority Order

1. **Local C2 authority**: operator commands apply locally and persist first.
2. **Disconnected resilience**: offline/degraded modes never block mission work.
3. **Drone coordination**: multiple vehicles can be monitored, tasked, and deconflicted.
4. **Sensor fusion and alerting**: video/RF/position observations become useful local cues.
5. **Power/latency posture**: laptop/backpack operation stays lightweight and bounded.
6. **Enterprise sync boundary**: Foundry/Maven export is a deferred bridge, not a dependency.

## Accelerator Role

MPUs, NPUs, GPUs, and RTX paths are **supporting capabilities**. They demonstrate
that the laptop and each field platform can process local sensor data when
useful, but they are not the application's center of gravity.

Object detection should appear as a proof point only after the local C2 loop is
working: "once identifiable objects or unknown contacts exist in the feed, each
edge device can classify or prioritize them locally." Strix is the
hardware-readiness proof rig for this distributed NPU concept; it is not
required as a gate. If inference fails, the operator must still retain C2, map
context, tasking, logs, and sync queue continuity.

## Non-Goals

- Do not optimize the demo around model accuracy or benchmark charts.
- Do not require cloud inference, model downloads, or live Foundry access.
- Do not make Intel NPU availability a gate for the core workflow.
- Do not let accelerator integration displace operator tasking, local state, or swarm control.
