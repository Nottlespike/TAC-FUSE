"""Focused offline tests for the power/latency posture module.

All tests are offline-testable and require no external services.
"""

from __future__ import annotations

import pytest

from tac_fuse.power_posture import (
    WORKLOAD_REGISTRY,
    ComputeTier,
    PowerPosture,
    PowerPostureConfig,
    PowerPostureManager,
    PowerSource,
    WorkloadClass,
)

# ---------------------------------------------------------------------------
# PowerSource enum
# ---------------------------------------------------------------------------

class TestPowerSource:
    def test_battery_value(self):
        assert PowerSource.BATTERY.value == "battery"

    def test_backpack_value(self):
        assert PowerSource.BACKPACK_GENERATOR.value == "backpack_generator"

    def test_ac_mains_value(self):
        assert PowerSource.AC_MAINS.value == "ac_mains"

    def test_from_string(self):
        assert PowerSource("battery") is PowerSource.BATTERY


# ---------------------------------------------------------------------------
# ComputeTier enum
# ---------------------------------------------------------------------------

class TestComputeTier:
    def test_tiers_exist(self):
        assert ComputeTier.FULL.value == "full"
        assert ComputeTier.REDUCED.value == "reduced"
        assert ComputeTier.MINIMAL.value == "minimal"


# ---------------------------------------------------------------------------
# WorkloadClass and registry
# ---------------------------------------------------------------------------

class TestWorkloadRegistry:
    def test_registry_has_core_workloads(self):
        assert "local_c2" in WORKLOAD_REGISTRY
        assert "sensor_fusion" in WORKLOAD_REGISTRY
        assert "alerting" in WORKLOAD_REGISTRY
        assert "fusion_spool" in WORKLOAD_REGISTRY

    def test_registry_has_online_workloads(self):
        # foundry_export is SAFE_OFFLINE because exports are deterministic offline
        # artifacts derived from persisted local state - no network needed.
        # Only enterprise_sync (actual upload) requires ONLINE connectivity.
        assert "foundry_export" in WORKLOAD_REGISTRY
        assert "enterprise_sync" in WORKLOAD_REGISTRY
        assert WORKLOAD_REGISTRY["foundry_export"] == WorkloadClass.SAFE_OFFLINE
        assert WORKLOAD_REGISTRY["enterprise_sync"] == WorkloadClass.REQUIRES_ONLINE

    def test_registry_has_degraded_workloads(self):
        assert "sensor_emulation" in WORKLOAD_REGISTRY
        assert WORKLOAD_REGISTRY["sensor_emulation"] == WorkloadClass.SAFE_DEGRADED

    def test_core_c2_is_offline_safe(self):
        assert WORKLOAD_REGISTRY["local_c2"] == WorkloadClass.SAFE_OFFLINE
        assert WORKLOAD_REGISTRY["alerting"] == WorkloadClass.SAFE_OFFLINE
        assert WORKLOAD_REGISTRY["fusion_spool"] == WorkloadClass.SAFE_OFFLINE


# ---------------------------------------------------------------------------
# PowerPostureConfig defaults
# ---------------------------------------------------------------------------

class TestPowerPostureConfig:
    def test_default_thresholds(self):
        cfg = PowerPostureConfig()
        assert cfg.battery_full_threshold == 80.0
        assert cfg.battery_reduced_threshold == 40.0
        assert cfg.battery_minimal_threshold == 15.0

    def test_custom_thresholds(self):
        cfg = PowerPostureConfig(battery_minimal_threshold=20.0)
        assert cfg.battery_minimal_threshold == 20.0


# ---------------------------------------------------------------------------
# PowerPostureManager — basic operations
# ---------------------------------------------------------------------------

class TestPowerPostureManagerBasic:
    def test_default_state(self):
        mgr = PowerPostureManager()
        assert mgr.power_source == PowerSource.BATTERY
        assert mgr.battery_pct == 100.0
        assert mgr.connectivity_mode == "offline"

    def test_update_battery_clamps_high(self):
        mgr = PowerPostureManager()
        mgr.update_battery(150.0)
        assert mgr.battery_pct == 100.0

    def test_update_battery_clamps_low(self):
        mgr = PowerPostureManager()
        mgr.update_battery(-5.0)
        assert mgr.battery_pct == 0.0

    def test_update_power_source_string(self):
        mgr = PowerPostureManager()
        mgr.update_power_source("ac_mains")
        assert mgr.power_source == PowerSource.AC_MAINS

    def test_update_power_source_enum(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.BACKPACK_GENERATOR)
        assert mgr.power_source == PowerSource.BACKPACK_GENERATOR

    def test_update_cpu_load_clamps(self):
        mgr = PowerPostureManager()
        mgr.update_cpu_load(200.0)
        assert mgr.cpu_load == 100.0

    def test_update_connectivity(self):
        mgr = PowerPostureManager()
        mgr.update_connectivity("online")
        assert mgr.connectivity_mode == "online"


# ---------------------------------------------------------------------------
# Compute tier computation
# ---------------------------------------------------------------------------

class TestComputeTierComputation:
    def test_full_battery_full_tier(self):
        mgr = PowerPostureManager()
        mgr.update_battery(95.0)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.FULL

    def test_medium_battery_full_tier(self):
        mgr = PowerPostureManager()
        mgr.update_battery(50.0)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.FULL

    def test_low_battery_minimal_tier(self):
        mgr = PowerPostureManager()
        mgr.update_battery(10.0)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.MINIMAL

    def test_high_cpu_reduces_tier(self):
        mgr = PowerPostureManager()
        mgr.update_battery(95.0)
        mgr.update_cpu_load(90.0)
        assert mgr.compute_tier() == ComputeTier.REDUCED

    def test_ac_mains_full_tier(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.AC_MAINS)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.FULL

    def test_ac_mains_hot_cpu_reduces(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.AC_MAINS)
        mgr.update_cpu_load(90.0)
        assert mgr.compute_tier() == ComputeTier.REDUCED

    def test_backpack_generator_full_tier(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.BACKPACK_GENERATOR)
        mgr.update_battery(80.0)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.FULL

    def test_backpack_low_battery_minimal(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.BACKPACK_GENERATOR)
        mgr.update_battery(5.0)
        assert mgr.compute_tier() == ComputeTier.MINIMAL

    def test_boundary_at_reduced_threshold(self):
        mgr = PowerPostureManager()
        mgr.update_battery(40.0)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.REDUCED

    def test_boundary_just_above_reduced(self):
        mgr = PowerPostureManager()
        mgr.update_battery(41.0)
        mgr.update_cpu_load(30.0)
        assert mgr.compute_tier() == ComputeTier.FULL

    def test_custom_thresholds(self):
        cfg = PowerPostureConfig(battery_reduced_threshold=60.0)
        mgr = PowerPostureManager(cfg)
        mgr.update_battery(55.0)
        assert mgr.compute_tier() == ComputeTier.REDUCED


# ---------------------------------------------------------------------------
# Thermal headroom
# ---------------------------------------------------------------------------

class TestThermalHeadroom:
    def test_nominal(self):
        mgr = PowerPostureManager()
        mgr.update_cpu_load(30.0)
        assert mgr.thermal_headroom() == "nominal"

    def test_warm(self):
        mgr = PowerPostureManager()
        mgr.update_cpu_load(70.0)
        assert mgr.thermal_headroom() == "warm"

    def test_hot(self):
        mgr = PowerPostureManager()
        mgr.update_cpu_load(90.0)
        assert mgr.thermal_headroom() == "hot"


# ---------------------------------------------------------------------------
# Runtime estimation
# ---------------------------------------------------------------------------

class TestRuntimeEstimation:
    def test_battery_full_runtime(self):
        mgr = PowerPostureManager()
        mgr.update_battery(100.0)
        runtime = mgr.estimated_runtime_min()
        assert runtime == pytest.approx(180.0, abs=1.0)

    def test_battery_half_runtime(self):
        mgr = PowerPostureManager()
        mgr.update_battery(50.0)
        runtime = mgr.estimated_runtime_min()
        assert runtime == pytest.approx(90.0, abs=1.0)

    def test_battery_zero_runtime(self):
        mgr = PowerPostureManager()
        mgr.update_battery(0.0)
        assert mgr.estimated_runtime_min() == 0.0

    def test_ac_mains_infinite(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.AC_MAINS)
        assert mgr.estimated_runtime_min() == float("inf")

    def test_backpack_extended(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.BACKPACK_GENERATOR)
        assert mgr.estimated_runtime_min() == 360.0


# ---------------------------------------------------------------------------
# Full posture snapshot
# ---------------------------------------------------------------------------

class TestPowerPostureSnapshot:
    def test_posture_is_dataclass(self):
        mgr = PowerPostureManager()
        posture = mgr.get_posture()
        assert isinstance(posture, PowerPosture)

    def test_posture_to_dict(self):
        mgr = PowerPostureManager()
        posture = mgr.get_posture()
        d = posture.to_dict()
        assert "power_source" in d
        assert "battery_pct" in d
        assert "compute_tier" in d
        assert "safe_workloads" in d
        assert "restricted_workloads" in d
        assert "notes" in d

    def test_offline_c2_always_safe_when_not_minimal(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        mgr.update_connectivity("offline")
        posture = mgr.get_posture()
        assert "local_c2" in posture.safe_workloads
        assert "sensor_fusion" in posture.safe_workloads
        assert "alerting" in posture.safe_workloads

    def test_enterprise_sync_blocked_when_offline(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        mgr.update_connectivity("offline")
        posture = mgr.get_posture()
        assert "foundry_export" in posture.safe_workloads
        assert "enterprise_sync" in posture.restricted_workloads

    def test_online_workloads_safe_when_online(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        mgr.update_connectivity("online")
        posture = mgr.get_posture()
        assert "foundry_export" in posture.safe_workloads
        assert "enterprise_sync" in posture.safe_workloads

    def test_minimal_tier_restricts_degraded_workloads(self):
        mgr = PowerPostureManager()
        mgr.update_battery(5.0)
        mgr.update_connectivity("offline")
        posture = mgr.get_posture()
        assert posture.compute_tier == "minimal"
        # C2 essentials should still be safe
        assert "local_c2" in posture.safe_workloads
        assert "alerting" in posture.safe_workloads
        assert "fusion_spool" in posture.safe_workloads
        # Degraded workloads restricted
        assert "sensor_emulation" in posture.restricted_workloads

    def test_offline_safe_list_always_populated(self):
        mgr = PowerPostureManager()
        posture = mgr.get_posture()
        assert len(posture.offline_safe_workloads) > 0
        assert "local_c2" in posture.offline_safe_workloads


# ---------------------------------------------------------------------------
# Workload safety check
# ---------------------------------------------------------------------------

class TestWorkloadSafetyCheck:
    def test_safe_workload_returns_true(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        mgr.update_connectivity("offline")
        assert mgr.is_workload_safe("local_c2") is True

    def test_online_workload_returns_false_offline(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        mgr.update_connectivity("offline")
        assert mgr.is_workload_safe("enterprise_sync") is False

    def test_online_workload_returns_true_online(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        mgr.update_connectivity("online")
        assert mgr.is_workload_safe("enterprise_sync") is True

    def test_unknown_workload_returns_false(self):
        mgr = PowerPostureManager()
        assert mgr.is_workload_safe("nonexistent_workload") is False


# ---------------------------------------------------------------------------
# Runbook summary
# ---------------------------------------------------------------------------

class TestRunbookSummary:
    def test_summary_contains_header(self):
        mgr = PowerPostureManager()
        summary = mgr.get_runbook_summary()
        assert "TAC-FUSE Power/Latency Posture" in summary

    def test_summary_contains_power_source(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.BATTERY)
        summary = mgr.get_runbook_summary()
        assert "battery" in summary

    def test_summary_contains_workloads(self):
        mgr = PowerPostureManager()
        mgr.update_battery(90.0)
        summary = mgr.get_runbook_summary()
        assert "local_c2" in summary

    def test_summary_contains_notes(self):
        mgr = PowerPostureManager()
        mgr.update_connectivity("offline")
        summary = mgr.get_runbook_summary()
        assert "OFFLINE" in summary


# ---------------------------------------------------------------------------
# Posture notes generation
# ---------------------------------------------------------------------------

class TestPostureNotes:
    def test_battery_note_includes_runtime(self):
        mgr = PowerPostureManager()
        mgr.update_battery(80.0)
        posture = mgr.get_posture()
        battery_notes = [n for n in posture.notes if "Battery" in n or "BATTERY" in n]
        assert len(battery_notes) > 0
        assert "min" in battery_notes[0]

    def test_critical_battery_note(self):
        mgr = PowerPostureManager()
        mgr.update_battery(8.0)
        posture = mgr.get_posture()
        critical_notes = [n for n in posture.notes if "BATTERY CRITICAL" in n]
        assert len(critical_notes) > 0

    def test_low_battery_note(self):
        mgr = PowerPostureManager()
        mgr.update_battery(25.0)
        posture = mgr.get_posture()
        low_notes = [n for n in posture.notes if "BATTERY LOW" in n]
        assert len(low_notes) > 0

    def test_ac_mains_note(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.AC_MAINS)
        posture = mgr.get_posture()
        assert any("AC mains" in n for n in posture.notes)

    def test_backpack_note(self):
        mgr = PowerPostureManager()
        mgr.update_power_source(PowerSource.BACKPACK_GENERATOR)
        posture = mgr.get_posture()
        assert any("Backpack" in n for n in posture.notes)

    def test_offline_note(self):
        mgr = PowerPostureManager()
        mgr.update_connectivity("offline")
        posture = mgr.get_posture()
        assert any("OFFLINE" in n for n in posture.notes)

    def test_degraded_note(self):
        mgr = PowerPostureManager()
        mgr.update_connectivity("degraded")
        posture = mgr.get_posture()
        assert any("DEGRADED" in n for n in posture.notes)

    def test_minimal_tier_note(self):
        mgr = PowerPostureManager()
        mgr.update_battery(5.0)
        posture = mgr.get_posture()
        assert any("MINIMAL compute" in n for n in posture.notes)

    def test_reduced_tier_note(self):
        mgr = PowerPostureManager()
        mgr.update_battery(30.0)
        posture = mgr.get_posture()
        assert any("REDUCED compute" in n for n in posture.notes)

    def test_cpu_fallback_note(self):
        mgr = PowerPostureManager()
        posture = mgr.get_posture()
        assert any("CPU fallback" in n for n in posture.notes)

    def test_thermal_throttle_note(self):
        mgr = PowerPostureManager()
        mgr.update_cpu_load(90.0)
        posture = mgr.get_posture()
        assert any("Thermal throttle" in n for n in posture.notes)
