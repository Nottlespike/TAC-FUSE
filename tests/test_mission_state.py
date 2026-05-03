from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import generate_scenario


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
