"""Deterministic sensor emulation for field conditions.

This module provides deterministic sensor models that emulate field conditions
for EO/RGB cameras, IR/thermal sensors, depth/range sensors, and GNSS/IMU state.
Each sensor model supports configurable degradation effects including reduced
visibility, dropped frames, stale tracks, and low-confidence detections.

The output is structured as :class:`SensorObservation` objects that can be
converted to :class:`SensorEvent` envelopes for the fusion ingest bus.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from tac_fuse.fusion_node.ingest import ContributorSource, SensorEvent


class SensorType(Enum):
    """Canonical sensor types for field emulation."""

    EO_RGB = "eo_rgb"
    IR_THERMAL = "ir_thermal"
    DEPTH_RANGE = "depth_range"
    GNSS = "gnss"
    IMU = "imu"


class DegradationMode(Enum):
    """Environmental degradation modes affecting sensor quality."""

    CLEAR = "clear"
    HAZE = "haze"
    SMOKE = "smoke"
    DUST = "dust"
    RAIN = "rain"
    FOG = "fog"
    LOW_LIGHT = "low_light"
    OCCLUDED = "occluded"


@dataclass(frozen=True)
class Covariance2D:
    """2D covariance matrix representation for observation uncertainty."""

    var_x: float = 1.0
    var_y: float = 1.0
    cov_xy: float = 0.0

    def to_matrix(self) -> list[list[float]]:
        return [[self.var_x, self.cov_xy], [self.cov_xy, self.var_y]]

    def determinant(self) -> float:
        return self.var_x * self.var_y - self.cov_xy * self.cov_xy

    def is_positive_definite(self) -> bool:
        return self.var_x > 0 and self.determinant() > 0


@dataclass(frozen=True)
class Covariance3D:
    """3D covariance matrix representation for position uncertainty."""

    var_x: float = 1.0
    var_y: float = 1.0
    var_z: float = 1.0
    cov_xy: float = 0.0
    cov_xz: float = 0.0
    cov_yz: float = 0.0

    def to_matrix(self) -> list[list[float]]:
        return [
            [self.var_x, self.cov_xy, self.cov_xz],
            [self.cov_xy, self.var_y, self.cov_yz],
            [self.cov_xz, self.cov_yz, self.var_z],
        ]


@dataclass(frozen=True)
class SensorObservation:
    """Normalized sensor observation with uncertainty metadata.

    This is the core output of sensor emulation. Each observation includes
    the raw sensor data, quality metrics, and covariance/uncertainty information
    that the fusion module can use for multi-sensor combination.
    """

    observation_id: str
    sensor_type: str
    sensor_id: str
    platform_id: str
    timestamp: str
    received_at: str
    data: dict[str, Any]
    confidence: float
    uncertainty: float
    covariance: dict[str, Any] | None
    degradation_mode: str
    quality_score: float
    is_dropped_frame: bool = False
    is_stale: bool = False
    seq: int = 0

    def to_sensor_event(
        self,
        source: ContributorSource = ContributorSource.EXTERNAL_FIELD_SENSORS,
        provenance: str = "sensor_emulator",
    ) -> SensorEvent:
        """Convert this observation to a fusion bus SensorEvent."""
        return SensorEvent(
            event_id=self.observation_id,
            source=source.value,
            source_id=self.sensor_id,
            timestamp=self.timestamp,
            received_at=self.received_at,
            confidence=self.confidence,
            uncertainty=self.uncertainty,
            provenance=provenance,
            seq=self.seq,
            payload={
                "sensor_type": self.sensor_type,
                "platform_id": self.platform_id,
                "data": self.data,
                "covariance": self.covariance,
                "degradation_mode": self.degradation_mode,
                "quality_score": self.quality_score,
                "is_dropped_frame": self.is_dropped_frame,
                "is_stale": self.is_stale,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SensorEmulatorConfig:
    """Configuration for deterministic sensor emulation."""

    sensor_type: SensorType
    sensor_id: str
    platform_id: str
    seed: int = 42
    base_confidence: float = 0.95
    base_uncertainty: float = 0.1
    drop_rate: float = 0.05
    stale_threshold_s: float = 5.0
    degradation_mode: DegradationMode = DegradationMode.CLEAR
    frame_interval_ms: int = 33

    def derive_rng(self, frame_index: int) -> random.Random:
        """Create a deterministic RNG for a specific frame."""
        combined_seed = self.seed + frame_index + hash(self.sensor_id) % 10000
        return random.Random(combined_seed)


class SensorEmulatorBase:
    """Base class for deterministic sensor emulators."""

    def __init__(self, config: SensorEmulatorConfig) -> None:
        self.config = config
        self._frame_index = 0
        self._last_timestamp: datetime | None = None
        self._seq_counter = 0

    def _get_deterministic_hash(self, suffix: str = "") -> str:
        """Generate a deterministic hash for observation IDs."""
        base = f"{self.config.sensor_id}-{self._frame_index}-{suffix}"
        return hashlib.sha256(base.encode()).hexdigest()[:16]

    def _compute_degradation_factor(self) -> float:
        """Compute a quality degradation factor based on mode."""
        mode = self.config.degradation_mode
        factors = {
            DegradationMode.CLEAR: 1.0,
            DegradationMode.HAZE: 0.7,
            DegradationMode.SMOKE: 0.5,
            DegradationMode.DUST: 0.6,
            DegradationMode.RAIN: 0.65,
            DegradationMode.FOG: 0.4,
            DegradationMode.LOW_LIGHT: 0.55,
            DegradationMode.OCCLUDED: 0.3,
        }
        return factors.get(mode, 1.0)

    def _should_drop_frame(self, rng: random.Random) -> bool:
        """Deterministically decide if this frame should be dropped."""
        return rng.random() < self.config.drop_rate

    def _compute_confidence(
        self, base: float, degradation_factor: float, rng: random.Random
    ) -> float:
        """Compute observation confidence with noise."""
        noise = rng.gauss(0, 0.05)
        return max(0.0, min(1.0, base * degradation_factor + noise))

    def _compute_uncertainty(
        self, base: float, degradation_factor: float, rng: random.Random
    ) -> float:
        """Compute observation uncertainty with noise."""
        noise = rng.gauss(0, 0.02)
        return max(0.0, min(1.0, base / degradation_factor + noise))

    def _get_timestamp(self, frame_index: int) -> str:
        """Generate deterministic timestamp for frame index."""
        base = datetime.now(UTC)
        if self._last_timestamp is None:
            self._last_timestamp = base
        else:
            self._last_timestamp = self._last_timestamp + timedelta(
                milliseconds=self.config.frame_interval_ms
            )
        return self._last_timestamp.isoformat()

    def emulate(self, frame_index: int | None = None) -> SensorObservation:
        """Emulate a single sensor observation.

        Subclasses must override _emulate_data() to provide sensor-specific data.
        """
        if frame_index is None:
            frame_index = self._frame_index
            self._frame_index += 1

        rng = self.config.derive_rng(frame_index)
        is_dropped = self._should_drop_frame(rng)
        degradation_factor = self._compute_degradation_factor()

        base_confidence = 0.0 if is_dropped else self.config.base_confidence
        base_uncertainty = 1.0 if is_dropped else self.config.base_uncertainty

        confidence = self._compute_confidence(base_confidence, degradation_factor, rng)
        uncertainty = self._compute_uncertainty(base_uncertainty, degradation_factor, rng)

        data = {} if is_dropped else self._emulate_data(rng, frame_index)
        covariance = None if is_dropped else self._emulate_covariance(rng, degradation_factor)

        timestamp = self._get_timestamp(frame_index)
        self._seq_counter += 1

        return SensorObservation(
            observation_id=self._get_deterministic_hash(f"obs-{frame_index}"),
            sensor_type=self.config.sensor_type.value,
            sensor_id=self.config.sensor_id,
            platform_id=self.config.platform_id,
            timestamp=timestamp,
            received_at=datetime.now(UTC).isoformat(),
            data=data,
            confidence=confidence,
            uncertainty=uncertainty,
            covariance=covariance,
            degradation_mode=self.config.degradation_mode.value,
            quality_score=degradation_factor if not is_dropped else 0.0,
            is_dropped_frame=is_dropped,
            is_stale=False,
            seq=self._seq_counter,
        )

    def _emulate_data(self, rng: random.Random, frame_index: int) -> dict[str, Any]:
        """Subclasses override to provide sensor-specific data."""
        raise NotImplementedError

    def _emulate_covariance(
        self, rng: random.Random, degradation_factor: float
    ) -> dict[str, Any] | None:
        """Subclasses override to provide sensor-specific covariance."""
        return None


class EOCameraEmulator(SensorEmulatorBase):
    """EO/RGB camera sensor emulator."""

    def _emulate_data(self, rng: random.Random, frame_index: int) -> dict[str, Any]:
        """Emulate EO camera frame with detected objects."""
        num_detections = rng.randint(0, 5)
        detections = []
        for i in range(num_detections):
            detections.append(
                {
                    "object_id": self._get_deterministic_hash(f"det-{i}"),
                    "bbox": [
                        rng.uniform(0, 1920),
                        rng.uniform(0, 1080),
                        rng.uniform(100, 400),
                        rng.uniform(100, 400),
                    ],
                    "class": rng.choice(["vehicle", "person", "structure", "unknown"]),
                    "class_confidence": rng.uniform(0.3, 0.99),
                }
            )

        return {
            "frame_width": 1920,
            "frame_height": 1080,
            "format": "rgb888",
            "detections": detections,
            "exposure_ms": rng.uniform(1, 30),
            "gain_db": rng.uniform(0, 20),
        }

    def _emulate_covariance(
        self, rng: random.Random, degradation_factor: float
    ) -> dict[str, Any]:
        """Emulate 2D position covariance for detections."""
        base_var = 10.0 / degradation_factor
        return {
            "type": "2d",
            "var_x": base_var + rng.uniform(-2, 2),
            "var_y": base_var + rng.uniform(-2, 2),
            "cov_xy": rng.uniform(-1, 1),
        }


class IRThermalEmulator(SensorEmulatorBase):
    """IR/Thermal sensor emulator."""

    def _emulate_data(self, rng: random.Random, frame_index: int) -> dict[str, Any]:
        """Emulate thermal frame with heat signatures."""
        num_signatures = rng.randint(0, 4)
        signatures = []
        for i in range(num_signatures):
            signatures.append(
                {
                    "signature_id": self._get_deterministic_hash(f"sig-{i}"),
                    "centroid": [rng.uniform(0, 640), rng.uniform(0, 480)],
                    "peak_temp_c": rng.uniform(25, 80),
                    "avg_temp_c": rng.uniform(20, 60),
                    "area_pixels": rng.randint(10, 500),
                    "is_animated": rng.choice([True, False]),
                }
            )

        return {
            "frame_width": 640,
            "frame_height": 480,
            "format": "thermal14",
            "temp_range_c": [rng.uniform(-10, 20), rng.uniform(50, 150)],
            "signatures": signatures,
            "emissivity": rng.uniform(0.9, 0.98),
        }

    def _emulate_covariance(
        self, rng: random.Random, degradation_factor: float
    ) -> dict[str, Any]:
        """Emulate thermal signature position covariance."""
        base_var = 15.0 / degradation_factor
        return {
            "type": "2d",
            "var_x": base_var + rng.uniform(-3, 3),
            "var_y": base_var + rng.uniform(-3, 3),
            "cov_xy": rng.uniform(-2, 2),
        }


class DepthRangeEmulator(SensorEmulatorBase):
    """Depth/Range sensor emulator (LiDAR, stereo depth, ToF)."""

    def _emulate_data(self, rng: random.Random, frame_index: int) -> dict[str, Any]:
        """Emulate depth point cloud or range measurements."""
        num_points = rng.randint(50, 200)
        points = []
        for i in range(num_points):
            points.append(
                [
                    rng.uniform(-50, 50),
                    rng.uniform(-50, 50),
                    rng.uniform(0.5, 100),
                ]
            )

        return {
            "sensor_type": rng.choice(["lidar", "stereo", "tof"]),
            "num_points": num_points,
            "range_min_m": 0.5,
            "range_max_m": 100.0,
            "points_sample": points[:10],
            "density_per_m2": rng.uniform(10, 100),
        }

    def _emulate_covariance(
        self, rng: random.Random, degradation_factor: float
    ) -> dict[str, Any]:
        """Emulate 3D position covariance for range measurements."""
        base_var = 0.5 / degradation_factor
        return {
            "type": "3d",
            "var_x": base_var + rng.uniform(-0.1, 0.1),
            "var_y": base_var + rng.uniform(-0.1, 0.1),
            "var_z": base_var * 2 + rng.uniform(-0.2, 0.2),
            "cov_xy": rng.uniform(-0.05, 0.05),
            "cov_xz": rng.uniform(-0.05, 0.05),
            "cov_yz": rng.uniform(-0.05, 0.05),
        }


class GNSSIMUEmulator(SensorEmulatorBase):
    """GNSS/IMU state sensor emulator."""

    def __init__(
        self,
        config: SensorEmulatorConfig,
        initial_position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        initial_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        super().__init__(config)
        self._position = list(initial_position)
        self._velocity = list(initial_velocity)
        self._orientation = [0.0, 0.0, 0.0]

    def _emulate_data(self, rng: random.Random, frame_index: int) -> dict[str, Any]:
        """Emulate GNSS position and IMU state."""
        dt = self.config.frame_interval_ms / 1000.0

        for i in range(3):
            accel_noise = rng.gauss(0, 0.1)
            self._velocity[i] += accel_noise * dt
            self._velocity[i] *= 0.98
            self._position[i] += self._velocity[i] * dt

        self._orientation[0] += rng.gauss(0, 0.01)
        self._orientation[1] += rng.gauss(0, 0.01)
        self._orientation[2] += rng.gauss(0, 0.02)

        gnss_quality = rng.choice(["fix", "float", "single", "none"])
        gnss_cov = {
            "fix": 0.01,
            "float": 0.1,
            "single": 1.0,
            "none": 10.0,
        }.get(gnss_quality, 1.0)

        return {
            "position": {
                "lat": 37.7749 + self._position[0] * 0.0001,
                "lon": -122.4194 + self._position[1] * 0.0001,
                "alt_m": 10.0 + self._position[2],
            },
            "velocity": {
                "vx_mps": self._velocity[0],
                "vy_mps": self._velocity[1],
                "vz_mps": self._velocity[2],
            },
            "orientation": {
                "roll": self._orientation[0],
                "pitch": self._orientation[1],
                "yaw": self._orientation[2],
            },
            "angular_rates": {
                "wx": rng.gauss(0, 0.01),
                "wy": rng.gauss(0, 0.01),
                "wz": rng.gauss(0, 0.02),
            },
            "gnss": {
                "quality": gnss_quality,
                "num_satellites": rng.randint(0, 12),
                "hdop": rng.uniform(0.8, 5.0),
                "vdop": rng.uniform(1.0, 8.0),
            },
            "accelerations": {
                "ax": rng.gauss(0, 0.1),
                "ay": rng.gauss(0, 0.1),
                "az": rng.gauss(-9.81, 0.2),
            },
        }

    def _emulate_covariance(
        self, rng: random.Random, degradation_factor: float
    ) -> dict[str, Any]:
        """Emulate position and orientation covariance."""
        pos_var = 1.0 / degradation_factor
        orient_var = 0.01 / degradation_factor
        return {
            "position": {
                "type": "3d",
                "var_x": pos_var,
                "var_y": pos_var,
                "var_z": pos_var * 2,
            },
            "orientation": {
                "type": "3d",
                "var_x": orient_var,
                "var_y": orient_var,
                "var_z": orient_var * 2,
            },
        }


class MultiSensorEmulator:
    """Coordinates multiple sensor emulators for a single platform.

    This class manages a collection of sensor emulators and produces
    synchronized observations that can be fed to the fusion module.
    """

    def __init__(self, platform_id: str, seed: int = 42) -> None:
        self.platform_id = platform_id
        self.seed = seed
        self._emulators: dict[SensorType, SensorEmulatorBase] = {}
        self._frame_index = 0

    def add_emulator(self, emulator: SensorEmulatorBase) -> None:
        """Add a sensor emulator to this platform."""
        self._emulators[emulator.config.sensor_type] = emulator

    def get_emulator(self, sensor_type: SensorType) -> SensorEmulatorBase | None:
        """Get emulator for a specific sensor type."""
        return self._emulators.get(sensor_type)

    def emulate_all(
        self, frame_index: int | None = None
    ) -> list[SensorObservation]:
        """Emulate observations from all sensors."""
        if frame_index is None:
            frame_index = self._frame_index
            self._frame_index += 1

        observations = []
        for emulator in self._emulators.values():
            obs = emulator.emulate(frame_index)
            observations.append(obs)
        return observations

    def emulate_to_events(
        self,
        frame_index: int | None = None,
        source: ContributorSource = ContributorSource.EXTERNAL_FIELD_SENSORS,
    ) -> list[SensorEvent]:
        """Emulate all sensors and convert to fusion bus events."""
        observations = self.emulate_all(frame_index)
        return [obs.to_sensor_event(source=source) for obs in observations]


def create_platform_emulator(
    platform_id: str,
    sensor_types: list[SensorType] | None = None,
    seed: int = 42,
    degradation_mode: DegradationMode = DegradationMode.CLEAR,
    drop_rate: float = 0.05,
) -> MultiSensorEmulator:
    """Create a multi-sensor emulator for a platform.

    Args:
        platform_id: Unique identifier for the platform (drone, ground station, etc.)
        sensor_types: List of sensor types to include. Defaults to all types.
        seed: Random seed for deterministic emulation.
        degradation_mode: Environmental degradation mode.
        drop_rate: Probability of dropping frames.

    Returns:
        Configured MultiSensorEmulator instance.
    """
    if sensor_types is None:
        sensor_types = [
            SensorType.EO_RGB,
            SensorType.IR_THERMAL,
            SensorType.DEPTH_RANGE,
            SensorType.GNSS,
            SensorType.IMU,
        ]

    multi = MultiSensorEmulator(platform_id=platform_id, seed=seed)

    for i, sensor_type in enumerate(sensor_types):
        config = SensorEmulatorConfig(
            sensor_type=sensor_type,
            sensor_id=f"{platform_id}_{sensor_type.value}",
            platform_id=platform_id,
            seed=seed + i,
            degradation_mode=degradation_mode,
            drop_rate=drop_rate,
        )

        if sensor_type in (SensorType.GNSS, SensorType.IMU):
            emulator: SensorEmulatorBase = GNSSIMUEmulator(
                config,
                initial_position=(seed % 10, (seed * 2) % 10, 10.0),
                initial_velocity=(0.5, 0.3, 0.0),
            )
        elif sensor_type == SensorType.EO_RGB:
            emulator = EOCameraEmulator(config)
        elif sensor_type == SensorType.IR_THERMAL:
            emulator = IRThermalEmulator(config)
        elif sensor_type == SensorType.DEPTH_RANGE:
            emulator = DepthRangeEmulator(config)
        else:
            continue

        multi.add_emulator(emulator)

    return multi
