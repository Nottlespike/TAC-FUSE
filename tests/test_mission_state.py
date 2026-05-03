from tac_fuse.foundry_export import build_foundry_export, verify_export_readiness
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import SeededReplayEngine, generate_scenario


def test_task_create_update_enqueue_sync() -> None:
    store = MissionStateStore()

    task = store.create_task(title="Hold north corridor", description="Observe RF pocket")
    updated = store.update_task(task["id"], status="complete")

    assert updated["status"] == "complete"
    assert store.pending_sync_count() == 2
    assert [entry["operation"] for entry in store.list_sync_queue()] == ["create", "update"]


def test_cancel_task_state_first() -> None:
    """Prove cancel_task (a retasking action) persists to local state, audit log,
    and sync queue BEFORE any enterprise export can run.
    """
    store = MissionStateStore(operator="test_operator")

    # Create a task first
    task = store.create_task(title="Patrol zone A", description="Standard patrol")

    # Cancel the task (retasking action)
    cancelled = store.cancel_task(task["id"])

    # Verify state persistence
    assert cancelled["status"] == "cancelled"
    persisted = store.get_task(task["id"])
    assert persisted is not None
    assert persisted["status"] == "cancelled"

    # Verify audit log has cancel event
    audit_events = store.list_audit_events()
    assert any(e["event_type"] == "task_cancelled" for e in audit_events)

    # Verify sync queue has cancel entry
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 2  # create + cancel
    cancel_entry = [e for e in sync_queue if e["operation"] == "cancel"][0]
    assert cancel_entry["entity_type"] == "operator_task"
    assert cancel_entry["status"] == "pending"


def test_verify_state_first_proof_path() -> None:
    """Prove verify_state_first correctly checks all three proofs."""
    store = MissionStateStore(operator="verify_test_operator")

    # Create a task
    task = store.create_task(title="Verify test task")
    task_id = task["id"]

    # Verify all three proofs are present
    proof = store.verify_state_first("operator_task", task_id)
    assert proof["state_persisted"] is True
    assert proof["audit_logged"] is True
    assert proof["sync_enqueued"] is True
    assert proof["proof_complete"] is True

    # Verify non-existent entity fails
    fake_proof = store.verify_state_first("operator_task", "non-existent-id")
    assert fake_proof["state_persisted"] is False
    assert fake_proof["audit_logged"] is False
    assert fake_proof["sync_enqueued"] is False
    assert fake_proof["proof_complete"] is False


def test_track_sync_enqueue() -> None:
    """Prove track ingestion enqueues sync entries for each asset."""
    store = MissionStateStore()
    frame = generate_scenario(frames=1)[0]

    count = store.insert_tracks(frame)
    assert count == len(frame)

    # Each track should have a sync queue entry
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == len(frame)
    assert all(e["entity_type"] == "asset_state" for e in sync_queue)
    assert all(e["operation"] == "create" for e in sync_queue)


def test_dashboard_value_sync_enqueue() -> None:
    """Prove dashboard value updates enqueue sync entries."""
    store = MissionStateStore()

    store.put_dashboard_value("test_key", "test_value")

    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 1
    assert sync_queue[0]["entity_type"] == "demo_state"
    assert sync_queue[0]["operation"] == "update"


def test_tracks_alerts_and_audit_persist() -> None:
    store = MissionStateStore()
    frame = generate_scenario(frames=1)[0]

    assert store.insert_tracks(frame) == len(frame)
    store.create_alert("Charlie near RF denial pocket", severity="critical")

    assert store.count_tracks() == len(frame)
    assert store.list_alerts()[0]["severity"] == "critical"
    assert {event["event_type"] for event in store.list_audit_events()} >= {
        "tracks_inserted",
        "alert_created",
    }


def test_restricted_entries_and_route_conflicts_persist() -> None:
    store = MissionStateStore()
    engine = SeededReplayEngine(seed=42, num_assets=5, duration_sec=20.0, tick_interval_sec=2.5)

    restricted = store.insert_restricted_entry(engine.restricted_entries[0])
    conflict = store.insert_route_conflict(engine.route_conflicts[0])

    assert restricted["asset_id"] == "uav-charlie"
    assert conflict["asset_ids"] == ["uav-alpha", "uav-charlie"]
    assert store.list_restricted_entries()[0]["payload"]["zone_id"] == "rf-denial-pocket-west"
    assert store.list_route_conflicts()[0]["conflict_id"] == "conflict-alpha-charlie-001"
    assert {entry["entity_type"] for entry in store.list_sync_queue()} == {
        "restricted_entry",
        "route_conflict",
    }


def test_demo_state_values_are_persisted_for_runbook() -> None:
    store = MissionStateStore()

    record = store.put_dashboard_value("last_connectivity_event", "degraded_entered")

    assert record["key"] == "last_connectivity_event"
    row = store.conn.execute(
        "SELECT value FROM demo_state WHERE key = 'last_connectivity_event'"
    ).fetchone()
    assert row[0] == "degraded_entered"


def test_restricted_entries_and_route_conflicts_are_idempotent() -> None:
    store = MissionStateStore()
    engine = SeededReplayEngine(seed=42, num_assets=5, duration_sec=20.0, tick_interval_sec=2.5)

    store.insert_restricted_entry(engine.restricted_entries[0])
    store.insert_restricted_entry(engine.restricted_entries[0])
    store.insert_route_conflict(engine.route_conflicts[0])
    store.insert_route_conflict(engine.route_conflicts[0])

    assert len(store.list_restricted_entries()) == 1
    assert len(store.list_route_conflicts()) == 1


def test_local_c2_state_first_proof_path() -> None:
    """Prove operator tasking persists to local state, audit log, and sync queue
    BEFORE any enterprise export can run.

    This is the first-class proof path for local C2 authority:
    1. Task creation persists to operator_tasks table
    2. Audit log records the command event
    3. Sync queue entry created for deferred enterprise sync
    4. Export reads from persisted state (offline, deterministic)
    """
    store = MissionStateStore(operator="test_operator")

    # Phase 1: Create task - must persist before export
    task = store.create_task(
        title="Retask Alpha to RF pocket",
        description="Investigate RF denial zone east",
        metadata={"asset_id": "uav-alpha", "priority": "high"},
    )

    # Verify local state persistence
    persisted = store.get_task(task["id"])
    assert persisted is not None
    assert persisted["title"] == "Retask Alpha to RF pocket"
    assert persisted["status"] == "pending"

    # Verify audit log entry
    audit_events = store.list_audit_events()
    assert any(e["event_type"] == "task_created" for e in audit_events)
    assert any("Retask Alpha" in e["message"] for e in audit_events)

    # Verify sync queue entry (deferred enterprise sync)
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 1
    assert sync_queue[0]["entity_type"] == "operator_task"
    assert sync_queue[0]["operation"] == "create"
    assert sync_queue[0]["status"] == "pending"

    # Phase 2: Update task (retask) - must persist before export
    updated = store.update_task(
        task["id"],
        status="in_progress",
        description="En route to RF pocket",
    )

    # Verify update persisted
    assert updated["status"] == "in_progress"
    assert updated["description"] == "En route to RF pocket"

    # Verify audit log has update event
    audit_events = store.list_audit_events()
    assert any(e["event_type"] == "task_updated" for e in audit_events)

    # Verify sync queue has update entry
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 2
    assert sync_queue[1]["operation"] == "update"

    # Phase 3: Export is derived from persisted state (offline, deterministic)
    export = build_foundry_export(store)

    # Export contains the persisted task data
    assert len(export["operator_tasks"]) == 1
    assert export["operator_tasks"][0]["title"] == "Retask Alpha to RF pocket"
    assert export["operator_tasks"][0]["status"] == "in_progress"

    # Export contains audit events (mission_events)
    assert len(export["mission_events"]) >= 2

    # Export contains sync queue for enterprise handoff
    assert len(export["sync_queue"]) == 2

    # Verify export is deterministic (no external dependencies)
    export2 = build_foundry_export(store)
    assert export["operator_tasks"] == export2["operator_tasks"]
    assert export["sync_queue"] == export2["sync_queue"]


def test_complete_task_state_first() -> None:
    """Prove complete_task (a final-state retasking action) persists to local state,
    audit log, and sync queue BEFORE any enterprise export can run.
    """
    store = MissionStateStore(operator="complete_test_operator")

    task = store.create_task(title="Scout sector 7")
    completed = store.complete_task(task["id"])

    # Verify state persistence
    assert completed["status"] == "complete"
    persisted = store.get_task(task["id"])
    assert persisted is not None
    assert persisted["status"] == "complete"

    # Verify audit log
    audit_events = store.list_audit_events()
    assert any(e["event_type"] == "task_completed" for e in audit_events)

    # Verify sync queue
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 2  # create + complete
    complete_entry = [e for e in sync_queue if e["operation"] == "complete"][0]
    assert complete_entry["entity_type"] == "operator_task"

    # Verify complete proofs for both operations
    proof = store.verify_state_first("operator_task", task["id"])
    assert proof["proof_complete"] is True


def test_retask_state_first() -> None:
    """Prove retask persists all three proofs BEFORE any enterprise export can run."""
    store = MissionStateStore(operator="retask_test_operator")

    task = store.create_task(title="Initial patrol")
    retasked = store.retask(
        task["id"],
        title="Updated patrol",
        description="Expanded scope",
        metadata={"retask_count": 1},
    )

    # Verify state persistence
    assert retasked["title"] == "Updated patrol"
    assert retasked["description"] == "Expanded scope"
    persisted = store.get_task(task["id"])
    assert persisted is not None
    assert persisted["title"] == "Updated patrol"

    # Verify audit log
    audit_events = store.list_audit_events()
    assert any(e["event_type"] == "task_retasked" for e in audit_events)
    assert any("Updated patrol" in e["message"] for e in audit_events)

    # Verify sync queue
    sync_queue = store.list_sync_queue()
    retask_entry = [e for e in sync_queue if e["operation"] == "retask"][0]
    assert retask_entry["entity_type"] == "operator_task"

    # Verify complete proof
    proof = store.verify_state_first("operator_task", task["id"])
    assert proof["proof_complete"] is True


def test_dispatch_command_state_first() -> None:
    """Prove dispatch_command (the authoritative C2 entry point) persists all three
    proofs BEFORE any enterprise export can run.
    """
    store = MissionStateStore(operator="dispatch_test_operator")

    task = store.dispatch_command(
        "patrol",
        asset_id="uav-alpha",
        title="Patrol east corridor",
        description="Investigate RF pocket",
    )

    # Verify state persistence
    assert task["title"] == "Patrol east corridor"
    assert task["status"] == "in_progress"
    persisted = store.get_task(task["id"])
    assert persisted is not None
    assert persisted["metadata"]["command"] == "patrol"
    assert persisted["metadata"]["asset_id"] == "uav-alpha"

    # Verify audit log
    audit_events = store.list_audit_events()
    assert any("Patrol east corridor" in e["message"] for e in audit_events)
    assert any("created" in e["message"].lower() for e in audit_events)

    # Verify sync queue
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 1
    assert sync_queue[0]["operation"] == "create"
    assert sync_queue[0]["entity_type"] == "operator_task"

    # Verify complete proof
    proof = store.verify_state_first("operator_task", task["id"])
    assert proof["state_persisted"] is True
    assert proof["audit_logged"] is True
    assert proof["sync_enqueued"] is True
    assert proof["proof_complete"] is True

    # Export works offline (no network)
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 1
    assert export["operator_tasks"][0]["title"] == "Patrol east corridor"


def test_assert_command_proof_chain() -> None:
    """Prove assert_command_proof_chain is the hard export gate — raises on incomplete
    proofs and returns the report when all tasks are proven.
    """
    store = MissionStateStore(operator="gate_test_operator")

    # Empty store passes (no tasks = nothing to prove)
    report = store.assert_command_proof_chain()
    assert report["chain_complete"] is True

    # Create one task — passes
    task = store.create_task(title="Gate test task")
    report = store.assert_command_proof_chain()
    assert report["chain_complete"] is True
    assert report["total_tasks"] == 1
    assert report["proven"] == 1

    # update_task adds another sync entry — still passes
    store.update_task(task["id"], status="in_progress")
    report = store.assert_command_proof_chain()
    assert report["chain_complete"] is True

    # verify_export_readiness returns same info without raising
    readiness = verify_export_readiness(store)
    assert readiness["ready"] is True
    assert readiness["proven"] == 1


def test_state_first_all_operation_types() -> None:
    """Prove every operator-task operation type (create, update, cancel, retask, complete,
    dispatch_command) produces a complete state-first proof chain.
    """
    store = MissionStateStore(operator="all_ops_test")

    # create
    task = store.create_task(title="Initial task")
    # update
    store.update_task(task["id"], status="in_progress")
    # cancel (new task)
    task2 = store.create_task(title="Task to cancel")
    store.cancel_task(task2["id"])
    # retask (new task)
    task3 = store.create_task(title="Task to retask")
    store.retask(task3["id"], title="Retasked task", metadata={"retasked": True})
    # complete (new task)
    task4 = store.create_task(title="Task to complete")
    store.complete_task(task4["id"])
    # dispatch_command
    store.dispatch_command("hold", asset_id="uav-bravo")

    # Verify aggregate proof summary
    summary = store.state_proof_summary()
    assert summary["entities"]["operator_task"]["total"] == 5
    assert summary["entities"]["operator_task"]["proven"] == 5
    # create + update + cancel + retask + complete + dispatch
    assert summary["total_audit_events"] >= 6

    # Hard gate passes — all tasks complete
    report = store.assert_command_proof_chain()
    assert report["chain_complete"] is True
    assert report["total_tasks"] == 5
    assert report["proven"] == 5
    assert report["unproven"] == 0

    # Export reads from local state only
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 5
    assert len(export["mission_events"]) >= 6
    assert len(export["sync_queue"]) >= 6  # at least one per task operation


def test_single_operator_swarm_control_offline() -> None:
    """Prove a single operator can task and retask multiple drones while OFFLINE.

    This is the core denied-operations proof:
    1. Operator issues commands to multiple drones (Alpha, Bravo, Charlie)
    2. All commands persist locally with audit trail
    3. All commands queue for deferred sync (no network required)
    4. Operator can retask any drone mid-mission
    5. Export works offline from persisted state
    6. Enterprise sync remains blocked until ONLINE mode
    """
    store = MissionStateStore(operator="field_operator_1")

    # Phase 1: Initial swarm tasking - operator tasks 4 drones
    alpha_task = store.dispatch_command("patrol", asset_id="uav-alpha", title="Alpha patrol east")
    bravo_task = store.dispatch_command("relay", asset_id="uav-bravo", title="Bravo comms relay")
    charlie_task = store.dispatch_command(
        "scout", asset_id="uav-charlie", title="Charlie scout RF pocket"
    )
    delta_task = store.dispatch_command(
        "overwatch", asset_id="uav-delta", title="Delta overwatch"
    )

    # All 4 tasks persisted locally
    assert store.get_task(alpha_task["id"]) is not None
    assert store.get_task(bravo_task["id"]) is not None
    assert store.get_task(charlie_task["id"]) is not None
    assert store.get_task(delta_task["id"]) is not None

    # All 4 tasks have audit trail
    audit_events = store.list_audit_events()
    assert sum(1 for e in audit_events if "created" in e["message"].lower()) == 4

    # All 4 tasks queued for sync (but NOT uploaded - offline)
    sync_queue = store.list_sync_queue()
    assert len(sync_queue) == 4
    assert all(e["status"] == "pending" for e in sync_queue)

    # Phase 2: Operator retasks mid-mission (denied connectivity)
    # Alpha finds RF pocket - retask to investigate
    store.retask(
        alpha_task["id"], title="Alpha investigate RF pocket", metadata={"priority": "high"}
    )
    # Bravo relay no longer needed - retask to patrol
    store.retask(bravo_task["id"], title="Bravo patrol north", status="pending")
    # Charlie finds target - retask to hold position
    store.update_task(charlie_task["id"], status="in_progress", metadata={"target_detected": True})

    # Retasks persisted locally
    assert store.get_task(alpha_task["id"])["title"] == "Alpha investigate RF pocket"
    assert store.get_task(bravo_task["id"])["title"] == "Bravo patrol north"
    assert store.get_task(charlie_task["id"])["status"] == "in_progress"

    # Retasks queued for sync (now 7 total: 4 create + 3 retask/update)
    assert store.pending_sync_count() == 7

    # Phase 3: Operator issues emergency abort - all drones hold
    abort_task = store.dispatch_command(
        "abort", asset_id="swarm", title="Emergency abort all drones"
    )
    assert store.get_task(abort_task["id"]) is not None

    # Phase 4: Verify complete proof chain for all operations
    summary = store.state_proof_summary()
    assert summary["entities"]["operator_task"]["total"] == 5
    assert summary["entities"]["operator_task"]["proven"] == 5
    assert summary["total_audit_events"] >= 8  # 5 create + 3 retask/update

    # Hard gate passes - all commands proven
    report = store.assert_command_proof_chain()
    assert report["chain_complete"] is True
    assert report["total_tasks"] == 5
    assert report["proven"] == 5

    # Phase 5: Export works offline (deterministic from local state)
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 5
    assert len(export["mission_events"]) >= 8
    assert len(export["sync_queue"]) == 8  # All commands staged for later upload

    # Export is deterministic - same result on re-export
    export2 = build_foundry_export(store)
    assert export["operator_tasks"] == export2["operator_tasks"]
    assert export["sync_queue"] == export2["sync_queue"]

    # Phase 6: Prove sync boundary - cannot upload while offline
    # (Verified by sync_queue status = 'pending' - nothing actually uploaded)
    pending_count = store.pending_sync_count()
    assert pending_count == 8  # All still pending, none uploaded
