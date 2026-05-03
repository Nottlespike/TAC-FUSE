"""Local alerting engine for TAC-FUSE.

This module converts sensor observations, fusion events, and geometry checks
into prioritized operator alerts without requiring cloud infrastructure.

Alert triggers (all offline-testable):
- Video/RF cue: object detection or signal anomaly from sensor stream
- Position breach: asset enters restricted zone (auto from GNSS events)
- Route conflict: two assets on collision course (auto from tracked positions)
- Stale feed: sensor/telemetry gap exceeds threshold
- Battery low: asset battery below threshold
- Confidence drop: track quality falls below usable threshold

The alerting engine is purely local and does not require:
- Foundry/Maven connectivity
- Intel NPU or object detection models
- Internet access or Hugging Face downloads

Alert deduplication:
- Each (asset_id, alert_type) pair is tracked with a cooldown window.
- Duplicate alerts for the same condition are suppressed until the
  cooldown expires, preventing alert storms from repeated events.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from tac_fuse.fusion_node.ingest import SensorEvent


class AlertSeverity(Enum):
    """Priority levels for operator alerts."""

    CRITICAL = "critical"  # Immediate action required
    HIGH = "high"  # Action needed within seconds
    MEDIUM = "medium"  # Awareness needed
    LOW = "low"  # Informational


class AlertType(Enum):
    """Canonical alert types for local C2."""

    VIDEO_CUE = "video_cue"  # Object detection from video
    RF_CUE = "rf_cue"  # RF anomaly or signal detection
    POSITION_BREACH = "position_breach"  # Entered restricted zone
    ROUTE_CONFLICT = "route_conflict"  # Collision risk
    STALE_FEED = "stale_feed"  # Sensor/telemetry gap
    BATTERY_LOW = "battery_low"  # Low battery warning
    CONFIDENCE_DROP = "confidence_drop"  # Track quality degraded
    SENSOR_DEGRADED = "sensor_degraded"  # Environmental degradation
    DROPPED_FRAME = "dropped_frame"  # Frame loss detected


@dataclass(frozen=True)
class OperatorAlert:
    """Prioritized alert for operator attention.

    Alerts are created from sensor events, geometry checks, or system state.
    Each alert has a severity, type, and payload with context for decision-making.
    """

    alert_id: str
    alert_type: str
    severity: str
    message: str
    asset_id: str | None
    sensor_id: str | None
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_alert_payload(self) -> dict[str, Any]:
        """Convert to payload suitable for MissionStateStore.create_alert()."""
        return {
            "alert_id": self.alert_id,
            "alert_type": self.alert_type,
            "asset_id": self.asset_id,
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp,
            **self.payload,
        }


@dataclass
class _AssetPosition:
    """Tracked asset position for auto geometry checks."""

    asset_id: str
    lat: float
    lon: float
    heading: float = 0.0
    speed: float = 0.0
    timestamp: float = 0.0


class AlertingEngine:
    """Local alerting engine for sensor/fusion events.

    This engine processes SensorEvent objects and geometry state to produce
    prioritized OperatorAlert objects. It is entirely offline and does not
    require external services.

    Configuration thresholds:
    - stale_threshold_s: Max age before stale-feed alert (default 5.0s)
    - battery_low_threshold: Battery % for low-battery alert (default 20)
    - confidence_drop_threshold: Min confidence before alert (default 0.5)
    - restricted_zones: Set of zone IDs to monitor for breaches
    """

    def __init__(
        self,
        *,
        stale_threshold_s: float = 5.0,
        battery_low_threshold: float = 20.0,
        confidence_drop_threshold: float = 0.5,
        restricted_zones: set[str] | None = None,
        dedup_cooldown_s: float = 10.0,
        route_conflict_range_m: float = 50.0,
    ) -> None:
        self.stale_threshold_s = stale_threshold_s
        self.battery_low_threshold = battery_low_threshold
        self.confidence_drop_threshold = confidence_drop_threshold
        self.restricted_zones = restricted_zones or set()
        self.dedup_cooldown_s = dedup_cooldown_s
        self.route_conflict_range_m = route_conflict_range_m
        self._alerts: list[OperatorAlert] = []
        self._last_seen: dict[str, float] = {}  # asset_id -> last timestamp
        # Dedup: (dedup_key) -> last alert timestamp (epoch seconds)
        self._dedup_window: dict[str, float] = {}
        # Tracked asset positions for auto geometry checks
        self._asset_positions: dict[str, _AssetPosition] = {}
        # Restricted zone definitions: zone_id -> (lat, lon, radius_m)
        self._zone_defs: dict[str, tuple[float, float, float]] = {}

    @property
    def alerts(self) -> list[OperatorAlert]:
        """Snapshot of all generated alerts."""
        return list(self._alerts)

    def clear(self) -> None:
        """Clear all stored alerts."""
        self._alerts.clear()

    def _add_alert(self, alert: OperatorAlert) -> OperatorAlert:
        """Add an alert to the internal list and return it."""
        self._alerts.append(alert)
        return alert

    def _utc_now(self) -> str:
        return datetime.now(UTC).isoformat()

    def process_event(self, event: SensorEvent) -> list[OperatorAlert]:
        """Process a single SensorEvent and return any triggered alerts.

        This is the main entry point for the sensor/fusion pipeline.
        Each event is checked against all alert conditions.
        """
        triggered: list[OperatorAlert] = []

        # Extract common fields
        payload = event.payload
        asset_id = payload.get("asset_id") or payload.get("platform_id")
        sensor_id = event.source_id

        # Check for stale feed
        if asset_id:
            try:
                event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                now = datetime.now(UTC)
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                age = (now - event_ts).total_seconds()
                if age > self.stale_threshold_s:
                    triggered.append(self._create_stale_alert(asset_id, sensor_id, age))
            except (ValueError, TypeError):
                pass  # Skip staleness check for invalid timestamps

        # Check for dropped frame
        if payload.get("is_dropped_frame"):
            triggered.append(self._create_dropped_frame_alert(asset_id, sensor_id, event))

        # Check for sensor degradation
        degradation = payload.get("degradation_mode", "clear")
        if degradation and degradation != "clear":
            quality = payload.get("quality_score", 1.0)
            if quality < 0.6:
                triggered.append(
                    self._create_sensor_degraded_alert(asset_id, sensor_id, degradation, quality)
                )

        # Check confidence drop
        if event.confidence < self.confidence_drop_threshold:
            triggered.append(
                self._create_confidence_drop_alert(asset_id, sensor_id, event.confidence)
            )

        # Check battery level (from telemetry events)
        battery = payload.get("battery_pct")
        if battery is not None and battery < self.battery_low_threshold:
            triggered.append(self._create_battery_low_alert(asset_id, sensor_id, battery))

        # Check for video cues (object detections)
        detections = payload.get("data", {}).get("detections", [])
        if detections:
            triggered.append(
                self._create_video_cue_alert(asset_id, sensor_id, detections, event)
            )

        # Check for RF cues (thermal signatures or RF-specific data)
        signatures = payload.get("data", {}).get("signatures", [])
        if signatures:
            triggered.append(self._create_rf_cue_alert(asset_id, sensor_id, signatures, event))

        # Update last-seen tracking
        if asset_id:
            try:
                event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                self._last_seen[asset_id] = event_ts.timestamp()
            except (ValueError, TypeError):
                pass

        for alert in triggered:
            self._add_alert(alert)

        return triggered

    def check_position_breach(
        self,
        asset_id: str,
        lat: float,
        lon: float,
        zone_id: str,
        zone_lat: float,
        zone_lon: float,
        zone_radius_m: float,
    ) -> OperatorAlert | None:
        """Check if an asset position breaches a restricted zone.

        Uses simple equirectangular distance approximation (accurate for small areas).
        """
        # Quick bounding box check first
        lat_diff = abs(lat - zone_lat)
        lon_diff = abs(lon - zone_lon)

        # Rough conversion: 1 degree lat ~ 111km, 1 degree lon ~ 111km * cos(lat)
        if lat_diff > zone_radius_m / 111000 + 0.01:
            return None  # Too far north/south
        if lon_diff > zone_radius_m / (111000 * 0.8) + 0.01:
            return None  # Too far east/west

        # More precise distance calculation
        meters_per_deg_lat = 111320.0
        meters_per_deg_lon = meters_per_deg_lat * 0.75  # Approximate for mid-latitudes

        delta_north = (lat - zone_lat) * meters_per_deg_lat
        delta_east = (lon - zone_lon) * meters_per_deg_lon
        distance = (delta_north**2 + delta_east**2) ** 0.5

        if distance <= zone_radius_m:
            alert = self._create_position_breach_alert(
                asset_id, zone_id, distance, lat, lon, zone_radius_m
            )
            self._add_alert(alert)
            return alert

        return None

    def check_route_conflict(
        self,
        asset_a_id: str,
        asset_a_lat: float,
        asset_a_lon: float,
        asset_a_heading: float,
        asset_a_speed: float,
        asset_b_id: str,
        asset_b_lat: float,
        asset_b_lon: float,
        asset_b_heading: float,
        asset_b_speed: float,
        conflict_range_m: float = 50.0,
    ) -> OperatorAlert | None:
        """Check if two assets are on a collision course.

        Returns an alert if the assets are within the conflict range.
        """
        meters_per_deg_lat = 111320.0
        meters_per_deg_lon = meters_per_deg_lat * 0.75

        delta_north = (asset_a_lat - asset_b_lat) * meters_per_deg_lat
        delta_east = (asset_a_lon - asset_b_lon) * meters_per_deg_lon
        distance = (delta_north**2 + delta_east**2) ** 0.5

        if distance <= conflict_range_m:
            alert = self._create_route_conflict_alert(
                asset_a_id,
                asset_b_id,
                distance,
                conflict_range_m,
            )
            self._add_alert(alert)
            return alert

        return None

    def _create_stale_alert(
        self, asset_id: str | None, sensor_id: str | None, age: float
    ) -> OperatorAlert:
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.STALE_FEED.value,
            severity=AlertSeverity.MEDIUM.value,
            message=f"Stale feed detected: {age:.1f}s old (threshold: {self.stale_threshold_s}s)",
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={"age_seconds": age, "threshold_seconds": self.stale_threshold_s},
        )

    def _create_dropped_frame_alert(
        self, asset_id: str | None, sensor_id: str | None, event: SensorEvent
    ) -> OperatorAlert:
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.DROPPED_FRAME.value,
            severity=AlertSeverity.LOW.value,
            message=f"Dropped frame from sensor {sensor_id or 'unknown'}",
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={
                "event_id": event.event_id,
                "source": event.source,
                "confidence": event.confidence,
            },
        )

    def _create_sensor_degraded_alert(
        self,
        asset_id: str | None,
        sensor_id: str | None,
        degradation: str,
        quality: float,
    ) -> OperatorAlert:
        severity = AlertSeverity.MEDIUM if quality < 0.4 else AlertSeverity.LOW
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.SENSOR_DEGRADED.value,
            severity=severity.value,
            message=f"Sensor degradation: {degradation} (quality: {quality:.2f})",
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={"degradation_mode": degradation, "quality_score": quality},
        )

    def _create_confidence_drop_alert(
        self, asset_id: str | None, sensor_id: str | None, confidence: float
    ) -> OperatorAlert:
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.CONFIDENCE_DROP.value,
            severity=AlertSeverity.MEDIUM.value,
            message=(
                "Low confidence track: "
                f"{confidence:.2f} (threshold: {self.confidence_drop_threshold})"
            ),
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={"confidence": confidence, "threshold": self.confidence_drop_threshold},
        )

    def _create_battery_low_alert(
        self, asset_id: str | None, sensor_id: str | None, battery: float
    ) -> OperatorAlert:
        severity = AlertSeverity.HIGH if battery < 10 else AlertSeverity.MEDIUM
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.BATTERY_LOW.value,
            severity=severity.value,
            message=f"Low battery on {asset_id or 'asset'}: {battery:.0f}%",
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={"battery_pct": battery, "threshold": self.battery_low_threshold},
        )

    def _create_video_cue_alert(
        self,
        asset_id: str | None,
        sensor_id: str | None,
        detections: list[dict[str, Any]],
        event: SensorEvent,
    ) -> OperatorAlert:
        # Prioritize based on detection classes
        high_priority_classes = {"person", "vehicle"}
        has_priority = any(d.get("class") in high_priority_classes for d in detections)
        severity = AlertSeverity.HIGH if has_priority else AlertSeverity.MEDIUM

        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.VIDEO_CUE.value,
            severity=severity.value,
            message=f"Video cue: {len(detections)} detection(s) from {sensor_id or 'camera'}",
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={
                "detection_count": len(detections),
                "detections": detections,
                "event_confidence": event.confidence,
            },
        )

    def _create_rf_cue_alert(
        self,
        asset_id: str | None,
        sensor_id: str | None,
        signatures: list[dict[str, Any]],
        event: SensorEvent,
    ) -> OperatorAlert:
        # Check for high-temperature signatures (potential heat sources)
        high_temp = any(s.get("peak_temp_c", 0) > 60 for s in signatures)
        severity = AlertSeverity.HIGH if high_temp else AlertSeverity.MEDIUM

        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.RF_CUE.value,
            severity=severity.value,
            message=f"Thermal cue: {len(signatures)} signature(s) from {sensor_id or 'sensor'}",
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={
                "signature_count": len(signatures),
                "signatures": signatures,
                "event_confidence": event.confidence,
            },
        )

    def _create_position_breach_alert(
        self,
        asset_id: str,
        zone_id: str,
        distance_m: float,
        lat: float,
        lon: float,
        zone_radius_m: float,
    ) -> OperatorAlert:
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.POSITION_BREACH.value,
            severity=AlertSeverity.HIGH.value,
            message=(
                f"RESTRICTED ZONE BREACH: {asset_id} entered {zone_id} "
                f"(distance: {distance_m:.1f}m)"
            ),
            asset_id=asset_id,
            sensor_id=None,
            timestamp=self._utc_now(),
            payload={
                "zone_id": zone_id,
                "distance_m": distance_m,
                "zone_radius_m": zone_radius_m,
                "latitude": lat,
                "longitude": lon,
            },
        )

    def _create_route_conflict_alert(
        self,
        asset_a_id: str,
        asset_b_id: str,
        distance_m: float,
        conflict_range_m: float,
    ) -> OperatorAlert:
        severity = (
            AlertSeverity.CRITICAL
            if distance_m < conflict_range_m / 2
            else AlertSeverity.HIGH
        )
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.ROUTE_CONFLICT.value,
            severity=severity.value,
            message=(
                f"ROUTE CONFLICT: {asset_a_id} and {asset_b_id} "
                f"at {distance_m:.1f}m (min: {conflict_range_m}m)"
            ),
            asset_id=asset_a_id,
            sensor_id=None,
            timestamp=self._utc_now(),
            payload={
                "asset_a_id": asset_a_id,
                "asset_b_id": asset_b_id,
                "distance_m": distance_m,
                "conflict_range_m": conflict_range_m,
            },
        )

    def process_events_batch(
        self, events: list[SensorEvent]
    ) -> list[OperatorAlert]:
        """Process multiple events and return all triggered alerts."""
        all_alerts: list[OperatorAlert] = []
        for event in events:
            alerts = self.process_event(event)
            all_alerts.extend(alerts)
        return all_alerts

    def get_alerts_by_severity(
        self, severity: AlertSeverity | str
    ) -> list[OperatorAlert]:
        """Filter alerts by severity level."""
        if isinstance(severity, AlertSeverity):
            severity = severity.value
        return [a for a in self._alerts if a.severity == severity]

    def get_critical_alerts(self) -> list[OperatorAlert]:
        """Get all critical alerts requiring immediate attention."""
        return self.get_alerts_by_severity(AlertSeverity.CRITICAL)

    def get_actionable_alerts(self) -> list[OperatorAlert]:
        """Get alerts requiring operator action (critical + high)."""
        return [
            a
            for a in self._alerts
            if a.severity in (AlertSeverity.CRITICAL.value, AlertSeverity.HIGH.value)
        ]
