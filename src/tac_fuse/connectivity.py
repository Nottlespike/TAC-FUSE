"""Connectivity controller for online, degraded, and offline field modes."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from tac_fuse.mission_state import MissionStateStore


class ConnectivityMode(Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class ConnectivityController:
    """Persist connectivity state locally and gate external sync."""

    def __init__(self, mission_store: MissionStateStore) -> None:
        self._store = mission_store
        self._current_mode = ConnectivityMode.ONLINE
        self._callbacks: list[Callable[[ConnectivityMode], None]] = []
        self._ensure_state()

    def set_manual_override(self, mode: ConnectivityMode) -> None:
        old_mode = self._current_mode
        self._current_mode = mode
        self._store_mode(mode)
        if old_mode != mode:
            self._store._audit(
                "connectivity_mode_change",
                "demo_state",
                "connectivity_mode",
                f"Connectivity changed from {old_mode.value} to {mode.value}",
            )
            self._store.conn.commit()
        for callback in self._callbacks:
            callback(mode)

    def get_current_mode(self) -> ConnectivityMode:
        return self._current_mode

    def is_external_sync_allowed(self) -> bool:
        return self._current_mode is ConnectivityMode.ONLINE

    def add_mode_change_callback(self, callback: Callable[[ConnectivityMode], None]) -> None:
        self._callbacks.append(callback)

    def _ensure_state(self) -> None:
        self._store.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        row = self._store.conn.execute(
            "SELECT value FROM demo_state WHERE key = 'connectivity_mode'"
        ).fetchone()
        if row:
            self._current_mode = ConnectivityMode(row[0])
        else:
            self._store_mode(self._current_mode)
        self._store.conn.commit()

    def _store_mode(self, mode: ConnectivityMode) -> None:
        self._store.conn.execute(
            """
            INSERT OR REPLACE INTO demo_state (key, value, updated_at)
            VALUES ('connectivity_mode', ?, ?)
            """,
            (mode.value, self._store._utc_now()),
        )


def create_connectivity_controller(
    mission_store: MissionStateStore,
    *,
    operator: str = "demo_operator",
) -> ConnectivityController:
    del operator
    return ConnectivityController(mission_store)
