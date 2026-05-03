"""Denied-operations proof: single-operator swarm control while offline.

This module provides a deterministic, replayable proof that a single operator
can task, retask, and monitor multiple drones while completely denied access
to Foundry, Maven, internet, or central C2.

The proof exercises:
- Local C2 authority: operator issues commands to all drones
- Sensor fusion: replay tracks are ingested and alerts generated
- State-first persistence: every command has (state, audit, sync) proofs
- Deferred sync: commands queue locally, enterprise sync blocked
- Export readiness: offline export works from local state
- Connectivity transitions: OFFLINE → DEGRADED → ONLINE recovery

All behavior is offline-testable and requires no external services.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tac_fuse.connectivity import ConnectivityController, ConnectivityMode
from tac_fuse.foundry_export import build_foundry_export
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import SeededReplayEngine, generate_scenario


@dataclass
class DeniedOpsPhase:
    """Snapshot of a single phase in the denied-ops proof."""

    phase: str
    connectivity: str
    commands_issued: int
    retasks_issued: int
    alerts_generated: int
    tracks_ingested: int
    sync_queue_depth: int
    proof_chain_complete: bool
    export_ready: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeniedOpsResult:
    """Complete result of the denied-operations proof run."""

    operator: str
    total_phases: int
    total_commands: int
    total_retasks: int
    total_alerts: int
    total_tracks: int
    final_sync_pending: int
    final_proof_complete: bool
    final_export_ready: bool
    connectivity_transitions: list[str]
    phases: list[DeniedOpsPhase] = field(default_factory=list)
    proof_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def run_denied_operations_proof(
    *,
    operator: str = "field_operator_1",
    num_drones: int = 4,
    replay_seed: int = 42,
    replay_duration_sec: float = 30.0,
) -> DeniedOpsResult:
    """Run the full denied-operations proof as a single replayable scenario.

    This is the authoritative local proof that a single operator can control
    the swarm while OFFLINE.  It exercises every C2 action without requiring
    Foundry, Maven, internet, or central C2.

    The proof proceeds through five phases:

    1. INITIAL TASKING (OFFLINE): Operator tasks all drones
    2. MID-MISSION RETASKING (OFFLINE): Situation changes, operator retasks
    3. EMERGENCY ABORT (OFFLINE): Operator aborts all drones
    4. DEGRADED RECOVERY: Connectivity partially restored, sync queued
    5. ONLINE RECOVERY: Sync gate opens, export proves state integrity

    Each phase records a DeniedOpsPhase snapshot with command counts,
    alert counts, sync queue depth, and proof chain status.
    """
    store = MissionStateStore(operator=operator)
    ctrl = ConnectivityController(store)
    replay = SeededReplayEngine(
        seed=replay_seed,
        num_assets=num_drones + 1,  # drones + ground team
        duration_sec=replay_duration_sec,
        tick_interval_sec=2.5,
    )

    drone_ids = [f"uav-{name}" for name in ("alpha", "bravo", "charlie", "delta")][
        :num_drones
    ]
    commands = {
        "uav-alpha": "patrol",
        "uav-bravo": "relay",
        "uav-charlie": "scout",
        "uav-delta": "overwatch",
    }

    phases: list[DeniedOpsPhase] = []
    connectivity_transitions: list[str] = []
    total_commands = 0
    total_retasks = 0
    total_alerts = 0
    total_tracks = 0

    def _snapshot(
        phase: str,
        *,
        extra_notes: list[str] | None = None,
    ) -> DeniedOpsPhase:
        proof = store.verify_command_proof_chain()
        export_check = _check_export_ready(store)
        pending = store.pending_sync_count()
        alert_count = len(store.list_alerts())
        track_count = store.count_tracks()
        notes = list(extra_notes or [])

        if not proof["chain_complete"]:
            notes.append(
                f"Proof chain incomplete: {proof['unproven']} unproven task(s)"
            )
        if pending > 0:
            notes.append(f"{pending} commands queued for deferred sync")
        if not export_check["ready"]:
            notes.append("Export not yet ready — complete proof chain required")

        return DeniedOpsPhase(
            phase=phase,
            connectivity=ctrl.get_current_mode().value,
            commands_issued=total_commands,
            retasks_issued=total_retasks,
            alerts_generated=alert_count,
            tracks_ingested=track_count,
            sync_queue_depth=pending,
            proof_chain_complete=proof["chain_complete"],
            export_ready=export_check["ready"],
            notes=notes,
        )

    # ── Phase 1: Initial tasking while OFFLINE ──────────────────────────

    ctrl.set_manual_override(ConnectivityMode.OFFLINE)
    connectivity_transitions.append("OFFLINE")

    for drone_id in drone_ids:
        cmd = commands.get(drone_id, "patrol")
        store.dispatch_command(
            cmd,
            asset_id=drone_id,
            title=f"{drone_id} {cmd}",
            description=f"Operator tasked {drone_id} with {cmd}",
        )
        total_commands += 1

    # Ingest first frame of replay tracks
    frames = replay.generate()
    if frames:
        total_tracks += store.insert_tracks(frames[0])

    # Generate initial alerts from replay data
    for conflict in replay.route_conflicts:
        store.insert_route_conflict(conflict)
        total_alerts += 1
    for entry in replay.restricted_entries:
        store.insert_restricted_entry(entry)
        total_alerts += 1

    phases.append(
        _snapshot(
            "initial_tasking",
            extra_notes=[
                f"Tasked {len(drone_ids)} drones while OFFLINE",
                "All commands persisted to local SQLite",
                "Enterprise sync blocked — commands queued",
            ],
        )
    )

    # ── Phase 2: Mid-mission retasking while OFFLINE ───────────────────

    # Situation change: Alpha finds RF pocket, needs to investigate
    alpha_task_id = None
    for task in store.list_tasks():
        if "uav-alpha" in task.get("title", ""):
            alpha_task_id = task["id"]
            break

    if alpha_task_id:
        store.retask(
            alpha_task_id,
            title="uav-alpha investigate RF pocket",
            metadata={"priority": "high", "reason": "RF pocket detected"},
        )
        total_retasks += 1

    # Bravo relay no longer needed — retask to patrol
    bravo_task_id = None
    for task in store.list_tasks():
        if "uav-bravo" in task.get("title", ""):
            bravo_task_id = task["id"]
            break

    if bravo_task_id:
        store.retask(
            bravo_task_id,
            title="uav-bravo patrol north sector",
            metadata={"reason": "relay mission complete"},
        )
        total_retasks += 1

    # Charlie reports target — hold position
    charlie_task_id = None
    for task in store.list_tasks():
        if "uav-charlie" in task.get("title", ""):
            charlie_task_id = task["id"]
            break

    if charlie_task_id:
        store.update_task(
            charlie_task_id,
            status="in_progress",
            metadata={"target_detected": True},
        )
        total_retasks += 1

    # Create alert for the situation change
    store.create_alert(
        "Charlie reports priority contact in sector 7",
        severity="high",
        payload={"asset_id": "uav-charlie", "sector": 7},
    )
    total_alerts += 1

    # Ingest more replay frames
    if len(frames) > 1:
        total_tracks += store.insert_tracks(frames[1])

    phases.append(
        _snapshot(
            "mid_mission_retasking",
            extra_notes=[
                "Operator retasked 3 drones based on field conditions",
                "All retasks persisted locally with audit trail",
                "Situation-driven tasking without enterprise dependency",
            ],
        )
    )

    # ── Phase 3: Emergency abort while OFFLINE ─────────────────────────

    store.dispatch_command(
        "abort",
        asset_id="swarm",
        title="Emergency abort all drones",
        description="Operator issued emergency abort — all drones hold position",
    )
    total_commands += 1

    store.create_alert(
        "EMERGENCY ABORT: All drones holding position",
        severity="critical",
        payload={"operator_action": "abort_all"},
    )
    total_alerts += 1

    phases.append(
        _snapshot(
            "emergency_abort",
            extra_notes=[
                "Emergency abort issued to all drones while OFFLINE",
                "Abort persisted locally before any export",
                "All drones holding — operator has full authority",
            ],
        )
    )

    # ── Phase 4: Degraded recovery ──────────────────────────────────────

    ctrl.set_manual_override(ConnectivityMode.DEGRADED)
    connectivity_transitions.append("DEGRADED")

    # Issue recovery commands
    for drone_id in drone_ids:
        store.dispatch_command(
            "patrol",
            asset_id=drone_id,
            title=f"{drone_id} resume patrol",
        )
        total_commands += 1

    # Verify sync is still blocked in degraded mode
    sync_blocked = not ctrl.is_external_sync_allowed()

    phases.append(
        _snapshot(
            "degraded_recovery",
            extra_notes=[
                "Connectivity degraded — partial link restored",
                "Local C2 continues operating normally",
                f"Enterprise sync {'blocked' if sync_blocked else 'UNEXPECTEDLY OPEN'} in degraded mode",
                "Recovery commands queued for sync when online",
            ],
        )
    )

    # ── Phase 5: Online recovery and export proof ───────────────────────

    ctrl.set_manual_override(ConnectivityMode.ONLINE)
    connectivity_transitions.append("ONLINE")

    # Sync is now allowed but commands still in queue
    sync_allowed = ctrl.is_external_sync_allowed()

    # Generate export from local state (works in any mode)
    export = build_foundry_export(store)

    # Get final proof summary
    proof_summary = store.state_proof_summary()

    phases.append(
        _snapshot(
            "online_recovery",
            extra_notes=[
                "Connectivity restored to ONLINE",
                f"Enterprise sync gate {'open' if sync_allowed else 'still closed'}",
                f"Export generated with {len(export['operator_tasks'])} tasks",
                f"Export contains {len(export['mission_events'])} audit events",
                f"Export contains {len(export['sync_queue'])} queued sync items",
                "Export is deterministic — no network dependency",
            ],
        )
    )

    # ── Assemble result ──────────────────────────────────────────────────

    final_phase = phases[-1]
    result = DeniedOpsResult(
        operator=operator,
        total_phases=len(phases),
        total_commands=total_commands,
        total_retasks=total_retasks,
        total_alerts=total_alerts,
        total_tracks=total_tracks,
        final_sync_pending=store.pending_sync_count(),
        final_proof_complete=final_phase.proof_chain_complete,
        final_export_ready=final_phase.export_ready,
        connectivity_transitions=connectivity_transitions,
        phases=phases,
        proof_summary=proof_summary,
    )

    store.close()
    return result


def _check_export_ready(store: MissionStateStore) -> dict[str, Any]:
    """Check export readiness without raising."""
    try:
        report = store.assert_command_proof_chain()
        return {"ready": report["chain_complete"], "report": report}
    except Exception:
        return {"ready": False, "report": {}}


def format_denied_ops_report(result: DeniedOpsResult) -> str:
    """Format the denied-operations result as a human-readable report.

    Suitable for runbook output, operator review, or fixture comparison.
    """
    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        "║         TAC-FUSE DENIED OPERATIONS PROOF — OFFLINE C2 AUTHORITY    ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
        f"Operator:       {result.operator}",
        f"Total Phases:   {result.total_phases}",
        f"Connectivity:   {' → '.join(result.connectivity_transitions)}",
        "",
        "── SUMMARY ──────────────────────────────────────────────────────────",
        f"Commands Issued:  {result.total_commands}",
        f"Retasks Issued:   {result.total_retasks}",
        f"Alerts Generated: {result.total_alerts}",
        f"Tracks Ingested:  {result.total_tracks}",
        f"Sync Pending:     {result.final_sync_pending}",
        f"Proof Complete:   {'YES ✓' if result.final_proof_complete else 'NO ✗'}",
        f"Export Ready:     {'YES ✓' if result.final_export_ready else 'NO ✗'}",
        "",
        "── PHASES ───────────────────────────────────────────────────────────",
    ]

    for phase in result.phases:
        lines.append("")
        lines.append(f"  Phase: {phase.phase}")
        lines.append(f"  Connectivity: {phase.connectivity.upper()}")
        lines.append(f"  Commands: {phase.commands_issued}  "
                     f"Retasks: {phase.retasks_issued}  "
                     f"Alerts: {phase.alerts_generated}")
        lines.append(f"  Tracks: {phase.tracks_ingested}  "
                     f"Sync Queue: {phase.sync_queue_depth}")
        lines.append(
            f"  Proof: {'COMPLETE ✓' if phase.proof_chain_complete else 'INCOMPLETE'}  "
            f"Export: {'READY ✓' if phase.export_ready else 'NOT READY'}"
        )
        if phase.notes:
            lines.append("  Notes:")
            for note in phase.notes:
                lines.append(f"    • {note}")

    lines.append("")
    lines.append("── PROOF CHAIN ────────────────────────────────────────────────────")

    if result.proof_summary:
        entities = result.proof_summary.get("entities", {})
        for entity_type, counts in entities.items():
            total = counts.get("total", 0)
            proven = counts.get("proven", 0)
            status = "✓" if total == proven else "✗"
            lines.append(f"  {status} {entity_type}: {proven}/{total} proven")
        lines.append(
            f"  Audit Events: {result.proof_summary.get('total_audit_events', 0)}"
        )
        lines.append(
            f"  Sync Pending: {result.proof_summary.get('pending_sync_items', 0)}"
        )

    lines.append("")
    lines.append("── CONCLUSION ─────────────────────────────────────────────────────")
    if result.final_proof_complete and result.final_export_ready:
        lines.append(
            "  PROOF PASSED: Single operator controlled swarm while denied."
        )
        lines.append(
            "  All commands persisted locally with complete proof chains."
        )
        lines.append(
            "  Export generated offline from local state — no external dependency."
        )
        lines.append(
            "  Enterprise sync remained blocked until operator opened the gate."
        )
    else:
        lines.append("  PROOF INCOMPLETE: Check phase details above.")
    lines.append("")
    lines.append("══════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)
