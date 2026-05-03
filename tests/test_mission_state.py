from tac_fuse.foundry_export import build_foundry_export
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
