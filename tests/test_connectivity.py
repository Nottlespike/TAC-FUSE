from tac_fuse.connectivity import ConnectivityMode, create_connectivity_controller
from tac_fuse.foundry.config import (
    FoundryConnectionConfig,
    MavenFoundryConfig,
    can_upload,
    has_upload_credentials,
)
from tac_fuse.foundry_export import build_foundry_export
from tac_fuse.mission_state import MissionStateStore


def test_connectivity_controller_persists_manual_override() -> None:
    store = MissionStateStore()
    controller = create_connectivity_controller(store)

    controller.set_manual_override(ConnectivityMode.OFFLINE)

    assert controller.get_current_mode() is ConnectivityMode.OFFLINE
    assert not controller.is_external_sync_allowed()
    row = store.conn.execute(
        "SELECT value FROM demo_state WHERE key = 'connectivity_mode'"
    ).fetchone()
    assert row[0] == "offline"


def test_degraded_mode_blocks_external_sync() -> None:
    store = MissionStateStore()
    controller = create_connectivity_controller(store)

    controller.set_manual_override(ConnectivityMode.DEGRADED)

    assert not controller.is_external_sync_allowed()


def test_enterprise_sync_boundary_gated_by_connectivity() -> None:
    """Prove exports work offline but external sync requires ONLINE mode.

    This test verifies the deferred sync boundary:
    - Local exports can be created in any connectivity mode
    - External sync (upload) must be gated by ONLINE mode
    - DEGRADED and OFFLINE modes block external sync
    """
    store = MissionStateStore()
    controller = create_connectivity_controller(store)

    # Create task while OFFLINE - local C2 still works
    controller.set_manual_override(ConnectivityMode.OFFLINE)
    store.create_task(title="Offline patrol", description="Local C2 active")

    # Export works offline - reads from local state
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 1
    assert export["operator_tasks"][0]["title"] == "Offline patrol"

    # External sync blocked in OFFLINE mode
    assert not controller.is_external_sync_allowed()

    # External sync blocked in DEGRADED mode
    controller.set_manual_override(ConnectivityMode.DEGRADED)
    assert not controller.is_external_sync_allowed()

    # External sync allowed only in ONLINE mode
    controller.set_manual_override(ConnectivityMode.ONLINE)
    assert controller.is_external_sync_allowed()


def test_audit_log_records_all_operator_commands() -> None:
    """Prove every operator command is audited before export."""
    store = MissionStateStore(operator="audit_test_operator")
    controller = create_connectivity_controller(store)

    # Stay offline to prove local C2 authority
    controller.set_manual_override(ConnectivityMode.OFFLINE)

    # Issue multiple commands
    task1 = store.create_task(title="Patrol corridor A")
    store.update_task(task1["id"], status="in_progress")
    store.create_alert("RF denial detected", severity="critical")

    # All commands audited
    audit_events = store.list_audit_events()
    event_types = [e["event_type"] for e in audit_events]

    assert "task_created" in event_types
    assert "task_updated" in event_types
    assert "alert_created" in event_types

    # All events have operator attribution
    for event in audit_events:
        assert event["operator"] == "audit_test_operator"
        assert "created_at" in event


def _make_foundry_config() -> MavenFoundryConfig:
    """Build a fake Foundry config with valid upload credentials."""
    return MavenFoundryConfig(
        connection=FoundryConnectionConfig(hostname="https://h", token="pat-fake"),
        ontology_name="maven",
        mission_dataset_rid="ri-ds-1",
        events_dataset_rid="ri-ds-2",
        media_set_rid="ri-ms-1",
    )


def test_can_upload_combines_connectivity_and_credentials() -> None:
    """Prove can_upload requires both ONLINE mode AND valid credentials."""
    store = MissionStateStore()
    controller = create_connectivity_controller(store)
    cfg = _make_foundry_config()

    # ONLINE + valid credentials => upload allowed
    controller.set_manual_override(ConnectivityMode.ONLINE)
    assert can_upload(cfg, sync_allowed=controller.is_external_sync_allowed()) is True

    # OFFLINE + valid credentials => upload blocked
    controller.set_manual_override(ConnectivityMode.OFFLINE)
    assert can_upload(cfg, sync_allowed=controller.is_external_sync_allowed()) is False

    # DEGRADED + valid credentials => upload blocked
    controller.set_manual_override(ConnectivityMode.DEGRADED)
    assert can_upload(cfg, sync_allowed=controller.is_external_sync_allowed()) is False

    # ONLINE + no config => upload blocked
    controller.set_manual_override(ConnectivityMode.ONLINE)
    assert can_upload(None, sync_allowed=controller.is_external_sync_allowed()) is False


def test_missing_foundry_config_never_blocks_local_c2() -> None:
    """Prove local C2 and exports work perfectly with zero Foundry config."""
    store = MissionStateStore()
    controller = create_connectivity_controller(store)

    # Stay offline, no Foundry config at all
    controller.set_manual_override(ConnectivityMode.OFFLINE)
    assert has_upload_credentials(None) is False
    assert can_upload(None, sync_allowed=controller.is_external_sync_allowed()) is False

    # Local C2 still fully operational
    task = store.create_task(title="Air-gapped recon", description="No Foundry needed")
    store.update_task(task["id"], status="in_progress")
    store.create_alert("No comms since 04:00Z", severity="warning")

    # Export works from local state only
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 1
    assert export["operator_tasks"][0]["title"] == "Air-gapped recon"
    assert len(export["alerts"]) == 1

    # Audit log proves local authority
    audit = store.list_audit_events()
    event_types = [e["event_type"] for e in audit]
    assert "task_created" in event_types
    assert "alert_created" in event_types
