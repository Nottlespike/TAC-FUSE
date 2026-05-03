"""Offline swarm control: prove single-operator denied-ops capability.

These tests verify that a single operator can task, retask, and monitor
multiple drones while completely disconnected from enterprise services.
No Foundry, Maven, internet, or central C2 is required.
"""

from __future__ import annotations

from tac_fuse.connectivity import ConnectivityController, ConnectivityMode
from tac_fuse.fusion_node import AlertingEngine, IngestBus
from tac_fuse.fusion_node.alerting import AlertSeverity, AlertType
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import (
    SeededReplayEngine,
    demo_conflicts,
    demo_restricted_entries,
    generate_scenario,
)
from tac_fuse.sensors.models import DegradationMode, create_platform_emulator


class TestOfflineSwarmTasking:
    """Prove operator can issue commands to multiple drones while offline."""

    def test_create_tasks_for_all_drones_offline(self) -> None:
        """Operator creates tasks for 4 drones while offline."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        drone_ids = ["uav-alpha", "uav-bravo", "uav-charlie", "uav-delta"]
        for drone_id in drone_ids:
            task = store.create_task(
                title=f"Patrol sector - {drone_id}",
                description=f"Assign patrol route to {drone_id}",
                metadata={"drone_id": drone_id, "command": "patrol"},
            )
            assert task["status"] == "pending"

        tasks = store.list_tasks()
        assert len(tasks) == 4

        # All tasks queued for sync (but not synced)
        assert store.pending_sync_count() >= 4
        assert not ctrl.is_external_sync_allowed()

    def test_retask_drone_while_offline(self) -> None:
        """Operator updates a task (retasks) a drone while offline."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        task = store.create_task(title="Alpha patrol", metadata={"command": "patrol"})
        updated = store.update_task(
            task["id"], title="Alpha return home", metadata={"command": "return"}
        )
        assert updated["title"] == "Alpha return home"
        assert updated["metadata"]["command"] == "return"
        assert store.pending_sync_count() >= 2  # create + update

    def test_abort_all_drones_offline(self) -> None:
        """Operator issues abort to all drones while offline."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        for drone in ["alpha", "bravo", "charlie", "delta"]:
            store.create_task(
                title=f"ABORT {drone}",
                metadata={"drone_id": f"uav-{drone}", "command": "abort"},
            )

        tasks = store.list_tasks()
        abort_tasks = [t for t in tasks if "ABORT" in t["title"]]
        assert len(abort_tasks) == 4
        assert store.pending_sync_count() >= 4

    def test_sync_released_when_online(self) -> None:
        """Sync gate releases queued commands when connectivity restored."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)

        # Start offline, issue commands
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)
        store.create_task(title="Patrol alpha")
        store.create_task(title="Patrol bravo")
        assert store.pending_sync_count() >= 2

        # Go online — sync is now allowed
        ctrl.set_manual_override(ConnectivityMode.ONLINE)
        assert ctrl.is_external_sync_allowed()
        # Queue still has pending items (release is separate)
        assert store.pending_sync_count() >= 2

    def test_degraded_mode_still_queues(self) -> None:
        """DEGRADED mode allows local C2 but holds sync queue."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.DEGRADED)

        store.create_task(title="Scout delta", metadata={"command": "scout"})
        assert not ctrl.is_external_sync_allowed()
        assert store.pending_sync_count() >= 1

    def test_connectivity_mode_persisted(self) -> None:
        """Connectivity mode persists across controller instances."""
        store = MissionStateStore()
        ctrl1 = ConnectivityController(store)
        ctrl1.set_manual_override(ConnectivityMode.OFFLINE)

        # New controller reads persisted state
        ctrl2 = ConnectivityController(store)
        assert ctrl2.get_current_mode() == ConnectivityMode.OFFLINE


class TestOfflineAlertGeneration:
    """Prove alerting works while disconnected."""

    def test_battery_alert_generated_offline(self) -> None:
        """Low battery alert fires from sensor event while offline."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        engine = AlertingEngine(battery_low_threshold=20.0)
        bus = IngestBus(max_staleness_s=0)

        event = bus.ingest(
            {
                "source": "drone_telemetry",
                "source_id": "uav-alpha_telemetry",
                "timestamp": "2026-05-02T12:00:00Z",
                "confidence": 0.9,
                "payload": {
                    "asset_id": "uav-alpha",
                    "battery_pct": 12.0,
                },
            }
        )

        alerts = engine.process_event(event)
        assert len(alerts) >= 1
        battery_alerts = [a for a in alerts if a.alert_type == "battery_low"]
        assert len(battery_alerts) == 1
        assert battery_alerts[0].severity == AlertSeverity.MEDIUM.value

    def test_position_breach_alert_offline(self) -> None:
        """Zone breach alert fires while offline."""
        engine = AlertingEngine(restricted_zones={"rf-denial-east"})

        alert = engine.check_position_breach(
            asset_id="uav-charlie",
            lat=38.8900,
            lon=-77.0345,
            zone_id="rf-denial-east",
            zone_lat=38.8900,
            zone_lon=-77.0345,
            zone_radius_m=100.0,
        )
        assert alert is not None
        assert alert.alert_type == AlertType.POSITION_BREACH.value
        assert alert.severity == AlertSeverity.HIGH.value

    def test_route_conflict_alert_offline(self) -> None:
        """Route conflict detection works offline."""
        engine = AlertingEngine()

        alert = engine.check_route_conflict(
            asset_a_id="uav-alpha",
            asset_a_lat=38.8895,
            asset_a_lon=-77.0353,
            asset_a_heading=45.0,
            asset_a_speed=15.0,
            asset_b_id="uav-charlie",
            asset_b_lat=38.8895,
            asset_b_lon=-77.0353,
            asset_b_heading=225.0,
            asset_b_speed=12.0,
            conflict_range_m=50.0,
        )
        assert alert is not None
        assert alert.alert_type == AlertType.ROUTE_CONFLICT.value

    def test_confidence_drop_alert_offline(self) -> None:
        """Confidence drop alert fires from degraded sensor data."""
        engine = AlertingEngine(confidence_drop_threshold=0.5)
        bus = IngestBus(max_staleness_s=0)

        event = bus.ingest(
            {
                "source": "external_field_sensors",
                "source_id": "uav-delta_eo_rgb",
                "timestamp": "2026-05-02T12:00:00Z",
                "confidence": 0.3,
                "payload": {"asset_id": "uav-delta"},
            }
        )

        alerts = engine.process_event(event)
        conf_alerts = [a for a in alerts if a.alert_type == "confidence_drop"]
        assert len(conf_alerts) == 1

    def test_sensor_degraded_alert_offline(self) -> None:
        """Sensor degradation alert fires for environmental conditions."""
        engine = AlertingEngine()
        bus = IngestBus(max_staleness_s=0)

        event = bus.ingest(
            {
                "source": "external_field_sensors",
                "source_id": "uav-alpha_ir_thermal",
                "timestamp": "2026-05-02T12:00:00Z",
                "confidence": 0.7,
                "payload": {
                    "asset_id": "uav-alpha",
                    "degradation_mode": "smoke",
                    "quality_score": 0.35,
                },
            }
        )

        alerts = engine.process_event(event)
        deg_alerts = [a for a in alerts if a.alert_type == "sensor_degraded"]
        assert len(deg_alerts) == 1
        assert deg_alerts[0].severity == AlertSeverity.MEDIUM.value

    def test_video_cue_alert_offline(self) -> None:
        """Video detection cue generates alert while offline."""
        engine = AlertingEngine()
        bus = IngestBus(max_staleness_s=0)

        event = bus.ingest(
            {
                "source": "npu_vision",
                "source_id": "uav-alpha_eo",
                "timestamp": "2026-05-02T12:00:00Z",
                "confidence": 0.85,
                "payload": {
                    "asset_id": "uav-alpha",
                    "data": {
                        "detections": [
                            {"class": "person", "confidence": 0.92},
                            {"class": "vehicle", "confidence": 0.78},
                        ]
                    },
                },
            }
        )

        alerts = engine.process_event(event)
        video_alerts = [a for a in alerts if a.alert_type == "video_cue"]
        assert len(video_alerts) == 1
        assert video_alerts[0].severity == AlertSeverity.HIGH.value

    def test_dropped_frame_alert_offline(self) -> None:
        """Dropped frame detection generates alert while offline."""
        engine = AlertingEngine()
        bus = IngestBus(max_staleness_s=0)

        event = bus.ingest(
            {
                "source": "drone_pov",
                "source_id": "uav-bravo_cam",
                "timestamp": "2026-05-02T12:00:00Z",
                "confidence": 0.0,
                "payload": {
                    "asset_id": "uav-bravo",
                    "is_dropped_frame": True,
                },
            }
        )

        alerts = engine.process_event(event)
        drop_alerts = [a for a in alerts if a.alert_type == "dropped_frame"]
        assert len(drop_alerts) == 1

    def test_no_position_breach_outside_zone(self) -> None:
        """No false breach alert when asset is outside zone."""
        engine = AlertingEngine()

        alert = engine.check_position_breach(
            asset_id="uav-alpha",
            lat=39.0000,
            lon=-76.0000,
            zone_id="rf-denial-east",
            zone_lat=38.8900,
            zone_lon=-77.0345,
            zone_radius_m=100.0,
        )
        assert alert is None

    def test_actionable_alerts_filter(self) -> None:
        """AlertingEngine correctly filters actionable (critical + high) alerts."""
        engine = AlertingEngine(battery_low_threshold=20.0)
        bus = IngestBus(max_staleness_s=0)

        # Generate multiple alerts
        for pct in [8.0, 15.0, 25.0]:
            event = bus.ingest(
                {
                    "source": "drone_telemetry",
                    "source_id": f"drone-{pct}",
                    "timestamp": "2026-05-02T12:00:00Z",
                    "confidence": 0.9,
                    "payload": {"asset_id": f"drone-{pct}", "battery_pct": pct},
                }
            )
            engine.process_event(event)

        actionable = engine.get_actionable_alerts()
        # Only the 8% one should be HIGH (actionable), 15% is MEDIUM
        assert any(a.severity == AlertSeverity.HIGH.value for a in actionable)


class TestOfflineReplayFromFixtures:
    """Prove replay works from deterministic fixtures while offline."""

    def test_replay_generates_tracks_offline(self) -> None:
        """Seeded replay generates asset tracks without network."""
        engine = SeededReplayEngine(seed=42, duration_sec=45.0)
        frames = engine.generate()
        assert len(frames) > 0
        assert all(len(frame) > 0 for frame in frames)
        for frame in frames:
            for track in frame:
                assert track.asset_id
                assert track.confidence > 0
                assert track.battery_pct > 0

    def test_replay_tracks_match_web_demo_assets(self) -> None:
        """Replay fixture assets match the web demo drone IDs."""
        scenario = generate_scenario()
        all_ids: set[str] = set()
        for frame in scenario:
            for track in frame:
                all_ids.add(track.asset_id)
        expected = {"uav-alpha", "uav-bravo", "uav-charlie", "uav-delta", "ground-team-1"}
        assert all_ids == expected

    def test_replay_conflict_detection_offline(self) -> None:
        """Route conflicts detected from replay fixtures offline."""
        conflicts = demo_conflicts()
        assert len(conflicts) >= 1
        assert conflicts[0].asset_ids[0] != conflicts[0].asset_ids[1]

    def test_replay_restricted_entries_offline(self) -> None:
        """Restricted zone entries detected from replay fixtures offline."""
        entries = demo_restricted_entries()
        assert len(entries) >= 1
        assert entries[0].asset_id
        assert entries[0].zone_id

    def test_replay_battery_drain_trajectory(self) -> None:
        """Replay tracks show battery decreasing over time."""
        scenario = generate_scenario()
        alpha_batteries = [
            frame[0].battery_pct
            for frame in scenario
            if frame[0].asset_id == "uav-alpha"
        ]
        assert alpha_batteries == sorted(alpha_batteries, reverse=True)


class TestOfflineSensorFusion:
    """Prove sensor fusion pipeline works offline end-to-end."""

    def test_multi_sensor_emulator_offline(self) -> None:
        """Sensor emulator produces observations without network."""
        platform = create_platform_emulator(
            "uav-alpha", degradation_mode=DegradationMode.HAZE, seed=42
        )
        observations = platform.emulate_all(frame_index=0)
        assert len(observations) > 0

        events = platform.emulate_to_events(frame_index=0)
        assert len(events) > 0
        for event in events:
            assert event.source
            assert event.confidence >= 0.0

    def test_ingest_bus_accepts_emulator_events_offline(self) -> None:
        """Ingest bus processes emulator events without network."""
        bus = IngestBus(max_staleness_s=0)
        platform = create_platform_emulator("uav-alpha", seed=42)

        for frame_idx in range(5):
            events = platform.emulate_to_events(frame_index=frame_idx)
            for event in events:
                raw = event.to_dict()
                accepted = bus.ingest(raw)
                assert accepted.event_id
        assert bus.count() > 0

    def test_alerting_from_full_pipeline_offline(self) -> None:
        """Full pipeline: emulator → bus → alerting, all offline."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        bus = IngestBus(max_staleness_s=0)
        engine = AlertingEngine(battery_low_threshold=30.0)

        event = bus.ingest(
            {
                "source": "drone_telemetry",
                "source_id": "uav-charlie_telemetry",
                "timestamp": "2026-05-02T12:00:00Z",
                "confidence": 0.85,
                "payload": {
                    "asset_id": "uav-charlie",
                    "battery_pct": 15.0,
                },
            }
        )

        alerts = engine.process_event(event)
        assert len(alerts) >= 1

        for alert in alerts:
            store.create_alert(
                alert.message, severity=alert.severity, payload=alert.to_dict()
            )

        stored_alerts = store.list_alerts()
        assert len(stored_alerts) >= 1
        assert store.pending_sync_count() >= 1
        assert not ctrl.is_external_sync_allowed()

    def test_audit_trail_preserved_offline(self) -> None:
        """All operator actions are audited while offline."""
        store = MissionStateStore()
        ctrl = ConnectivityController(store)
        ctrl.set_manual_override(ConnectivityMode.OFFLINE)

        store.create_task(title="Patrol alpha", metadata={"command": "patrol"})
        store.create_task(title="Return bravo", metadata={"command": "return"})
        store.create_alert("Battery low on uav-charlie", severity="high")

        audit = store.list_audit_events()
        assert len(audit) >= 3

        event_types = {e["event_type"] for e in audit}
        assert "task_created" in event_types
        assert "alert_created" in event_types

    def test_track_insertion_offline(self) -> None:
        """Asset tracks from replay are stored locally while offline."""
        store = MissionStateStore()
        scenario = generate_scenario(frames=3)

        total = 0
        for frame in scenario:
            count = store.insert_tracks(frame)
            total += count
        assert total > 0
        assert store.count_tracks() == total
