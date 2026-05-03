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
    PSEUDO_CLASSIFICATION = "pseudo_classification"  # Zero-shot scene context


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
        """Clear all stored alerts and dedup state."""
        self._alerts.clear()
        self._dedup_window.clear()

    def add_restricted_zone(
        self,
        zone_id: str,
        zone_lat: float,
        zone_lon: float,
        zone_radius_m: float,
    ) -> None:
        """Register a restricted zone for automatic breach detection.

        Once registered, any GNSS/telemetry event that updates an asset's
        position will be automatically checked against this zone.
        """
        self._zone_defs[zone_id] = (zone_lat, zone_lon, zone_radius_m)

    def _is_duplicate(self, dedup_key: str) -> bool:
        """Check if an alert with this dedup key was recently emitted."""
        last_ts = self._dedup_window.get(dedup_key)
        if last_ts is None:
            return False
        now = datetime.now(UTC).timestamp()
        return (now - last_ts) < self.dedup_cooldown_s

    def _record_dedup(self, dedup_key: str) -> None:
        """Record that an alert was emitted for this dedup key."""
        self._dedup_window[dedup_key] = datetime.now(UTC).timestamp()

    def _extract_gnss_position(self, event: SensorEvent) -> _AssetPosition | None:
        """Extract asset position from a GNSS/telemetry event payload.

        Returns None if the event does not contain position data.
        """
        payload = event.payload
        asset_id = payload.get("asset_id") or payload.get("platform_id")
        if not asset_id:
            return None

        # Check for position data in payload.data (sensor emulator format)
        data = payload.get("data", {})
        position = data.get("position")
        if position and "lat" in position and "lon" in position:
            velocity = data.get("velocity", {})
            orientation = data.get("orientation", {})
            heading = orientation.get("yaw", 0.0)
            speed = (velocity.get("vx_mps", 0.0) ** 2 + velocity.get("vy_mps", 0.0) ** 2) ** 0.5
            try:
                event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                ts = event_ts.timestamp()
            except (ValueError, TypeError):
                ts = datetime.now(UTC).timestamp()
            return _AssetPosition(
                asset_id=asset_id,
                lat=float(position["lat"]),
                lon=float(position["lon"]),
                heading=heading,
                speed=speed,
                timestamp=ts,
            )

        # Check for position data in top-level payload (drone_telemetry format)
        lat = payload.get("lat") or payload.get("latitude")
        lon = payload.get("lon") or payload.get("longitude")
        if lat is not None and lon is not None:
            heading = payload.get("heading", 0.0)
            speed = payload.get("speed", 0.0)
            try:
                event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                ts = event_ts.timestamp()
            except (ValueError, TypeError):
                ts = datetime.now(UTC).timestamp()
            return _AssetPosition(
                asset_id=asset_id,
                lat=float(lat),
                lon=float(lon),
                heading=float(heading),
                speed=float(speed),
                timestamp=ts,
            )

        return None

    def _auto_position_breach_check(self, pos: _AssetPosition) -> list[OperatorAlert]:
        """Check a tracked position against all registered restricted zones."""
        triggered: list[OperatorAlert] = []
        for zone_id, (z_lat, z_lon, z_radius) in self._zone_defs.items():
            dedup_key = f"pos_breach:{pos.asset_id}:{zone_id}"
            if self._is_duplicate(dedup_key):
                continue
            alert = self.check_position_breach(
                asset_id=pos.asset_id,
                lat=pos.lat,
                lon=pos.lon,
                zone_id=zone_id,
                zone_lat=z_lat,
                zone_lon=z_lon,
                zone_radius_m=z_radius,
            )
            if alert is not None:
                self._record_dedup(dedup_key)
                triggered.append(alert)
        return triggered

    def _auto_route_conflict_check(self, updated_pos: _AssetPosition) -> list[OperatorAlert]:
        """Check an updated position against all other tracked positions for conflicts."""
        triggered: list[OperatorAlert] = []
        for asset_id, other_pos in self._asset_positions.items():
            if asset_id == updated_pos.asset_id:
                continue
            first_asset = min(updated_pos.asset_id, asset_id)
            second_asset = max(updated_pos.asset_id, asset_id)
            dedup_key = f"route_conflict:{first_asset}:{second_asset}"
            if self._is_duplicate(dedup_key):
                continue
            alert = self.check_route_conflict(
                asset_a_id=updated_pos.asset_id,
                asset_a_lat=updated_pos.lat,
                asset_a_lon=updated_pos.lon,
                asset_a_heading=updated_pos.heading,
                asset_a_speed=updated_pos.speed,
                asset_b_id=other_pos.asset_id,
                asset_b_lat=other_pos.lat,
                asset_b_lon=other_pos.lon,
                asset_b_heading=other_pos.heading,
                asset_b_speed=other_pos.speed,
                conflict_range_m=self.route_conflict_range_m,
            )
            if alert is not None:
                self._record_dedup(dedup_key)
                triggered.append(alert)
        return triggered

    def _add_alert(self, alert: OperatorAlert) -> OperatorAlert:
        """Add an alert to the internal list and return it."""
        self._alerts.append(alert)
        return alert

    def _utc_now(self) -> str:
        return datetime.now(UTC).isoformat()

    def process_event(self, event: SensorEvent) -> list[OperatorAlert]:
        """Process a single SensorEvent and return any triggered alerts.

        This is the main entry point for the sensor/fusion pipeline.
        Each event is checked against all alert conditions, with dedup
        suppression to avoid alert storms.
        """
        triggered: list[OperatorAlert] = []

        # Extract common fields
        payload = event.payload
        asset_id = payload.get("asset_id") or payload.get("platform_id")
        sensor_id = event.source_id

        # Check for stale feed
        if asset_id:
            dedup_key = f"stale:{asset_id}"
            try:
                event_ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
                now = datetime.now(UTC)
                if event_ts.tzinfo is None:
                    event_ts = event_ts.replace(tzinfo=UTC)
                age = (now - event_ts).total_seconds()
                if age > self.stale_threshold_s and not self._is_duplicate(dedup_key):
                    triggered.append(self._create_stale_alert(asset_id, sensor_id, age))
                    self._record_dedup(dedup_key)
            except (ValueError, TypeError):
                pass  # Skip staleness check for invalid timestamps

        # Check for dropped frame
        if payload.get("is_dropped_frame"):
            dedup_key = f"dropped:{asset_id or 'unknown'}:{sensor_id}"
            if not self._is_duplicate(dedup_key):
                triggered.append(self._create_dropped_frame_alert(asset_id, sensor_id, event))
                self._record_dedup(dedup_key)

        # Check for sensor degradation
        degradation = payload.get("degradation_mode", "clear")
        if degradation and degradation != "clear":
            quality = payload.get("quality_score", 1.0)
            if quality < 0.6:
                dedup_key = f"degraded:{asset_id or 'unknown'}:{degradation}"
                if not self._is_duplicate(dedup_key):
                    triggered.append(
                        self._create_sensor_degraded_alert(
                            asset_id, sensor_id, degradation, quality
                        )
                    )
                    self._record_dedup(dedup_key)

        # Check confidence drop
        if event.confidence < self.confidence_drop_threshold:
            dedup_key = f"conf_drop:{asset_id or 'unknown'}:{sensor_id}"
            if not self._is_duplicate(dedup_key):
                triggered.append(
                    self._create_confidence_drop_alert(asset_id, sensor_id, event.confidence)
                )
                self._record_dedup(dedup_key)

        # Check battery level (from telemetry events)
        battery = payload.get("battery_pct")
        if battery is not None and battery < self.battery_low_threshold:
            dedup_key = f"battery:{asset_id or 'unknown'}"
            if not self._is_duplicate(dedup_key):
                triggered.append(self._create_battery_low_alert(asset_id, sensor_id, battery))
                self._record_dedup(dedup_key)

        # Check for video cues (object detections) — optional, not center of work
        if payload.get("pseudo_classification_alert"):
            pseudo = payload.get("pseudo_classification")
            if isinstance(pseudo, dict):
                label = pseudo.get("label")
                score = float(pseudo.get("score", event.confidence))
                floor = float(payload.get("pseudo_classification_alert_floor", 0.0))
                if isinstance(label, str) and label and score >= floor:
                    dedup_key = f"pseudo:{asset_id or 'unknown'}:{sensor_id}:{label}"
                    if not self._is_duplicate(dedup_key):
                        triggered.append(
                            self._create_pseudo_classification_alert(
                                asset_id,
                                sensor_id,
                                label,
                                score,
                                event,
                            )
                        )
                        self._record_dedup(dedup_key)

        # Check for video cues (object detections) — optional, not center of work
        detections = payload.get("data", {}).get("detections", [])
        if detections:
            dedup_key = f"video_cue:{asset_id or 'unknown'}:{sensor_id}"
            if not self._is_duplicate(dedup_key):
                triggered.append(
                    self._create_video_cue_alert(asset_id, sensor_id, detections, event)
                )
                self._record_dedup(dedup_key)

        # Check for RF cues (thermal signatures or RF-specific data)
        signatures = payload.get("data", {}).get("signatures", [])
        if signatures:
            dedup_key = f"rf_cue:{asset_id or 'unknown'}:{sensor_id}"
            if not self._is_duplicate(dedup_key):
                triggered.append(self._create_rf_cue_alert(asset_id, sensor_id, signatures, event))
                self._record_dedup(dedup_key)

        # Auto-check: extract GNSS position and check geometry
        pos = self._extract_gnss_position(event)
        if pos is not None:
            self._asset_positions[pos.asset_id] = pos
            # Auto position breach check against registered zones
            if self._zone_defs:
                breach_alerts = self._auto_position_breach_check(pos)
                triggered.extend(breach_alerts)
            # Auto route conflict check against other tracked assets
            if len(self._asset_positions) > 1:
                conflict_alerts = self._auto_route_conflict_check(pos)
                triggered.extend(conflict_alerts)

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
            return self._create_position_breach_alert(
                asset_id, zone_id, distance, lat, lon, zone_radius_m
            )

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
            return self._create_route_conflict_alert(
                asset_a_id,
                asset_b_id,
                distance,
                conflict_range_m,
            )

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

    def _create_pseudo_classification_alert(
        self,
        asset_id: str | None,
        sensor_id: str | None,
        label: str,
        score: float,
        event: SensorEvent,
    ) -> OperatorAlert:
        return OperatorAlert(
            alert_id=str(uuid.uuid4()),
            alert_type=AlertType.PSEUDO_CLASSIFICATION.value,
            severity=AlertSeverity.LOW.value,
            message=(
                f"Pseudo classification: {label} "
                f"(score: {score:.2f}); confirm visually before acting"
            ),
            asset_id=asset_id,
            sensor_id=sensor_id,
            timestamp=self._utc_now(),
            payload={
                "label": label,
                "score": score,
                "event_id": event.event_id,
                "source": event.source,
                "frame_path": event.payload.get("frame_path"),
                "classification_mode": event.payload.get("classification_mode"),
                "candidates": event.payload.get("data", {}).get("candidates", []),
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

    def persist_alerts(self, store: Any) -> int:
        """Persist all alerts to a MissionStateStore.

        Each alert is persisted via store.create_alert() with the alert
        severity and message. Returns the number of alerts persisted.
        """
        count = 0
        for alert in self._alerts:
            store.create_alert(
                message=alert.message,
                severity=alert.severity,
                payload=alert.to_alert_payload(),
            )
            count += 1
        return count

    def get_operator_summary(self) -> dict[str, Any]:
        """Return a prioritized operator alert summary.

        The summary groups alerts by severity (critical first) and provides
        counts per type. This is suitable for operator display or runbook
        consumption without requiring cloud infrastructure.
        """
        severity_order = {
            AlertSeverity.CRITICAL.value: 0,
            AlertSeverity.HIGH.value: 1,
            AlertSeverity.MEDIUM.value: 2,
            AlertSeverity.LOW.value: 3,
        }

        by_severity: dict[str, list[dict[str, Any]]] = {
            "critical": [], "high": [], "medium": [], "low": []
        }
        type_counts: dict[str, int] = {}

        for alert in self._alerts:
            entry = {
                "alert_id": alert.alert_id,
                "alert_type": alert.alert_type,
                "message": alert.message,
                "asset_id": alert.asset_id,
                "sensor_id": alert.sensor_id,
                "timestamp": alert.timestamp,
            }
            by_severity[alert.severity].append(entry)
            type_counts[alert.alert_type] = type_counts.get(alert.alert_type, 0) + 1

        # Sort by severity (critical first)
        sorted_types = sorted(
            type_counts.items(),
            key=lambda x: max(
                severity_order.get(a.severity, 99)
                for a in self._alerts
                if a.alert_type == x[0]
            ),
        )

        return {
            "total_alerts": len(self._alerts),
            "actionable_count": len(self.get_actionable_alerts()),
            "critical_count": len(by_severity["critical"]),
            "high_count": len(by_severity["high"]),
            "medium_count": len(by_severity["medium"]),
            "low_count": len(by_severity["low"]),
            "type_counts": dict(sorted_types),
            "by_severity": by_severity,
        }
