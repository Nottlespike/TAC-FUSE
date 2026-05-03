"""Deterministic sensor emulation for field conditions.

This package provides sensor emulators that generate deterministic observations
for EO/RGB cameras, IR/thermal sensors, depth/range sensors, and GNSS/IMU state.
Each emulator supports configurable degradation effects and produces observations
with covariance/uncertainty metadata suitable for sensor fusion.

Example usage::

    from tac_fuse.sensors import (
        create_platform_emulator,
        SensorType,
        DegradationMode,
    )

    # Create emulator for a drone platform
    emulator = create_platform_emulator(
        platform_id="drone_001",
        degradation_mode=DegradationMode.HAZE,
        drop_rate=0.05,
    )

    # Generate observations for frame 0
    observations = emulator.emulate_all(frame_index=0)

    # Convert to fusion bus events
    events = emulator.emulate_to_events(frame_index=0)
"""

from tac_fuse.sensors.models import (
    Covariance2D,
    Covariance3D,
    DegradationMode,
    DepthRangeEmulator,
    EOCameraEmulator,
    GNSSIMUEmulator,
    IRThermalEmulator,
    MultiSensorEmulator,
    SensorEmulatorBase,
    SensorEmulatorConfig,
    SensorObservation,
    SensorType,
    create_platform_emulator,
)

__all__ = [
    "Covariance2D",
    "Covariance3D",
    "DegradationMode",
    "DepthRangeEmulator",
    "EOCameraEmulator",
    "GNSSIMUEmulator",
    "IRThermalEmulator",
    "MultiSensorEmulator",
    "SensorEmulatorBase",
    "SensorEmulatorConfig",
    "SensorObservation",
    "SensorType",
    "create_platform_emulator",
]
