"""Sync gate — external sync is gated behind ONLINE connectivity.

In OFFLINE and DEGRADED modes, commands are accepted locally and queued for
deferred sync.  The sync gate provides utilities to:
- Check whether sync is currently allowed
- Prepare the sync payload from the pending queue
- Flush the queue (mark items as synced) — only when ONLINE

External sync is *never* required for local command acceptance or replay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from tac_fuse.connectivity import ConnectivityController, ConnectivityMode
from tac_fuse.mission_state import MissionStateStore


class SyncGateStatus(StrEnum):
    """Status of the sync gate."""

    OPEN = "open"
    BLOCKED_OFFLINE = "blocked_offline"
    BLOCKED_DEGRADED = "blocked_degraded"
    BLOCKED_NO_CREDENTIALS = "blocked_no_credentials"


@dataclass(frozen=True)
class SyncGate:
    """Immutable snapshot of the sync gate state."""

    status: str
    connectivity_mode: str
    pending_count: int
    is_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_sync_gate(
    store: MissionStateStore,
    connectivity: ConnectivityController | None = None,
) -> SyncGate:
    """Evaluate the current sync gate state.

    Returns a :class:`SyncGate` snapshot with the gate status, pending count,
    and whether sync is currently allowed.
    """
    if connectivity is None:
        mode = ConnectivityMode.OFFLINE
    else:
        mode = connectivity.get_current_mode()

    pending = store.pending_sync_count()
    is_allowed = mode is ConnectivityMode.ONLINE

    if is_allowed:
        status = SyncGateStatus.OPEN
    elif mode is ConnectivityMode.DEGRADED:
        status = SyncGateStatus.BLOCKED_DEGRADED
    else:
        status = SyncGateStatus.BLOCKED_OFFLINE

    return SyncGate(
        status=status.value,
        connectivity_mode=mode.value,
        pending_count=pending,
        is_allowed=is_allowed,
    )


def prepare_sync_payload(store: MissionStateStore) -> dict[str, Any]:
    """Build the sync payload from all pending sync-queue items.

    This is a staging operation — it does not flush the queue.  The payload
    can be held for later upload when connectivity is restored.
    """
    pending_items = [
        item for item in store.list_sync_queue() if item["status"] == "pending"
    ]
    return {
        "pending_count": len(pending_items),
        "items": pending_items,
        "operator": store.operator,
        "timestamp": store._utc_now(),
    }


def flush_sync_queue(
    store: MissionStateStore,
    connectivity: ConnectivityController | None = None,
) -> dict[str, Any]:
    """Attempt to flush the sync queue — only succeeds when ONLINE.

    In OFFLINE/DEGRADED mode, returns a report without modifying the queue.
    When ONLINE, marks all pending items as ``synced``.
    """
    gate = check_sync_gate(store, connectivity)

    if not gate.is_allowed:
        return {
            "flushed": False,
            "reason": gate.status,
            "pending_count": gate.pending_count,
            "message": (
                f"SYNC BLOCKED: {gate.status.upper()}. "
                f"{gate.pending_count} ITEM(S) HELD FOR DEFERRED SYNC."
            ),
        }

    # Mark all pending items as synced
    with store.conn:
        cursor = store.conn.execute(
            "UPDATE sync_queue SET status = 'synced' WHERE status = 'pending'"
        )
        flushed = cursor.rowcount

    return {
        "flushed": True,
        "items_flushed": flushed,
        "message": (
            f"SYNC COMPLETE: {flushed} ITEM(S) FLUSHED TO ENTERPRISE."
        ),
    }
