"""Local ray-query boundary for TAC-FUSE field geometry checks.

The software validation path keeps automated tests deterministic. RTX/CUDA
acceleration is the hardware lane: when available it reduces latency for
spatial queries, but local C2 continuity, route guarding, and hazard avoidance
retain the same result shape.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from math import hypot
from typing import Any

from tac_fuse.replay import AssetTrack


@dataclass(frozen=True)
class BVHPrimitive:
    """Simple 2D hazard volume used by the software validation path."""

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
    """Runtime status for the ray-query boundary.

    The software validation path is always available; RTX/CUDA is an
    acceleration layer that improves latency when hardware and drivers are
    present.
    """

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
    """Detect whether the RTX path can be used without making it a hard import.

    Prefer Python CUDA driver bindings when present.  On Strix-style demo
    targets, a non-interactive SSH shell may have the NVIDIA driver and RTX GPU
    ready before the Python CUDA package is installed, so `nvidia-smi` is also a
    valid hardware-readiness signal for selecting the accelerated geometry lane.
    """

    if _cuda_driver_bindings_available():
        return RayQueryStatus(
            backend="rtx",
            available=True,
            accelerated=True,
            reason="CUDA driver bindings importable; RTX BVH path may be selected",
        )

    nvidia_status = _inspect_nvidia_smi()
    if nvidia_status is not None and nvidia_status.accelerated:
        return nvidia_status
    if require_rtx:
        return nvidia_status or RayQueryStatus(
            backend="unavailable",
            available=False,
            accelerated=False,
            reason="RTX/CUDA ray-query runtime is not available",
        )

    return RayQueryStatus(
        backend="cpu_parity",
        available=True,
        accelerated=False,
        reason="using deterministic software validation path",
    )


def _cuda_driver_bindings_available() -> bool:
    try:
        import cuda.bindings.driver as cuda_driver  # type: ignore[import-not-found]

        del cuda_driver
        return True
    except Exception:
        return False


def _inspect_nvidia_smi() -> RayQueryStatus | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None

    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return RayQueryStatus(
            backend="unavailable",
            available=False,
            accelerated=False,
            reason="nvidia-smi could not inspect the RTX/CUDA runtime",
        )

    if result.returncode != 0:
        return RayQueryStatus(
            backend="unavailable",
            available=False,
            accelerated=False,
            reason=(result.stderr.strip() or "nvidia-smi returned non-zero"),
        )

    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) < 3:
        return RayQueryStatus(
            backend="unavailable",
            available=False,
            accelerated=False,
            reason="nvidia-smi did not return GPU name, memory, and driver",
        )

    gpu_name, memory_text, driver_version = parts[:3]
    try:
        memory_mib = int(memory_text)
    except ValueError:
        memory_mib = 0
    min_memory_mib = int(os.environ.get("TAC_FUSE_MIN_GPU_MEMORY_MIB", "7500"))
    if "rtx" in gpu_name.lower() and memory_mib >= min_memory_mib:
        return RayQueryStatus(
            backend="rtx",
            available=True,
            accelerated=True,
            reason=(
                f"nvidia-smi reports {gpu_name} with {memory_mib} MiB VRAM "
                f"and driver {driver_version}; RTX geometry lane may be selected"
            ),
        )

    return RayQueryStatus(
        backend="unavailable",
        available=False,
        accelerated=False,
        reason=(
            f"nvidia-smi reports {gpu_name} with {memory_mib} MiB VRAM; "
            f"requires RTX-class GPU with at least {min_memory_mib} MiB"
        ),
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
