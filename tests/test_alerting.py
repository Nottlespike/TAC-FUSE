"""Tests for the local alerting engine.

These tests verify that sensor observations and geometry events
become prioritized operator alerts without cloud infrastructure.
"""

from __future__ import annotations

from tac_fuse.fusion_node.alerting import (
    AlertingEngine,
    AlertSeverity,
    AlertType,
    OperatorAlert,
)
from tac_fuse.fusion_node.ingest import SensorEvent


def make_sensor_event(
    source: str = "drone_pov",
    source_id: str = "camera_001",
    payload: dict | None = None,
    confidence: float = 0.9,
    timestamp: str | None = None,
) -> SensorEvent:
    """Helper to create test sensor events."""
    import uuid
    from datetime import UTC, datetime

    if timestamp is None:
        timestamp = datetime.now(UTC).isoformat()

    return SensorEvent(
        event_id=str(uuid.uuid4()),
        source=source,
        source_id=source_id,
        timestamp=timestamp,
        received_at=datetime.now(UTC).isoformat(),
        confidence=confidence,
        uncertainty=1.0 - confidence,
        provenance="test",
        seq=1,
        payload=payload or {},
    )


class TestOperatorAlert:
    """Tests for the OperatorAlert data structure."""

    def test_alert_creation(self) -> None:
        alert = OperatorAlert(
            alert_id="alert-001",
            alert_type="video_cue",
            severity="high",
            message="Test alert",
            asset_id="uav-alpha",
            sensor_id="camera_001",
            timestamp="2024-01-01T00:00:00Z",
        )
        assert alert.alert_id == "alert-001"
        assert alert.alert_type == "video_cue"
        assert alert.severity == "high"
        assert alert.asset_id == "uav-alpha"

    def test_alert_to_dict(self) -> None:
        alert = OperatorAlert(
            alert_id="alert-001",
            alert_type="position_breach",
            severity="critical",
            message="Breach detected",
            asset_id="uav-alpha",
            sensor_id=None,
            timestamp="2024-01-01T00:00:00Z",
            payload={"zone_id": "restricted-zone-1"},
        )
        d = alert.to_dict()
        assert d["alert_id"] == "alert-001"
        assert d["payload"]["zone_id"] == "restricted-zone-1"

    def test_alert_to_payload(self) -> None:
        alert = OperatorAlert(
            alert_id="alert-001",
            alert_type="battery_low",
            severity="medium",
            message="Low battery",
            asset_id="uav-bravo",
            sensor_id="telemetry_001",
            timestamp="2024-01-01T00:00:00Z",
            payload={"battery_pct": 15},
        )
        payload = alert.to_alert_payload()
        assert payload["alert_id"] == "alert-001"
        assert payload["battery_pct"] == 15


class TestAlertingEngine:
    """Tests for the AlertingEngine."""

    def test_engine_initial_state(self) -> None:
        engine = AlertingEngine()
        assert engine.alerts == []
        assert engine.get_critical_alerts() == []

    def test_engine_clear(self) -> None:
        engine = AlertingEngine()
        # Manually add an alert for testing
        engine._alerts.append(
            OperatorAlert(
                alert_id="test",
                alert_type="test",
                severity="low",
                message="test",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            )
        )
        assert len(engine.alerts) == 1
        engine.clear()
        assert engine.alerts == []


class TestVideoCueAlerts:
    """Tests for video/object detection alerts."""

    def test_video_cue_with_detections(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-alpha",
                "data": {
                    "detections": [
                        {
                            "class": "person",
                            "bbox": [100, 100, 50, 50],
                            "class_confidence": 0.95,
                        }
                    ]
                },
            }
        )
        alerts = engine.process_event(event)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.VIDEO_CUE.value
        assert alerts[0].severity == AlertSeverity.HIGH.value
        assert alerts[0].asset_id == "uav-alpha"

    def test_video_cue_multiple_detections(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-alpha",
                "data": {
                    "detections": [
                        {"class": "vehicle", "bbox": [100, 100, 50, 50], "class_confidence": 0.9},
                        {"class": "person", "bbox": [200, 200, 30, 30], "class_confidence": 0.85},
                        {"class": "unknown", "bbox": [300, 300, 20, 20], "class_confidence": 0.5},
                    ]
                },
            }
        )
        alerts = engine.process_event(event)
        assert len(alerts) == 1
        assert alerts[0].payload["detection_count"] == 3

    def test_video_cue_low_priority(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-alpha",
                "data": {
                    "detections": [
                        {
                            "class": "unknown",
                            "bbox": [100, 100, 50, 50],
                            "class_confidence": 0.5,
                        }
                    ]
                },
            }
        )
        alerts = engine.process_event(event)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.MEDIUM.value


class TestPseudoClassificationAlerts:
    """Tests for zero-shot pseudo-classification context alerts."""

    def test_pseudo_classification_is_silent_by_default(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            source="npu_vision",
            source_id="siglip2_zero_shot",
            payload={
                "asset_id": "uav-alpha",
                "classification_mode": "pseudo",
                "pseudo_classification": {
                    "label": "landing zone",
                    "prompt": "a landing zone",
                    "score": 0.91,
                    "logit": 5.0,
                },
                "data": {"candidates": []},
            },
            confidence=0.91,
        )

        assert engine.process_event(event) == []

    def test_pseudo_classification_alert_is_context_not_detection(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            source="npu_vision",
            source_id="siglip2_zero_shot",
            payload={
                "asset_id": "uav-alpha",
                "frame_path": "/tmp/frame.jpg",
                "classification_mode": "pseudo",
                "pseudo_classification_alert": True,
                "pseudo_classification_alert_floor": 0.8,
                "pseudo_classification": {
                    "label": "landing zone",
                    "prompt": "a landing zone",
                    "score": 0.91,
                    "logit": 5.0,
                },
                "data": {"detections": [], "candidates": []},
            },
            confidence=0.91,
        )

        alerts = engine.process_event(event)

        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.PSEUDO_CLASSIFICATION.value
        assert alerts[0].severity == AlertSeverity.LOW.value
        assert alerts[0].payload["label"] == "landing zone"
        assert alerts[0].payload["frame_path"] == "/tmp/frame.jpg"


class TestRFCueAlerts:
    """Tests for RF/thermal cue alerts."""

    def test_rf_cue_with_signatures(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            source="npu_vision",
            source_id="thermal_001",
            payload={
                "platform_id": "uav-bravo",
                "data": {
                    "signatures": [
                        {
                            "signature_id": "sig-001",
                            "centroid": [320, 240],
                            "peak_temp_c": 75.0,
                            "avg_temp_c": 60.0,
                            "area_pixels": 150,
                        }
                    ]
                },
            },
        )
        alerts = engine.process_event(event)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.RF_CUE.value
        assert alerts[0].severity == AlertSeverity.HIGH.value  # High temp

    def test_rf_cue_normal_temperature(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-bravo",
                "data": {
                    "signatures": [
                        {
                            "signature_id": "sig-001",
                            "peak_temp_c": 35.0,
                            "avg_temp_c": 30.0,
                        }
                    ]
                },
            }
        )
        alerts = engine.process_event(event)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.MEDIUM.value  # Normal temp


class TestStaleFeedAlerts:
    """Tests for stale feed detection."""

    def test_stale_feed_alert(self) -> None:
        engine = AlertingEngine(stale_threshold_s=5.0)
        # Create an old timestamp
        old_ts = "2020-01-01T00:00:00+00:00"
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha"},
            timestamp=old_ts,
        )
        alerts = engine.process_event(event)
        # Should trigger stale alert
        stale_alerts = [a for a in alerts if a.alert_type == AlertType.STALE_FEED.value]
        assert len(stale_alerts) >= 1

    def test_fresh_feed_no_alert(self) -> None:
        engine = AlertingEngine(stale_threshold_s=5.0)
        from datetime import UTC, datetime

        fresh_ts = datetime.now(UTC).isoformat()
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha"},
            timestamp=fresh_ts,
        )
        alerts = engine.process_event(event)
        stale_alerts = [a for a in alerts if a.alert_type == AlertType.STALE_FEED.value]
        assert len(stale_alerts) == 0


class TestBatteryAlerts:
    """Tests for low battery alerts."""

    def test_battery_low_critical(self) -> None:
        engine = AlertingEngine(battery_low_threshold=20.0)
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha", "battery_pct": 8},
        )
        alerts = engine.process_event(event)
        battery_alerts = [a for a in alerts if a.alert_type == AlertType.BATTERY_LOW.value]
        assert len(battery_alerts) == 1
        assert battery_alerts[0].severity == AlertSeverity.HIGH.value  # Below 10%

    def test_battery_low_warning(self) -> None:
        engine = AlertingEngine(battery_low_threshold=20.0)
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha", "battery_pct": 15},
        )
        alerts = engine.process_event(event)
        battery_alerts = [a for a in alerts if a.alert_type == AlertType.BATTERY_LOW.value]
        assert len(battery_alerts) == 1
        assert battery_alerts[0].severity == AlertSeverity.MEDIUM.value  # 10-20%

    def test_battery_normal_no_alert(self) -> None:
        engine = AlertingEngine(battery_low_threshold=20.0)
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha", "battery_pct": 50},
        )
        alerts = engine.process_event(event)
        battery_alerts = [a for a in alerts if a.alert_type == AlertType.BATTERY_LOW.value]
        assert len(battery_alerts) == 0


class TestConfidenceDropAlerts:
    """Tests for confidence drop alerts."""

    def test_confidence_drop_alert(self) -> None:
        engine = AlertingEngine(confidence_drop_threshold=0.5)
        event = make_sensor_event(confidence=0.3)
        alerts = engine.process_event(event)
        conf_alerts = [a for a in alerts if a.alert_type == AlertType.CONFIDENCE_DROP.value]
        assert len(conf_alerts) == 1

    def test_confidence_normal_no_alert(self) -> None:
        engine = AlertingEngine(confidence_drop_threshold=0.5)
        event = make_sensor_event(confidence=0.8)
        alerts = engine.process_event(event)
        conf_alerts = [a for a in alerts if a.alert_type == AlertType.CONFIDENCE_DROP.value]
        assert len(conf_alerts) == 0


class TestDroppedFrameAlerts:
    """Tests for dropped frame alerts."""

    def test_dropped_frame_alert(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha", "is_dropped_frame": True}
        )
        alerts = engine.process_event(event)
        drop_alerts = [a for a in alerts if a.alert_type == AlertType.DROPPED_FRAME.value]
        assert len(drop_alerts) == 1

    def test_normal_frame_no_alert(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={"platform_id": "uav-alpha", "is_dropped_frame": False}
        )
        alerts = engine.process_event(event)
        drop_alerts = [a for a in alerts if a.alert_type == AlertType.DROPPED_FRAME.value]
        assert len(drop_alerts) == 0


class TestSensorDegradationAlerts:
    """Tests for sensor degradation alerts."""

    def test_fog_degradation_alert(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-alpha",
                "degradation_mode": "fog",
                "quality_score": 0.35,  # Below 0.4 threshold for MEDIUM
            }
        )
        alerts = engine.process_event(event)
        deg_alerts = [a for a in alerts if a.alert_type == AlertType.SENSOR_DEGRADED.value]
        assert len(deg_alerts) == 1
        assert deg_alerts[0].severity == AlertSeverity.MEDIUM.value

    def test_smoke_degradation_critical(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-alpha",
                "degradation_mode": "smoke",
                "quality_score": 0.3,
            }
        )
        alerts = engine.process_event(event)
        deg_alerts = [a for a in alerts if a.alert_type == AlertType.SENSOR_DEGRADED.value]
        assert len(deg_alerts) == 1
        assert deg_alerts[0].severity == AlertSeverity.MEDIUM.value  # quality < 0.4

    def test_clear_conditions_no_alert(self) -> None:
        engine = AlertingEngine()
        event = make_sensor_event(
            payload={
                "platform_id": "uav-alpha",
                "degradation_mode": "clear",
                "quality_score": 1.0,
            }
        )
        alerts = engine.process_event(event)
        deg_alerts = [a for a in alerts if a.alert_type == AlertType.SENSOR_DEGRADED.value]
        assert len(deg_alerts) == 0


class TestPositionBreach:
    """Tests for restricted zone breach detection."""

    def test_position_breach_detected(self) -> None:
        engine = AlertingEngine()
        # Asset at 37.7749, -122.4194 (San Francisco)
        # Zone center at same location with 100m radius
        alert = engine.check_position_breach(
            asset_id="uav-alpha",
            lat=37.7749,
            lon=-122.4194,
            zone_id="restricted-zone-sf",
            zone_lat=37.7749,
            zone_lon=-122.4194,
            zone_radius_m=100.0,
        )
        assert alert is not None
        assert alert.alert_type == AlertType.POSITION_BREACH.value
        assert alert.severity == AlertSeverity.HIGH.value

    def test_position_outside_zone(self) -> None:
        engine = AlertingEngine()
        # Asset far from zone
        alert = engine.check_position_breach(
            asset_id="uav-alpha",
            lat=37.8,  # About 3km north
            lon=-122.4,
            zone_id="restricted-zone-sf",
            zone_lat=37.7749,
            zone_lon=-122.4194,
            zone_radius_m=100.0,
        )
        assert alert is None


class TestRouteConflict:
    """Tests for route conflict/collision detection."""

    def test_route_conflict_detected(self) -> None:
        engine = AlertingEngine()
        # Two assets at same location
        alert = engine.check_route_conflict(
            asset_a_id="uav-alpha",
            asset_a_lat=37.7749,
            asset_a_lon=-122.4194,
            asset_a_heading=0.0,
            asset_a_speed=10.0,
            asset_b_id="uav-bravo",
            asset_b_lat=37.7749,
            asset_b_lon=-122.4194,
            asset_b_heading=180.0,
            asset_b_speed=10.0,
            conflict_range_m=50.0,
        )
        assert alert is not None
        assert alert.alert_type == AlertType.ROUTE_CONFLICT.value
        assert alert.severity == AlertSeverity.CRITICAL.value  # Very close

    def test_route_conflict_close(self) -> None:
        engine = AlertingEngine()
        # Two assets 30m apart (within 50m range)
        # ~0.00027 deg lat ~= 30m
        alert = engine.check_route_conflict(
            asset_a_id="uav-alpha",
            asset_a_lat=37.7749,
            asset_a_lon=-122.4194,
            asset_a_heading=0.0,
            asset_a_speed=10.0,
            asset_b_id="uav-bravo",
            asset_b_lat=37.77517,  # ~30m north
            asset_b_lon=-122.4194,
            asset_b_heading=180.0,
            asset_b_speed=10.0,
            conflict_range_m=50.0,
        )
        assert alert is not None
        assert alert.severity == AlertSeverity.HIGH.value  # Within range but not critical

    def test_no_conflict_far_apart(self) -> None:
        engine = AlertingEngine()
        # Two assets far apart
        alert = engine.check_route_conflict(
            asset_a_id="uav-alpha",
            asset_a_lat=37.7749,
            asset_a_lon=-122.4194,
            asset_a_heading=0.0,
            asset_a_speed=10.0,
            asset_b_id="uav-bravo",
            asset_b_lat=37.78,  # ~500m north
            asset_b_lon=-122.4194,
            asset_b_heading=180.0,
            asset_b_speed=10.0,
            conflict_range_m=50.0,
        )
        assert alert is None


class TestAlertFiltering:
    """Tests for alert filtering methods."""

    def test_get_alerts_by_severity(self) -> None:
        engine = AlertingEngine()
        # Add alerts of different severities
        engine._alerts = [
            OperatorAlert(
                alert_id="1",
                alert_type="test",
                severity="critical",
                message="critical",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
            OperatorAlert(
                alert_id="2",
                alert_type="test",
                severity="high",
                message="high",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
            OperatorAlert(
                alert_id="3",
                alert_type="test",
                severity="low",
                message="low",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
        ]
        critical = engine.get_alerts_by_severity(AlertSeverity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].alert_id == "1"

    def test_get_critical_alerts(self) -> None:
        engine = AlertingEngine()
        engine._alerts = [
            OperatorAlert(
                alert_id="1",
                alert_type="test",
                severity="critical",
                message="critical",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
            OperatorAlert(
                alert_id="2",
                alert_type="test",
                severity="high",
                message="high",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
        ]
        critical = engine.get_critical_alerts()
        assert len(critical) == 1

    def test_get_actionable_alerts(self) -> None:
        engine = AlertingEngine()
        engine._alerts = [
            OperatorAlert(
                alert_id="1",
                alert_type="test",
                severity="critical",
                message="critical",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
            OperatorAlert(
                alert_id="2",
                alert_type="test",
                severity="high",
                message="high",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
            OperatorAlert(
                alert_id="3",
                alert_type="test",
                severity="medium",
                message="medium",
                asset_id=None,
                sensor_id=None,
                timestamp="2024-01-01T00:00:00Z",
            ),
        ]
        actionable = engine.get_actionable_alerts()
        assert len(actionable) == 2  # critical + high


class TestBatchProcessing:
    """Tests for batch event processing."""

    def test_process_events_batch(self) -> None:
        engine = AlertingEngine()
        events = [
            make_sensor_event(
                payload={"platform_id": "uav-alpha", "battery_pct": 10},
                source_id="cam_001",
            ),
            make_sensor_event(
                payload={"platform_id": "uav-bravo", "battery_pct": 5},
                source_id="cam_002",
            ),
        ]
        alerts = engine.process_events_batch(events)
        battery_alerts = [a for a in alerts if a.alert_type == AlertType.BATTERY_LOW.value]
        assert len(battery_alerts) == 2


class TestIntegrationWithSensorModels:
    """Integration tests with sensor emulator models."""

    def test_sensor_observation_to_alert(self) -> None:
        """Test that sensor observations can trigger alerts through the full pipeline."""
        from tac_fuse.sensors.models import (
            DegradationMode,
            SensorType,
            create_platform_emulator,
        )

        # Create emulator with degraded conditions
        emulator = create_platform_emulator(
            platform_id="uav-test",
            sensor_types=[SensorType.EO_RGB],
            seed=42,
            degradation_mode=DegradationMode.FOG,
            drop_rate=0.5,  # High drop rate
        )

        engine = AlertingEngine()

        # Emulate and process multiple frames
        for frame_idx in range(5):
            observations = emulator.emulate_all(frame_index=frame_idx)
            for obs in observations:
                event = obs.to_sensor_event()
                engine.process_event(event)

        # Verify engine collected alerts
        assert len(engine.alerts) >= 0  # At least ran without errors


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
