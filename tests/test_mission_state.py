from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import SeededReplayEngine, generate_scenario


def test_task_create_update_enqueue_sync() -> None:
    store = MissionStateStore()

    task = store.create_task(title="Hold north corridor", description="Observe RF pocket")
    updated = store.update_task(task["id"], status="complete")

    assert updated["status"] == "complete"
    assert store.pending_sync_count() == 2
    assert [entry["operation"] for entry in store.list_sync_queue()] == ["create", "update"]


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
