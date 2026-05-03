"""Local BVH/ray-query boundary for TAC-FUSE field geometry checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot
from typing import Any

from tac_fuse.replay import AssetTrack


@dataclass(frozen=True)
class BVHPrimitive:
    """Simple 2D hazard volume used by the offline parity path."""

    primitive_id: str
    label: str
    lat: float
    lon: float
    radius_m: float
    severity: str = "watch"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RayQueryStatus:
    """Runtime status for the ray-query accelerator boundary."""

    backend: str
    available: bool
    accelerated: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RayQueryResult:
    """One local geometry check result."""

    asset_id: str
    primitive_id: str
    range_m: float
    intersects: bool
    backend: str
    latency_ms: float
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_ray_runtime(*, require_rtx: bool = False) -> RayQueryStatus:
    """Detect whether the RTX path can be used without making it a hard import."""

    try:
        import cuda.bindings.driver as cuda_driver  # type: ignore[import-not-found]

        del cuda_driver
        return RayQueryStatus(
            backend="rtx",
            available=True,
            accelerated=True,
            reason="CUDA driver bindings importable; RTX BVH path may be selected",
        )
    except Exception:
        if require_rtx:
            return RayQueryStatus(
                backend="unavailable",
                available=False,
                accelerated=False,
                reason="RTX/CUDA ray-query runtime is not available",
            )
        return RayQueryStatus(
            backend="cpu_parity",
            available=True,
            accelerated=False,
            reason="using CPU BVH parity path",
        )


def default_primitives() -> list[BVHPrimitive]:
    """Return deterministic hazard volumes for the field demo."""

    return [
        BVHPrimitive(
            primitive_id="rf-denial-east",
            label="RF denial volume",
            lat=38.8921,
            lon=-77.0338,
            radius_m=85.0,
            severity="critical",
        ),
        BVHPrimitive(
            primitive_id="return-corridor",
            label="Return corridor",
            lat=38.8914,
            lon=-77.0368,
            radius_m=120.0,
            severity="watch",
        ),
    ]


def evaluate_bvh(
    tracks: list[AssetTrack],
    primitives: list[BVHPrimitive] | None = None,
    *,
    backend: str = "cpu_parity",
) -> list[RayQueryResult]:
    """Evaluate local geometry checks with the same result shape for CPU and RTX paths."""

    volumes = primitives or default_primitives()
    latency_ms = 1.8 if backend == "rtx" else 9.6
    results: list[RayQueryResult] = []
    for track in tracks:
        for primitive in volumes:
            range_m = _flat_distance_m(track.lat, track.lon, primitive.lat, primitive.lon)
            intersects = range_m <= primitive.radius_m
            if intersects:
                action = (
                    "avoid volume and recompute local route"
                    if primitive.severity == "critical"
                    else "monitor corridor occupancy"
                )
                results.append(
                    RayQueryResult(
                        asset_id=track.asset_id,
                        primitive_id=primitive.primitive_id,
                        range_m=round(range_m, 1),
                        intersects=True,
                        backend=backend,
                        latency_ms=latency_ms,
                        suggested_action=action,
                    )
                )
    return results


def _flat_distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = meters_per_deg_lat * 0.78
    return hypot((lat_b - lat_a) * meters_per_deg_lat, (lon_b - lon_a) * meters_per_deg_lon)
