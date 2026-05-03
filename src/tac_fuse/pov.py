"""Drone point-of-view projection helpers for TAC-FUSE."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import atan2, cos, radians, sin, sqrt
from typing import Any

from tac_fuse.replay import AssetTrack

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class POVObject:
    asset_id: str
    callsign: str
    asset_type: str
    range_m: float
    bearing_deg: float
    relative_altitude_m: float
    x: float
    y: float
    apparent_size: float
    threat_level: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DronePOVFrame:
    ownship: AssetTrack
    timestamp_s: float
    field_condition: str
    confidence: float
    horizon_y: float
    objects: list[POVObject] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownship": self.ownship.to_dict(),
            "timestamp_s": self.timestamp_s,
            "field_condition": self.field_condition,
            "confidence": self.confidence,
            "horizon_y": self.horizon_y,
            "objects": [obj.to_dict() for obj in self.objects],
        }


def _haversine_distance_m(a: AssetTrack, b: AssetTrack) -> float:
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    dlat = lat2 - lat1
    dlon = radians(b.lon - a.lon)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * atan2(sqrt(h), sqrt(max(0.0, 1.0 - h)))


def _bearing_deg(a: AssetTrack, b: AssetTrack) -> float:
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    dlon = radians(b.lon - a.lon)
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    return (atan2(y, x) * 180.0 / 3.141592653589793 + 360.0) % 360.0


def _angle_delta_deg(a: float, b: float) -> float:
    return (a - b + 540.0) % 360.0 - 180.0


def infer_field_condition(ownship: AssetTrack, objects: list[POVObject]) -> tuple[str, float]:
    if any(obj.threat_level == "critical" for obj in objects):
        return "drone near restricted area", 0.88
    if ownship.battery_pct < 70:
        return "low power return corridor", 0.81
    if len(objects) >= 3:
        return "dense multi asset formation", 0.79
    return "clear corridor", 0.86


def project_tracks_to_pov(
    tracks: list[AssetTrack],
    *,
    ownship_id: str = "uav-alpha",
    fov_deg: float = 120.0,
    max_range_m: float = 650.0,
) -> DronePOVFrame:
    ownship = next((track for track in tracks if track.asset_id == ownship_id), None)
    if ownship is None:
        raise ValueError(f"ownship {ownship_id!r} not found in tracks")

    objects: list[POVObject] = []
    for track in tracks:
        if track.asset_id == ownship.asset_id:
            continue
        range_m = _haversine_distance_m(ownship, track)
        if range_m > max_range_m:
            continue
        bearing = _bearing_deg(ownship, track)
        relative_bearing = _angle_delta_deg(bearing, ownship.heading_deg)
        if abs(relative_bearing) > fov_deg / 2:
            continue

        rel_alt = track.altitude_m - ownship.altitude_m
        x = 0.5 + relative_bearing / fov_deg
        y = 0.48 - rel_alt / 260.0 + min(range_m, max_range_m) / max_range_m * 0.22
        threat_level = "critical" if track.status in {"tracking", "conflict"} else "watch"
        objects.append(
            POVObject(
                asset_id=track.asset_id,
                callsign=track.callsign,
                asset_type=track.asset_type,
                range_m=round(range_m, 1),
                bearing_deg=round(relative_bearing, 1),
                relative_altitude_m=round(rel_alt, 1),
                x=round(min(0.95, max(0.05, x)), 4),
                y=round(min(0.9, max(0.12, y)), 4),
                apparent_size=round(max(0.035, min(0.18, 70.0 / max(range_m, 45.0))), 4),
                threat_level=threat_level,
                label=f"{track.callsign} {int(range_m)}m",
            )
        )

    objects.sort(key=lambda obj: obj.range_m)
    field_condition, confidence = infer_field_condition(ownship, objects)
    return DronePOVFrame(
        ownship=ownship,
        timestamp_s=ownship.timestamp_s,
        field_condition=field_condition,
        confidence=confidence,
        horizon_y=0.42,
        objects=objects,
    )


def generate_pov_sequence(
    scenario: list[list[AssetTrack]],
    *,
    ownship_id: str = "uav-alpha",
) -> list[DronePOVFrame]:
    return [project_tracks_to_pov(frame, ownship_id=ownship_id) for frame in scenario]


def render_svg_pov(frame: DronePOVFrame, *, width: int = 960, height: int = 540) -> str:
    horizon = int(frame.horizon_y * height)
    objects: list[str] = []
    for obj in frame.objects:
        cx = int(obj.x * width)
        cy = int(obj.y * height)
        radius = max(8, int(obj.apparent_size * width * 0.45))
        color = "#ff4d4d" if obj.threat_level == "critical" else "#55d6a6"
        objects.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{color}" '
            f'stroke="#f8f5ec" stroke-width="2" />'
        )
        objects.append(
            f'<text x="{cx + radius + 8}" y="{cy + 4}" fill="#f8f5ec" '
            f'font-size="16" font-family="Inter, Arial">{obj.label}</text>'
        )
    object_markup = "\n".join(objects)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">
  <rect width="{width}" height="{height}" fill="#111721"/>
  <rect y="{horizon}" width="{width}" height="{height - horizon}" fill="#293222"/>
  <line x1="0" y1="{horizon}" x2="{width}" y2="{horizon}" stroke="#e6cf88" stroke-width="2"/>
  <text x="24" y="38" fill="#f8f5ec" font-size="20" font-family="Inter, Arial">
    {frame.ownship.callsign} POV - {frame.field_condition}
  </text>
  {object_markup}
</svg>"""
