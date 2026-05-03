from tac_fuse.connectivity import ConnectivityMode, create_connectivity_controller
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
