"""Deterministic TAC-FUSE replay data for offline field demos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import cos, radians, sin
from random import Random
from typing import Any


@dataclass(frozen=True)
class AssetTrack:
    asset_id: str
    callsign: str
    asset_type: str
    timestamp_s: float
    lat: float
    lon: float
    altitude_m: float
    heading_deg: float
    speed_mps: float
    status: str = "nominal"
    battery_pct: int = 100
    confidence: float = 0.96
    is_stale: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def timestamp(self) -> float:
        return self.timestamp_s


@dataclass(frozen=True)
class RouteConflict:
    conflict_id: str
    asset_ids: tuple[str, str]
    range_m: float
    severity: str
    timestamp_s: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["asset_ids"] = list(self.asset_ids)
        return payload


def _offset_lat_lon(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = meters_per_deg_lat * cos(radians(lat))
    return lat + north_m / meters_per_deg_lat, lon + east_m / meters_per_deg_lon


def _track(
    asset_id: str,
    callsign: str,
    asset_type: str,
    timestamp_s: float,
    base_lat: float,
    base_lon: float,
    north_m: float,
    east_m: float,
    altitude_m: float,
    heading_deg: float,
    speed_mps: float,
    *,
    status: str = "nominal",
    battery_pct: int = 100,
    confidence: float = 0.96,
    is_stale: bool = False,
    metadata: dict[str, Any] | None = None,
) -> AssetTrack:
    lat, lon = _offset_lat_lon(base_lat, base_lon, north_m, east_m)
    return AssetTrack(
        asset_id=asset_id,
        callsign=callsign,
        asset_type=asset_type,
        timestamp_s=timestamp_s,
        lat=lat,
        lon=lon,
        altitude_m=altitude_m,
        heading_deg=heading_deg % 360,
        speed_mps=speed_mps,
        status=status,
        battery_pct=battery_pct,
        confidence=confidence,
        is_stale=is_stale,
        metadata=metadata or {},
    )


def generate_scenario(
    *,
    frames: int = 18,
    step_s: float = 2.5,
    seed: int = 42,
) -> list[list[AssetTrack]]:
    rng = Random(seed)
    base_lat = 38.8895
    base_lon = -77.0353
    scenario: list[list[AssetTrack]] = []
    for index in range(frames):
        t = round(index * step_s, 2)
        wave = sin(index / 3.0)
        stale = index >= max(5, frames // 2)
        scenario.append(
            [
                _track(
                    "uav-alpha",
                    "Alpha",
                    "quadrotor",
                    t,
                    base_lat,
                    base_lon,
                    index * 24.0,
                    index * 3.5,
                    122.0 + wave * 4.0,
                    18.0,
                    17.5,
                    battery_pct=max(62, 96 - index),
                    confidence=round(0.98 - index * 0.006, 3),
                    metadata={"role": "pov", "camera": "wide"},
                ),
                _track(
                    "uav-bravo",
                    "Bravo",
                    "fixed-wing",
                    t,
                    base_lat,
                    base_lon,
                    95.0 + index * 18.0,
                    -120.0 + wave * 30.0,
                    142.0,
                    42.0,
                    24.0,
                    battery_pct=max(55, 91 - index),
                    confidence=round(0.94 - index * 0.004, 3),
                    metadata={"role": "relay"},
                ),
                _track(
                    "uav-charlie",
                    "Charlie",
                    "quadrotor",
                    t,
                    base_lat,
                    base_lon,
                    180.0 + index * 12.0,
                    150.0 - index * 10.0,
                    98.0 + wave * 5.0,
                    315.0,
                    14.0,
                    status="tracking" if index >= frames // 3 else "nominal",
                    battery_pct=max(58, 88 - index),
                    confidence=round(0.91 - index * 0.008, 3),
                    is_stale=stale,
                    metadata={"role": "scout"},
                ),
                _track(
                    "uav-delta",
                    "Delta",
                    "quadrotor",
                    t,
                    base_lat,
                    base_lon,
                    55.0 + index * 9.5,
                    210.0 + wave * 16.0,
                    164.0 + rng.uniform(-2.0, 2.0),
                    282.0,
                    19.0,
                    status="overwatch",
                    battery_pct=max(60, 86 - index),
                    confidence=round(0.9 - index * 0.005, 3),
                    is_stale=index >= frames - 3,
                    metadata={"role": "overwatch"},
                ),
                _track(
                    "ground-team-1",
                    "Team 1",
                    "ground",
                    t,
                    base_lat,
                    base_lon,
                    310.0,
                    55.0 + index * 1.2,
                    2.0,
                    2.0,
                    1.4,
                    status="holding",
                    battery_pct=100,
                    confidence=0.99,
                    metadata={"role": "friendly"},
                ),
            ]
        )
    return scenario


def demo_conflicts(scenario: list[list[AssetTrack]] | None = None) -> list[RouteConflict]:
    frames = scenario or generate_scenario()
    pivot = frames[min(7, len(frames) - 1)]
    return [
        RouteConflict(
            conflict_id="conflict-alpha-charlie-001",
            asset_ids=("uav-alpha", "uav-charlie"),
            range_m=84.2,
            severity="watch",
            timestamp_s=pivot[0].timestamp_s,
        )
    ]


class SeededReplayEngine:
    def __init__(
        self,
        *,
        seed: int = 42,
        num_assets: int = 5,
        duration_sec: float = 45.0,
        tick_interval_sec: float = 2.5,
    ) -> None:
        self.seed = seed
        self.num_assets = num_assets
        self.duration_sec = duration_sec
        self.tick_interval_sec = tick_interval_sec
        self._scenario = generate_scenario(
            frames=max(1, int(duration_sec / tick_interval_sec)),
            step_s=tick_interval_sec,
            seed=seed,
        )
        self.route_conflicts = demo_conflicts(self._scenario)

    def generate(self) -> list[list[AssetTrack]]:
        return [frame[: self.num_assets] for frame in self._scenario]
