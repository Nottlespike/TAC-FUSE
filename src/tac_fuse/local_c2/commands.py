"""Local C2 command authority — the hardened-laptop command contract.

This module defines the six canonical operator commands (RESUME, PATROL, RETURN,
HOLD, ROUTE_SOLVE, ABORT) and the :class:`LocalC2Authority` that accepts them
in any connectivity mode.  Every accepted command produces a state-first proof
row in the underlying :class:`MissionStateStore` (state + audit + sync queue).

External sync is *never* required for local command acceptance.  The operator
copy is CAPITALIZED throughout.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from tac_fuse.connectivity import ConnectivityMode
from tac_fuse.mission_state import MissionStateStore

# ── Command enum ────────────────────────────────────────────────────────────


class C2Command(StrEnum):
    """The six canonical local-C2 operator commands.

    Each command maps to an operator-facing verb shown in CAPITALIZED copy.
    """

    RESUME = "resume"
    PATROL = "patrol"
    RETURN = "return"
    HOLD = "hold"
    ROUTE_SOLVE = "route_solve"
    ABORT = "abort"

    @property
    def display(self) -> str:
        """CAPITALIZED operator copy for the UI / demo."""
        return self.name.replace("_", " ")


class C2CommandStatus(StrEnum):
    """Lifecycle status of a locally-issued C2 command."""

    ACCEPTED = "accepted"
    ACKNOWLEDGED = "acknowledged"
    EXECUTING = "executing"
    COMPLETE = "complete"
    FAILED = "failed"


# ── Receipt ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class C2CommandReceipt:
    """Immutable receipt returned when the authority accepts a command.

    The receipt is the proof that local C2 accepted the operator's intent
    regardless of connectivity state.  It carries the task ID from the
    mission-state store so downstream consumers can correlate.
    """

    receipt_id: str
    command: str
    asset_id: str
    connectivity: str
    status: str
    task_id: str
    operator: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Known command set ───────────────────────────────────────────────────────

C2_COMMAND_OPS: frozenset[str] = frozenset(c.value for c in C2Command)
"""The accepted command set.  ``route_solve`` is included as a first-class
command for the route-guard scenario; other strings raise
:class:`UnknownCommandError`."""


# ── Exceptions ──────────────────────────────────────────────────────────────


class UnknownCommandError(ValueError):
    """Raised when the operator issues a command outside the accepted set."""


# ── Authority ───────────────────────────────────────────────────────────────


class LocalC2Authority:
    """Hardened-laptop local C2 authority.

    Owns the state contract for accepting operator commands while disconnected.
    Every call to :meth:`issue` writes a state-first proof row to the
    underlying :class:`MissionStateStore`, regardless of connectivity mode.

    Usage::

        store = MissionStateStore(operator="field_op_1")
        ctrl  = ConnectivityController(store)
        authority = LocalC2Authority(store, ctrl)

        # Works in OFFLINE, DEGRADED, and ONLINE
        receipt = authority.issue("patrol", asset_id="uav-alpha")
    """

    def __init__(
        self,
        store: MissionStateStore,
        connectivity: Any | None = None,
    ) -> None:
        self._store = store
        self._connectivity = connectivity

    # ── Public API ──────────────────────────────────────────────────────

    def issue(
        self,
        command: str,
        *,
        asset_id: str = "",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> C2CommandReceipt:
        """Accept and persist a local C2 command.

        Validates the command against the accepted set, then delegates to
        :meth:`MissionStateStore.dispatch_command` for state-first persistence.

        Args:
            command: One of the six canonical commands.
            asset_id: Target asset (drone, swarm, ground-team).
            description: Optional operator description.
            metadata: Optional metadata dict merged into the task.

        Returns:
            A :class:`C2CommandReceipt` proving local acceptance.

        Raises:
            UnknownCommandError: If *command* is not in the accepted set.
        """
        cmd_lower = command.strip().lower()
        if cmd_lower not in C2_COMMAND_OPS:
            raise UnknownCommandError(
                f"UNKNOWN COMMAND '{command}'. "
                f"ACCEPTED COMMANDS: {', '.join(sorted(C2_COMMAND_OPS)).upper()}."
            )

        meta = dict(metadata or {})
        meta["c2_authority"] = "local"
        meta["command"] = cmd_lower

        display = C2Command(cmd_lower).display
        title = f"{display} — {asset_id}" if asset_id else display

        task = self._store.dispatch_command(
            cmd_lower,
            asset_id=asset_id,
            title=title,
            description=description or f"OPERATOR ISSUED {display}",
            metadata=meta,
        )

        conn_mode = self._current_connectivity()

        return C2CommandReceipt(
            receipt_id=task["id"],
            command=cmd_lower,
            asset_id=asset_id,
            connectivity=conn_mode.value,
            status=C2CommandStatus.ACCEPTED.value,
            task_id=task["id"],
            operator=self._store.operator,
            timestamp=task["created_at"],
        )

    def history(self, *, asset_id: str | None = None) -> list[C2CommandReceipt]:
        """Return receipts for all locally-issued C2 commands.

        Optionally filtered by *asset_id*.
        """
        receipts: list[C2CommandReceipt] = []
        for task in self._store.list_tasks():
            meta = task.get("metadata") or {}
            if meta.get("c2_authority") != "local":
                continue
            if asset_id and meta.get("asset_id") != asset_id:
                continue
            receipts.append(
                C2CommandReceipt(
                    receipt_id=task["id"],
                    command=meta.get("command", ""),
                    asset_id=meta.get("asset_id", ""),
                    connectivity="",
                    status=task["status"],
                    task_id=task["id"],
                    operator=self._store.operator,
                    timestamp=task["created_at"],
                )
            )
        return receipts

    @property
    def store(self) -> MissionStateStore:
        """Access the underlying mission-state store for proof queries."""
        return self._store

    # ── Internals ───────────────────────────────────────────────────────

    def _current_connectivity(self) -> ConnectivityMode:
        if self._connectivity is not None and hasattr(
            self._connectivity, "get_current_mode"
        ):
            return self._connectivity.get_current_mode()
        return ConnectivityMode.OFFLINE


# ── Convenience helper ──────────────────────────────────────────────────────


def issue_c2_command(
    store: MissionStateStore,
    command: str,
    *,
    asset_id: str = "",
    connectivity: Any | None = None,
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> C2CommandReceipt:
    """One-shot helper: create an authority and issue a single command."""
    authority = LocalC2Authority(store, connectivity)
    return authority.issue(
        command,
        asset_id=asset_id,
        description=description,
        metadata=metadata,
    )
