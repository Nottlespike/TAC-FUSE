"""RT-geometry control boundary for TAC-FUSE local swarm tasking.

The ray-query module answers spatial questions.  This module turns those
answers into canonical Local C2 commands for Alpha/Bravo/Charlie/Delta style
assets.  Hardware acceleration is selected when the CUDA/RT geometry lane is
available; deterministic software validation keeps the same command shape for
offline tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from tac_fuse.local_c2.commands import C2_COMMAND_OPS, C2CommandReceipt, LocalC2Authority
from tac_fuse.ray_query import (
    BVHPrimitive,
    RayQueryResult,
    RayQueryStatus,
    default_primitives,
    evaluate_bvh,
    inspect_ray_runtime,
)
from tac_fuse.replay import AssetTrack


class RTControlUnavailable(RuntimeError):
    """Raised when a caller explicitly requires accelerated geometry."""


@dataclass(frozen=True, slots=True)
class RTControlDecision:
    """One geometry-derived local C2 decision for an asset."""

    asset_id: str
    callsign: str
    command: str
    priority: str
    reason: str
    backend: str
    accelerated: bool
    source: str = "rt_geometry_control"
    primitive_id: str | None = None
    primitive_label: str | None = None
    range_m: float | None = None
    standoff_m: float | None = None
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.command not in C2_COMMAND_OPS:
            raise ValueError(f"RT control produced unsupported C2 command: {self.command}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_command_metadata(self) -> dict[str, Any]:
        """Return metadata suitable for LocalC2Authority.issue()."""

        return {
            "control_source": self.source,
            "priority": self.priority,
            "reason": self.reason,
            "geometry_backend": self.backend,
            "accelerated": self.accelerated,
            "primitive_id": self.primitive_id,
            "primitive_label": self.primitive_label,
            "range_m": self.range_m,
            "standoff_m": self.standoff_m,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True, slots=True)
class RTControlPlan:
    """Geometry-control output for a full swarm frame."""

    backend: str
    accelerated: bool
    reason: str
    decisions: tuple[RTControlDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "accelerated": self.accelerated,
            "reason": self.reason,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }

    def commands_by_asset(self) -> dict[str, str]:
        return {decision.asset_id: decision.command for decision in self.decisions}


def plan_rt_control(
    tracks: Sequence[AssetTrack],
    primitives: Sequence[BVHPrimitive] | None = None,
    *,
    runtime_status: RayQueryStatus | None = None,
    require_accelerated: bool = False,
) -> RTControlPlan:
    """Plan local C2 commands from RT geometry.

    Args:
        tracks: Current asset tracks to control.
        primitives: Hazard or corridor volumes visible to the operator.
        runtime_status: Optional injected runtime status for tests or hardware probes.
        require_accelerated: If true, fail when the accelerated lane is not available.

    Returns:
        RTControlPlan with one canonical command per input track.
    """

    status = runtime_status or inspect_ray_runtime(require_rtx=require_accelerated)
    backend = _select_backend(status, require_accelerated=require_accelerated)
    volumes = list(primitives or default_primitives())
    hits = evaluate_bvh(list(tracks), volumes, backend=backend)
    hits_by_asset = _group_hits(hits)
    primitives_by_id = {primitive.primitive_id: primitive for primitive in volumes}

    decisions = tuple(
        _decision_for_track(
            track,
            hits_by_asset.get(track.asset_id, ()),
            primitives_by_id,
            backend=backend,
            accelerated=status.accelerated,
        )
        for track in tracks
    )
    return RTControlPlan(
        backend=backend,
        accelerated=status.accelerated,
        reason=status.reason,
        decisions=decisions,
    )


def issue_rt_control_plan(
    authority: LocalC2Authority,
    plan: RTControlPlan,
    *,
    include_resume: bool = False,
) -> list[C2CommandReceipt]:
    """Persist non-normal geometry decisions through the local C2 authority.

    Normal RESUME decisions are usually telemetry.  Callers may set
    ``include_resume=True`` when they need a full proof chain for every asset in
    a demo frame.
    """

    receipts: list[C2CommandReceipt] = []
    for decision in plan.decisions:
        if decision.priority == "normal" and not include_resume:
            continue
        receipts.append(
            authority.issue(
                decision.command,
                asset_id=decision.asset_id,
                description=decision.reason,
                metadata=decision.to_command_metadata(),
            )
        )
    return receipts


def _select_backend(status: RayQueryStatus, *, require_accelerated: bool) -> str:
    if status.accelerated:
        return "rtx"
    if require_accelerated:
        raise RTControlUnavailable(status.reason)
    return "cpu_parity"


def _group_hits(results: Iterable[RayQueryResult]) -> dict[str, tuple[RayQueryResult, ...]]:
    grouped: dict[str, list[RayQueryResult]] = {}
    for result in results:
        grouped.setdefault(result.asset_id, []).append(result)
    return {
        asset_id: tuple(sorted(items, key=lambda item: item.range_m))
        for asset_id, items in grouped.items()
    }


def _decision_for_track(
    track: AssetTrack,
    hits: Sequence[RayQueryResult],
    primitives_by_id: dict[str, BVHPrimitive],
    *,
    backend: str,
    accelerated: bool,
) -> RTControlDecision:
    if track.battery_pct <= 40:
        return RTControlDecision(
            asset_id=track.asset_id,
            callsign=track.callsign,
            command="return",
            priority="watch",
            reason=(
                f"{track.callsign} returns on battery reserve while keeping "
                "corridor state local."
            ),
            backend=backend,
            accelerated=accelerated,
        )

    ranked_hits = sorted(
        hits,
        key=lambda item: (
            0 if _primitive_severity(item, primitives_by_id) == "critical" else 1,
            item.range_m,
        ),
    )
    if ranked_hits:
        hit = ranked_hits[0]
        primitive = primitives_by_id[hit.primitive_id]
        priority = "critical" if primitive.severity == "critical" else "watch"
        command = "hold" if priority == "critical" else "patrol"
        verb = "holds clear of" if command == "hold" else "patrols around"
        standoff_m = max(0.0, primitive.radius_m - hit.range_m)
        return RTControlDecision(
            asset_id=track.asset_id,
            callsign=track.callsign,
            command=command,
            priority=priority,
            reason=(
                f"{track.callsign} {verb} {primitive.label}; "
                f"{backend_label(backend)} geometry reported {hit.range_m:.1f} m range."
            ),
            backend=backend,
            accelerated=accelerated,
            primitive_id=primitive.primitive_id,
            primitive_label=primitive.label,
            range_m=hit.range_m,
            standoff_m=round(standoff_m, 1),
            latency_ms=hit.latency_ms,
        )

    return RTControlDecision(
        asset_id=track.asset_id,
        callsign=track.callsign,
        command="resume",
        priority="normal",
        reason=f"{track.callsign} resumes route guard; no active geometry conflict.",
        backend=backend,
        accelerated=accelerated,
    )


def _primitive_severity(
    result: RayQueryResult,
    primitives_by_id: dict[str, BVHPrimitive],
) -> str:
    primitive = primitives_by_id.get(result.primitive_id)
    return primitive.severity if primitive is not None else "watch"


def backend_label(backend: str) -> str:
    """Operator-safe label for the geometry backend."""

    return "Accelerated" if backend == "rtx" else "Validation"
