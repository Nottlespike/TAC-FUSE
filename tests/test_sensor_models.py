"""Tests for deterministic sensor emulation models."""

from __future__ import annotations

import pytest

from tac_fuse.fusion_node.ingest import ContributorSource
from tac_fuse.sensors.models import (
    Covariance2D,
    Covariance3D,
    DegradationMode,
    DepthRangeEmulator,
    EOCameraEmulator,
    GNSSIMUEmulator,
    IRThermalEmulator,
    MultiSensorEmulator,
    SensorEmulatorConfig,
    SensorObservation,
    SensorType,
    create_platform_emulator,
)


class TestCovariance:
    """Tests for covariance matrix representations."""

    def test_covariance_2d_matrix(self) -> None:
        cov = Covariance2D(var_x=4.0, var_y=9.0, cov_xy=1.0)
        matrix = cov.to_matrix()
        assert matrix == [[4.0, 1.0], [1.0, 9.0]]

    def test_covariance_2d_determinant(self) -> None:
        cov = Covariance2D(var_x=4.0, var_y=9.0, cov_xy=1.0)
        assert cov.determinant() == 35.0

    def test_covariance_2d_positive_definite(self) -> None:
        cov = Covariance2D(var_x=4.0, var_y=9.0, cov_xy=1.0)
        assert cov.is_positive_definite() is True

    def test_covariance_2d_not_positive_definite(self) -> None:
        cov = Covariance2D(var_x=0.5, var_y=0.5, cov_xy=0.5)
        assert cov.is_positive_definite() is False

    def test_covariance_3d_matrix(self) -> None:
        cov = Covariance3D(
            var_x=1.0, var_y=2.0, var_z=3.0,
            cov_xy=0.1, cov_xz=0.2, cov_yz=0.3,
        )
        matrix = cov.to_matrix()
        assert matrix == [
            [1.0, 0.1, 0.2],
            [0.1, 2.0, 0.3],
            [0.2, 0.3, 3.0],
        ]


class TestSensorEmulatorConfig:
    """Tests for sensor emulator configuration."""

    def test_config_defaults(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="test_001",
            platform_id="drone_001",
        )
        assert config.seed == 42
        assert config.base_confidence == 0.95
        assert config.drop_rate == 0.05
        assert config.degradation_mode == DegradationMode.CLEAR

    def test_config_derive_rng_deterministic(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="test_001",
            platform_id="drone_001",
            seed=12345,
        )
        rng1 = config.derive_rng(0)
        rng2 = config.derive_rng(0)
        assert rng1.random() == rng2.random()


class TestEOCameraEmulator:
    """Tests for EO/RGB camera sensor emulator."""

    def test_emulator_creates_observation(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="eo_cam_001",
            platform_id="drone_001",
            seed=42,
        )
        emulator = EOCameraEmulator(config)
        obs = emulator.emulate(frame_index=0)

        assert obs.sensor_type == "eo_rgb"
        assert obs.sensor_id == "eo_cam_001"
        assert obs.platform_id == "drone_001"
        assert obs.data["frame_width"] == 1920
        assert obs.data["frame_height"] == 1080

    def test_emulator_deterministic_replay(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="eo_cam_001",
            platform_id="drone_001",
            seed=42,
        )
        emulator1 = EOCameraEmulator(config)
        emulator2 = EOCameraEmulator(config)

        obs1 = emulator1.emulate(frame_index=0)
        obs2 = emulator2.emulate(frame_index=0)

        assert obs1.observation_id == obs2.observation_id
        assert obs1.confidence == obs2.confidence
        assert obs1.data["detections"] == obs2.data["detections"]

    def test_emulator_covariance_included(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="eo_cam_001",
            platform_id="drone_001",
            seed=42,
        )
        emulator = EOCameraEmulator(config)
        obs = emulator.emulate(frame_index=0)

        assert obs.covariance is not None
        assert obs.covariance["type"] == "2d"
        assert "var_x" in obs.covariance
        assert "var_y" in obs.covariance

    def test_emulator_degradation_affects_confidence(self) -> None:
        config_clear = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="eo_cam_001",
            platform_id="drone_001",
            seed=42,
            degradation_mode=DegradationMode.CLEAR,
        )
        config_fog = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="eo_cam_001",
            platform_id="drone_001",
            seed=42,
            degradation_mode=DegradationMode.FOG,
        )

        emulator_clear = EOCameraEmulator(config_clear)
        emulator_fog = EOCameraEmulator(config_fog)

        obs_clear = emulator_clear.emulate(frame_index=0)
        obs_fog = emulator_fog.emulate(frame_index=0)

        assert obs_clear.quality_score == 1.0
        assert obs_fog.quality_score == 0.4


class TestIRThermalEmulator:
    """Tests for IR/Thermal sensor emulator."""

    def test_emulator_creates_observation(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.IR_THERMAL,
            sensor_id="ir_cam_001",
            platform_id="drone_001",
            seed=42,
            drop_rate=0.0,
        )
        emulator = IRThermalEmulator(config)
        obs = emulator.emulate(frame_index=0)

        assert obs.sensor_type == "ir_thermal"
        assert obs.data["frame_width"] == 640
        assert obs.data["frame_height"] == 480
        assert "signatures" in obs.data

    def test_emulator_deterministic_replay(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.IR_THERMAL,
            sensor_id="ir_cam_001",
            platform_id="drone_001",
            seed=42,
            drop_rate=0.0,
        )
        emulator1 = IRThermalEmulator(config)
        emulator2 = IRThermalEmulator(config)

        obs1 = emulator1.emulate(frame_index=0)
        obs2 = emulator2.emulate(frame_index=0)

        assert obs1.observation_id == obs2.observation_id
        assert obs1.data["signatures"] == obs2.data["signatures"]


class TestDepthRangeEmulator:
    """Tests for depth/range sensor emulator."""

    def test_emulator_creates_observation(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.DEPTH_RANGE,
            sensor_id="depth_001",
            platform_id="drone_001",
            seed=42,
        )
        emulator = DepthRangeEmulator(config)
        obs = emulator.emulate(frame_index=0)

        assert obs.sensor_type == "depth_range"
        assert "num_points" in obs.data
        assert "points_sample" in obs.data
        assert obs.covariance is not None
        assert obs.covariance["type"] == "3d"

    def test_emulator_deterministic_replay(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.DEPTH_RANGE,
            sensor_id="depth_001",
            platform_id="drone_001",
            seed=42,
        )
        emulator1 = DepthRangeEmulator(config)
        emulator2 = DepthRangeEmulator(config)

        obs1 = emulator1.emulate(frame_index=0)
        obs2 = emulator2.emulate(frame_index=0)

        assert obs1.observation_id == obs2.observation_id
        assert obs1.data["num_points"] == obs2.data["num_points"]


class TestGNSSIMUEmulator:
    """Tests for GNSS/IMU state sensor emulator."""

    def test_emulator_creates_observation(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.GNSS,
            sensor_id="gnss_001",
            platform_id="drone_001",
            seed=42,
            drop_rate=0.0,
        )
        emulator = GNSSIMUEmulator(
            config,
            initial_position=(0.0, 0.0, 0.0),
            initial_velocity=(0.0, 0.0, 0.0),
        )
        obs = emulator.emulate(frame_index=0)

        assert obs.sensor_type == "gnss"
        assert "position" in obs.data
        assert "velocity" in obs.data
        assert "orientation" in obs.data
        assert "gnss" in obs.data

    def test_emulator_tracks_position(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.GNSS,
            sensor_id="gnss_001",
            platform_id="drone_001",
            seed=42,
            drop_rate=0.0,
        )
        emulator = GNSSIMUEmulator(
            config,
            initial_position=(0.0, 0.0, 0.0),
            initial_velocity=(1.0, 0.5, 0.0),
        )

        obs0 = emulator.emulate(frame_index=0)
        obs1 = emulator.emulate(frame_index=1)

        pos0 = obs0.data["position"]
        pos1 = obs1.data["position"]

        assert pos0["lat"] != pos1["lat"] or pos0["lon"] != pos1["lon"]

    def test_emulator_covariance_included(self) -> None:
        config = SensorEmulatorConfig(
            sensor_type=SensorType.GNSS,
            sensor_id="gnss_001",
            platform_id="drone_001",
            seed=42,
            drop_rate=0.0,
        )
        emulator = GNSSIMUEmulator(config)
        obs = emulator.emulate(frame_index=0)

        assert obs.covariance is not None
        assert "position" in obs.covariance
        assert "orientation" in obs.covariance


class TestMultiSensorEmulator:
    """Tests for multi-sensor emulation."""

    def test_add_and_get_emulator(self) -> None:
        multi = MultiSensorEmulator(platform_id="drone_001", seed=42)

        config = SensorEmulatorConfig(
            sensor_type=SensorType.EO_RGB,
            sensor_id="eo_001",
            platform_id="drone_001",
        )
        emulator = EOCameraEmulator(config)
        multi.add_emulator(emulator)

        assert multi.get_emulator(SensorType.EO_RGB) is emulator
        assert multi.get_emulator(SensorType.IR_THERMAL) is None

    def test_emulate_all(self) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            sensor_types=[SensorType.EO_RGB, SensorType.IR_THERMAL],
            seed=42,
        )

        observations = multi.emulate_all(frame_index=0)

        assert len(observations) == 2
        sensor_types = {obs.sensor_type for obs in observations}
        assert "eo_rgb" in sensor_types
        assert "ir_thermal" in sensor_types

    def test_emulate_to_events(self) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            sensor_types=[SensorType.EO_RGB],
            seed=42,
        )

        events = multi.emulate_to_events(frame_index=0)

        assert len(events) == 1
        event = events[0]
        assert event.source == ContributorSource.EXTERNAL_FIELD_SENSORS.value
        assert event.source_id == "drone_001_eo_rgb"
        assert "sensor_type" in event.payload


class TestCreatePlatformEmulator:
    """Tests for the factory function."""

    def test_creates_all_sensors_by_default(self) -> None:
        multi = create_platform_emulator(platform_id="drone_001", seed=42)

        assert multi.get_emulator(SensorType.EO_RGB) is not None
        assert multi.get_emulator(SensorType.IR_THERMAL) is not None
        assert multi.get_emulator(SensorType.DEPTH_RANGE) is not None
        assert multi.get_emulator(SensorType.GNSS) is not None
        assert multi.get_emulator(SensorType.IMU) is not None

    def test_creates_specific_sensors(self) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            sensor_types=[SensorType.EO_RGB],
            seed=42,
        )

        assert multi.get_emulator(SensorType.EO_RGB) is not None
        assert multi.get_emulator(SensorType.IR_THERMAL) is None

    def test_respects_degradation_mode(self) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            seed=42,
            degradation_mode=DegradationMode.SMOKE,
        )

        obs = multi.emulate_all(frame_index=0)[0]
        assert obs.degradation_mode == "smoke"
        assert obs.quality_score == 0.5


class TestSensorObservation:
    """Tests for sensor observation data structure."""

    def test_to_dict(self) -> None:
        obs = SensorObservation(
            observation_id="obs_001",
            sensor_type="eo_rgb",
            sensor_id="cam_001",
            platform_id="drone_001",
            timestamp="2024-01-01T00:00:00Z",
            received_at="2024-01-01T00:00:00Z",
            data={"test": "data"},
            confidence=0.9,
            uncertainty=0.1,
            covariance={"type": "2d"},
            degradation_mode="clear",
            quality_score=1.0,
        )

        d = obs.to_dict()
        assert d["observation_id"] == "obs_001"
        assert d["sensor_type"] == "eo_rgb"
        assert d["data"] == {"test": "data"}

    def test_to_sensor_event(self) -> None:
        obs = SensorObservation(
            observation_id="obs_001",
            sensor_type="eo_rgb",
            sensor_id="cam_001",
            platform_id="drone_001",
            timestamp="2024-01-01T00:00:00Z",
            received_at="2024-01-01T00:00:00Z",
            data={"test": "data"},
            confidence=0.9,
            uncertainty=0.1,
            covariance={"type": "2d"},
            degradation_mode="clear",
            quality_score=1.0,
            seq=5,
        )

        event = obs.to_sensor_event(
            source=ContributorSource.DRONE_POV,
            provenance="test_provenance",
        )

        assert event.event_id == "obs_001"
        assert event.source == "drone_pov"
        assert event.source_id == "cam_001"
        assert event.confidence == 0.9
        assert event.uncertainty == 0.1
        assert event.seq == 5
        assert event.payload["sensor_type"] == "eo_rgb"
        assert event.payload["data"] == {"test": "data"}


class TestDeterminism:
    """Tests for deterministic replay behavior."""

    def test_sequence_determinism(self) -> None:
        """Same seed + frame index produces identical observations."""
        multi1 = create_platform_emulator(platform_id="drone_001", seed=42)
        multi2 = create_platform_emulator(platform_id="drone_001", seed=42)

        obs1 = multi1.emulate_all(frame_index=0)
        obs2 = multi2.emulate_all(frame_index=0)

        for o1, o2 in zip(obs1, obs2, strict=True):
            assert o1.observation_id == o2.observation_id
            assert o1.confidence == o2.confidence
            assert o1.data == o2.data

    def test_frame_index_determinism(self) -> None:
        """Different frame indices produce different observations."""
        multi = create_platform_emulator(platform_id="drone_001", seed=42)

        obs0 = multi.emulate_all(frame_index=0)
        obs1 = multi.emulate_all(frame_index=1)

        for o0, o1 in zip(obs0, obs1, strict=True):
            assert o0.observation_id != o1.observation_id

    def test_multiple_frames_sequence(self) -> None:
        """Multiple sequential frames are deterministic."""
        multi1 = create_platform_emulator(platform_id="drone_001", seed=42)
        multi2 = create_platform_emulator(platform_id="drone_001", seed=42)

        for frame_idx in range(5):
            obs1 = multi1.emulate_all(frame_index=frame_idx)
            obs2 = multi2.emulate_all(frame_index=frame_idx)
            for o1, o2 in zip(obs1, obs2, strict=True):
                assert o1.observation_id == o2.observation_id


class TestDroppedFrames:
    """Tests for dropped frame behavior."""

    def test_drop_rate_zero_no_drops(self) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            seed=42,
            drop_rate=0.0,
        )

        for _ in range(10):
            obs = multi.emulate_all(frame_index=0)[0]
            assert obs.is_dropped_frame is False
            assert obs.data != {}

    def test_drop_rate_one_all_dropped(self) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            seed=42,
            drop_rate=1.0,
        )

        for _ in range(10):
            obs = multi.emulate_all(frame_index=0)[0]
            assert obs.is_dropped_frame is True
            assert obs.data == {}
            assert obs.confidence < 0.2


class TestDegradationModes:
    """Tests for all degradation modes."""

    @pytest.mark.parametrize("mode", DegradationMode)
    def test_all_modes_produce_valid_observations(self, mode: DegradationMode) -> None:
        multi = create_platform_emulator(
            platform_id="drone_001",
            seed=42,
            degradation_mode=mode,
        )

        obs = multi.emulate_all(frame_index=0)[0]
        assert obs.degradation_mode == mode.value
        assert obs.quality_score > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
