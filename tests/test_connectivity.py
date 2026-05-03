import pytest

from tac_fuse.connectivity import ConnectivityMode, create_connectivity_controller
from tac_fuse.foundry.config import (
    FoundryConnectionConfig,
    MavenFoundryConfig,
    SyncBoundaryViolation,
    assert_sync_allowed,
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


def test_power_posture_classifies_export_as_safe_offline() -> None:
    """Prove foundry_export is classified as SAFE_OFFLINE in power posture.

    This is critical: exports must be available in any connectivity mode
    because they read from local persisted state. Only enterprise_sync
    (actual upload) requires ONLINE connectivity.
    """
    from tac_fuse.power_posture import WORKLOAD_REGISTRY, WorkloadClass

    # foundry_export must be SAFE_OFFLINE
    assert WORKLOAD_REGISTRY.get("foundry_export") == WorkloadClass.SAFE_OFFLINE

    # enterprise_sync requires ONLINE
    assert WORKLOAD_REGISTRY.get("enterprise_sync") == WorkloadClass.REQUIRES_ONLINE

    # Verify all core C2 workloads are SAFE_OFFLINE
    for workload in ["local_c2", "sensor_fusion", "alerting", "fusion_spool", "drone_tasking"]:
        assert WORKLOAD_REGISTRY.get(workload) == WorkloadClass.SAFE_OFFLINE


def test_upload_requires_both_online_mode_and_credentials() -> None:
    """Prove the unified upload gate requires both conditions.

    This is the critical sync boundary: uploads must be blocked when:
    - Connectivity is OFFLINE or DEGRADED (even with valid credentials)
    - Credentials are missing (even in ONLINE mode)
    """
    from tac_fuse.foundry.config import FoundryConnectionConfig, MavenFoundryConfig

    # Build valid config with credentials
    cfg = MavenFoundryConfig(
        connection=FoundryConnectionConfig(hostname="https://h", token="pat-valid"),
        ontology_name="maven",
        mission_dataset_rid="ri-ds-1",
        events_dataset_rid="ri-ds-2",
        media_set_rid="ri-ms-1",
    )

    # ONLINE + credentials = allowed
    assert can_upload(cfg, sync_allowed=True) is True

    # OFFLINE + credentials = blocked
    assert can_upload(cfg, sync_allowed=False) is False

    # DEGRADED + credentials = blocked
    assert can_upload(cfg, sync_allowed=False) is False

    # ONLINE + no config = blocked
    assert can_upload(None, sync_allowed=True) is False

    # OFFLINE + no config = blocked
    assert can_upload(None, sync_allowed=False) is False

    # Config without credentials = blocked
    no_auth_cfg = MavenFoundryConfig(
        connection=FoundryConnectionConfig(hostname="https://h", token=""),
        ontology_name="maven",
        mission_dataset_rid="ri-ds-1",
        events_dataset_rid="ri-ds-2",
        media_set_rid="ri-ms-1",
    )
    assert can_upload(no_auth_cfg, sync_allowed=True) is False


# ── assert_sync_allowed hard gate tests ──────────────────────────────────────


def test_assert_sync_allowed_passes_when_online_with_credentials() -> None:
    """Hard gate passes silently when both ONLINE and credentials present."""
    cfg = _make_foundry_config()
    # Should not raise
    assert_sync_allowed(cfg, sync_allowed=True)


def test_assert_sync_allowed_raises_offline() -> None:
    """Hard gate raises SyncBoundaryViolation in OFFLINE mode."""
    cfg = _make_foundry_config()
    try:
        assert_sync_allowed(cfg, sync_allowed=False)
        raise AssertionError("Expected SyncBoundaryViolation")
    except SyncBoundaryViolation as exc:
        assert "not ONLINE" in str(exc)
        assert "Exports" in str(exc)


def test_assert_sync_allowed_raises_degraded() -> None:
    """Hard gate raises SyncBoundaryViolation in DEGRADED mode."""
    cfg = _make_foundry_config()
    try:
        assert_sync_allowed(cfg, sync_allowed=False)
        raise AssertionError("Expected SyncBoundaryViolation")
    except SyncBoundaryViolation as exc:
        assert "not ONLINE" in str(exc)


def test_assert_sync_allowed_raises_no_config() -> None:
    """Hard gate raises SyncBoundaryViolation when no Foundry config exists."""
    try:
        assert_sync_allowed(None, sync_allowed=True)
        raise AssertionError("Expected SyncBoundaryViolation")
    except SyncBoundaryViolation as exc:
        assert "no Maven/Foundry configuration" in str(exc)
        assert "local operator C2" in str(exc)


def test_assert_sync_allowed_raises_empty_hostname() -> None:
    """Hard gate raises SyncBoundaryViolation when hostname is empty."""
    cfg = MavenFoundryConfig(
        connection=FoundryConnectionConfig(hostname="", token="pat-fake"),
        ontology_name="maven",
        mission_dataset_rid="ri-ds-1",
        events_dataset_rid="ri-ds-2",
        media_set_rid="ri-ms-1",
    )
    try:
        assert_sync_allowed(cfg, sync_allowed=True)
        raise AssertionError("Expected SyncBoundaryViolation")
    except SyncBoundaryViolation as exc:
        assert "hostname" in str(exc)


def test_assert_sync_allowed_raises_no_credentials() -> None:
    """Hard gate raises SyncBoundaryViolation when credentials are missing."""
    cfg = MavenFoundryConfig(
        connection=FoundryConnectionConfig(hostname="https://h", token=""),
        ontology_name="maven",
        mission_dataset_rid="ri-ds-1",
        events_dataset_rid="ri-ds-2",
        media_set_rid="ri-ms-1",
    )
    try:
        assert_sync_allowed(cfg, sync_allowed=True)
        raise AssertionError("Expected SyncBoundaryViolation")
    except SyncBoundaryViolation as exc:
        assert "credentials" in str(exc)


def test_assert_sync_allowed_offline_precedence_over_no_config() -> None:
    """When both offline and no config, offline reason takes precedence."""
    try:
        assert_sync_allowed(None, sync_allowed=False)
        raise AssertionError("Expected SyncBoundaryViolation")
    except SyncBoundaryViolation as exc:
        assert "not ONLINE" in str(exc)


def test_export_always_works_regardless_of_sync_boundary() -> None:
    """Exports are never blocked by the sync boundary — they read local state."""
    store = MissionStateStore()
    controller = create_connectivity_controller(store)

    # OFFLINE with no Foundry config — sync boundary is closed
    controller.set_manual_override(ConnectivityMode.OFFLINE)
    with pytest.raises(SyncBoundaryViolation):
        assert_sync_allowed(None, sync_allowed=controller.is_external_sync_allowed())

    # But export works fine — reads from local state, no network needed
    store.create_task(title="Air-gapped export test")
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 1
    assert export["operator_tasks"][0]["title"] == "Air-gapped export test"

    # DEGRADED too — sync blocked but export works
    controller.set_manual_override(ConnectivityMode.DEGRADED)
    with pytest.raises(SyncBoundaryViolation):
        assert_sync_allowed(None, sync_allowed=controller.is_external_sync_allowed())
    store.create_task(title="Degraded export test")
    export = build_foundry_export(store)
    assert len(export["operator_tasks"]) == 2


def test_sync_boundary_violation_is_runtime_error() -> None:
    """SyncBoundaryViolation is a RuntimeError so it's not caught by accident."""
    assert issubclass(SyncBoundaryViolation, RuntimeError)
