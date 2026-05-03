"""Laptop/backpack power and latency posture for TAC-FUSE.

This module makes the fusion node's own power and compute constraints
visible to the operator and runbook.  It answers:

- How long can the laptop keep running on its current power source?
- What workloads are safe to run given the current battery/thermal state?
- What compute tier is available (full / reduced / minimal)?
- Which workloads are safe during denied connectivity?

The module is purely computational and does **not** require:
- Foundry/Maven connectivity
- Intel NPU or object detection models
- Internet access or Hugging Face downloads
- Real hardware polling (posture is operator-reported or estimated)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PowerSource(Enum):
    """Fusion node power source."""

    BATTERY = "battery"
    BACKPACK_GENERATOR = "backpack_generator"
    AC_MAINS = "ac_mains"
    UNKNOWN = "unknown"


class ComputeTier(Enum):
    """Available compute tier based on power and thermal constraints.

    FULL:      No constraints — all local workloads safe.
    REDUCED:   Thermal or battery throttle — avoid heavy batch workloads.
    MINIMAL:   Critical only — restrict to C2, spool, and alerting.
    """

    FULL = "full"
    REDUCED = "reduced"
    MINIMAL = "minimal"


class WorkloadClass(Enum):
    """Classification of local workloads for gating.

    SAFE_OFFLINE:      Runs in any connectivity mode with minimal CPU.
    SAFE_DEGRADED:     Needs moderate CPU; safe while disconnected but
                       not during minimal-compute posture.
    REQUIRES_ONLINE:   Needs enterprise sync to be useful (export/upload).
    """

    SAFE_OFFLINE = "safe_offline"
    SAFE_DEGRADED = "safe_degraded"
    REQUIRES_ONLINE = "requires_online"


# Canonical workload registry — operator-facing labels for what is safe
# NOTE: foundry_export is SAFE_OFFLINE because exports are deterministic
# offline artifacts derived from persisted local state. Only enterprise_sync
# (actual upload to Foundry/Maven) requires ONLINE connectivity.
WORKLOAD_REGISTRY: dict[str, WorkloadClass] = {
    "local_c2": WorkloadClass.SAFE_OFFLINE,
    "sensor_fusion": WorkloadClass.SAFE_OFFLINE,
    "alerting": WorkloadClass.SAFE_OFFLINE,
    "fusion_spool": WorkloadClass.SAFE_OFFLINE,
    "collision_bvh": WorkloadClass.SAFE_OFFLINE,
    "drone_tasking": WorkloadClass.SAFE_OFFLINE,
    "foundry_export": WorkloadClass.SAFE_OFFLINE,  # Export from local state works offline
    "sensor_emulation": WorkloadClass.SAFE_DEGRADED,
    "terrain_mesh": WorkloadClass.SAFE_DEGRADED,
    "earth_aoi_cache": WorkloadClass.SAFE_DEGRADED,
    "enterprise_sync": WorkloadClass.REQUIRES_ONLINE,  # Upload requires ONLINE
}

# Latency budget per compute tier (milliseconds)
# At FULL tier, local work should complete within 100 ms.
# At REDUCED tier, thermal throttle allows up to 500 ms.
# At MINIMAL tier, only critical work runs with generous budget.
LATENCY_BUDGET_MS: dict[ComputeTier, float] = {
    ComputeTier.FULL: 100.0,
    ComputeTier.REDUCED: 500.0,
    ComputeTier.MINIMAL: 1000.0,
}

# Rationale for workload safety during denied connectivity
DENIED_CONNECTIVITY_RATIONALE: dict[str, str] = {
    "local_c2": "State persists locally; no enterprise dependency",
    "sensor_fusion": "Fuses local feeds; works without network",
    "alerting": "Local alert rules; no upload needed",
    "fusion_spool": "Append-only local log; offline by design",
    "collision_bvh": "Local spatial queries; no network needed",
    "drone_tasking": "Commands issued locally; queued for sync",
    "foundry_export": "Deterministic export from local state",
    "sensor_emulation": "Local compute emulation; no network needed",
    "terrain_mesh": "Local terrain data; cached locally",
    "earth_aoi_cache": "Cached imagery; works offline",
    "enterprise_sync": "Requires network upload to Foundry/Maven",
}


@dataclass
class LatencyBudget:
    """Per-tier latency budget for local workloads.

    Makes the fusion node's processing latency constraints visible
    so the operator understands whether local workloads complete
    within acceptable time bounds.
    """

    compute_tier: str
    local_budget_ms: float
    feed_latency_avg_ms: float
    budget_remaining_ms: float
    over_budget: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class DeniedConnectivityGuide:
    """Operator decision guide for denied-connectivity operations.

    Explicitly lists what is safe and restricted when the fusion
    node has no enterprise connectivity, with rationale and
    recommended operator actions.
    """

    safe_workloads: list[str]
    safe_rationale: dict[str, str]
    restricted_workloads: list[str]
    restricted_rationale: dict[str, str]
    operator_actions: list[str]


@dataclass
class BatteryAssumption:
    """Documented assumptions behind battery and runtime estimates.

    Makes the power model transparent so operators can adjust
    PowerPostureConfig for their specific deployment hardware.
    """

    laptop_battery_wh: float
    avg_power_draw_w: float
    drain_rate_pct_per_min: float
    backpack_output_w: float
    backpack_fuel_runtime_min: float
    ac_mains_infinite: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class PowerPosture:
    """Snapshot of the fusion node's power and compute posture.

    This is the operator-visible summary.  Fields are deliberately
    human-readable so the UI can render them without transformation.
    """

    power_source: str
    battery_pct: float
    estimated_runtime_min: float
    compute_tier: str
    thermal_headroom: str  # "nominal" | "warm" | "hot"
    connectivity_mode: str
    safe_workloads: list[str]
    restricted_workloads: list[str]
    offline_safe_workloads: list[str]
    cpu_fallback: bool
    latency_budget_ms: float
    feed_latency_avg_ms: float
    battery_assumption: str  # summary of assumptions
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PowerPostureConfig:
    """Configuration for posture estimation.

    All thresholds are tunable for different deployment scenarios.
    """

    # Battery thresholds (percentage)
    battery_full_threshold: float = 80.0
    battery_reduced_threshold: float = 40.0
    battery_minimal_threshold: float = 15.0

    # Runtime estimates (minutes) at different power sources
    battery_full_runtime_min: float = 180.0
    battery_reduced_runtime_min: float = 90.0
    backpack_runtime_min: float = 360.0
    ac_mains_runtime_min: float = float("inf")

    # CPU load thresholds for thermal estimation
    cpu_load_nominal_threshold: float = 60.0
    cpu_load_warm_threshold: float = 85.0

    # Power draw rates (percentage per minute) for runtime estimation
    battery_drain_rate_full: float = 100.0 / 180.0  # ~0.56%/min
    backpack_drain_rate: float = 0.0  # assumed infinite while running


class PowerPostureManager:
    """Manage the fusion node's power and latency posture.

    This is a lightweight, offline-first manager.  The operator or an
    external telemetry feed updates power state; the manager computes
    what workloads are safe and produces an operator-visible summary.

    Typical usage::

        mgr = PowerPostureManager()
        mgr.update_battery(72.0)
        mgr.update_connectivity("offline")
        posture = mgr.get_posture()
    """

    def __init__(self, config: PowerPostureConfig | None = None) -> None:
        self.config = config or PowerPostureConfig()
        self._power_source: PowerSource = PowerSource.BATTERY
        self._battery_pct: float = 100.0
        self._cpu_load_pct: float = 30.0
        self._connectivity_mode: str = "offline"
        self._cpu_fallback: bool = True  # CPU always available

    # -- Mutators (operator or telemetry input) --

    def update_power_source(self, source: PowerSource | str) -> None:
        """Set the current power source."""
        if isinstance(source, str):
            source = PowerSource(source)
        self._power_source = source

    def update_battery(self, pct: float) -> None:
        """Update battery percentage (0–100)."""
        self._battery_pct = max(0.0, min(100.0, pct))

    def update_cpu_load(self, pct: float) -> None:
        """Update estimated CPU load percentage (0–100)."""
        self._cpu_load_pct = max(0.0, min(100.0, pct))

    def update_connectivity(self, mode: str) -> None:
        """Update the current connectivity mode (offline/degraded/online)."""
        self._connectivity_mode = mode

    # -- Accessors --

    @property
    def power_source(self) -> PowerSource:
        return self._power_source

    @property
    def battery_pct(self) -> float:
        return self._battery_pct

    @property
    def cpu_load(self) -> float:
        return self._cpu_load_pct

    @property
    def connectivity_mode(self) -> str:
        return self._connectivity_mode

    # -- Posture computation --

    def compute_tier(self) -> ComputeTier:
        """Determine the current compute tier based on power and thermal state."""
        if self._power_source == PowerSource.AC_MAINS:
            # AC mains: only thermal can reduce tier
            if self._cpu_load_pct >= self.config.cpu_load_warm_threshold:
                return ComputeTier.REDUCED
            return ComputeTier.FULL

        if self._power_source == PowerSource.BACKPACK_GENERATOR:
            # Backpack: generous power but thermal matters
            if self._cpu_load_pct >= self.config.cpu_load_warm_threshold:
                return ComputeTier.REDUCED
            if self._battery_pct < self.config.battery_minimal_threshold:
                return ComputeTier.MINIMAL
            return ComputeTier.FULL

        # Battery: both battery level and thermal matter
        if self._battery_pct < self.config.battery_minimal_threshold:
            return ComputeTier.MINIMAL
        if self._battery_pct <= self.config.battery_reduced_threshold:
            return ComputeTier.REDUCED
        if self._cpu_load_pct >= self.config.cpu_load_warm_threshold:
            return ComputeTier.REDUCED
        return ComputeTier.FULL

    def thermal_headroom(self) -> str:
        """Classify thermal headroom as nominal / warm / hot."""
        if self._cpu_load_pct >= self.config.cpu_load_warm_threshold:
            return "hot"
        if self._cpu_load_pct >= self.config.cpu_load_nominal_threshold:
            return "warm"
        return "nominal"

    def estimated_runtime_min(self) -> float:
        """Estimate remaining runtime in minutes."""
        if self._power_source == PowerSource.AC_MAINS:
            return self.config.ac_mains_runtime_min
        if self._power_source == PowerSource.BACKPACK_GENERATOR:
            # Backpack assumed running; battery is backup
            return self.config.backpack_runtime_min

        # Battery: linear estimate
        if self._battery_pct <= 0:
            return 0.0
        return self._battery_pct / self.config.battery_drain_rate_full

    def _classify_workloads(
        self, tier: ComputeTier
    ) -> tuple[list[str], list[str], list[str]]:
        """Classify workloads into safe / restricted / offline-safe lists."""
        safe: list[str] = []
        restricted: list[str] = []
        offline_safe: list[str] = []

        for name, workload_class in WORKLOAD_REGISTRY.items():
            # Offline-safe workloads always listed
            if workload_class == WorkloadClass.SAFE_OFFLINE:
                offline_safe.append(name)

            # Determine if safe under current tier and connectivity
            is_safe = False
            if workload_class == WorkloadClass.SAFE_OFFLINE:
                is_safe = tier != ComputeTier.MINIMAL or name in (
                    "local_c2",
                    "fusion_spool",
                    "alerting",
                )
            elif workload_class == WorkloadClass.SAFE_DEGRADED:
                is_safe = tier == ComputeTier.FULL
            elif workload_class == WorkloadClass.REQUIRES_ONLINE:
                is_safe = (
                    self._connectivity_mode == "online"
                    and tier != ComputeTier.MINIMAL
                )

            if is_safe:
                safe.append(name)
            else:
                restricted.append(name)

        return safe, restricted, offline_safe

    def get_posture(self) -> PowerPosture:
        """Compute and return the current power/latency posture snapshot."""
        tier = self.compute_tier()
        safe, restricted, offline_safe = self._classify_workloads(tier)
        latency_budget = self.get_latency_budget()

        notes = self._generate_notes(tier)

        return PowerPosture(
            power_source=self._power_source.value,
            battery_pct=round(self._battery_pct, 1),
            estimated_runtime_min=round(self.estimated_runtime_min(), 1),
            compute_tier=tier.value,
            thermal_headroom=self.thermal_headroom(),
            connectivity_mode=self._connectivity_mode,
            safe_workloads=safe,
            restricted_workloads=restricted,
            offline_safe_workloads=offline_safe,
            cpu_fallback=self._cpu_fallback,
            latency_budget_ms=latency_budget.local_budget_ms,
            feed_latency_avg_ms=latency_budget.feed_latency_avg_ms,
            battery_assumption=self._battery_assumption_summary(),
            notes=notes,
        )

    def _generate_notes(self, tier: ComputeTier) -> list[str]:
        """Generate operator-facing posture notes."""
        notes: list[str] = []

        if self._power_source == PowerSource.BATTERY:
            runtime = self.estimated_runtime_min()
            if runtime < 30:
                notes.append(
                    f"BATTERY CRITICAL: ~{runtime:.0f} min remaining — "
                    "switch to backpack or AC immediately"
                )
            elif runtime < 60:
                notes.append(
                    f"BATTERY LOW: ~{runtime:.0f} min remaining — "
                    "prepare alternate power"
                )
            else:
                notes.append(f"Battery: ~{runtime:.0f} min estimated runtime")
        elif self._power_source == PowerSource.BACKPACK_GENERATOR:
            notes.append("Backpack generator active — extended runtime available")
        elif self._power_source == PowerSource.AC_MAINS:
            notes.append("AC mains power — no runtime constraint")

        if tier == ComputeTier.MINIMAL:
            notes.append(
                "MINIMAL compute: only C2, spool, and alerting active"
            )
        elif tier == ComputeTier.REDUCED:
            notes.append(
                "REDUCED compute: heavy batch workloads paused"
            )

        if self.thermal_headroom() == "hot":
            notes.append("Thermal throttle: CPU load elevated, expect reduced throughput")

        if self._connectivity_mode == "offline":
            notes.append("OFFLINE: all enterprise sync blocked, local C2 is authority")
        elif self._connectivity_mode == "degraded":
            notes.append("DEGRADED: sync queued, awaiting connectivity for upload")

        if self._cpu_fallback:
            notes.append("CPU fallback available for all compute tasks")

        return notes

    def is_workload_safe(self, workload_name: str) -> bool:
        """Check if a specific workload is safe to run under current posture."""
        tier = self.compute_tier()
        safe, _, _ = self._classify_workloads(tier)
        return workload_name in safe

    def get_latency_budget(
        self, feed_latency_avg_ms: float = 50.0
    ) -> LatencyBudget:
        """Compute the latency budget for local workloads.

        Parameters
        ----------
        feed_latency_avg_ms : float
            Average contributor feed latency in milliseconds.  Defaults
            to 50 ms (typical local RF link).  The operator or telemetry
            feed provides this value; it is not measured by this module.
        """
        tier = self.compute_tier()
        local_budget = LATENCY_BUDGET_MS[tier]
        remaining = max(0.0, local_budget - feed_latency_avg_ms)
        over = remaining <= 0

        notes: list[str] = []
        if over:
            notes.append(
                f"Feed latency ({feed_latency_avg_ms:.0f} ms) exceeds "
                f"{tier.value}-tier budget ({local_budget:.0f} ms)"
            )
        if tier == ComputeTier.REDUCED:
            notes.append("Reduced tier: thermal throttle increases processing latency")
        elif tier == ComputeTier.MINIMAL:
            notes.append("Minimal tier: only critical workloads with generous budget")

        return LatencyBudget(
            compute_tier=tier.value,
            local_budget_ms=local_budget,
            feed_latency_avg_ms=feed_latency_avg_ms,
            budget_remaining_ms=round(remaining, 1),
            over_budget=over,
            notes=notes,
        )

    def get_denied_connectivity_guide(self) -> DeniedConnectivityGuide:
        """Build an operator decision guide for denied-connectivity ops.

        This guide is intended for the operator runbook and the UI.
        It answers: "What can I safely do when I have no enterprise
        connectivity?"
        """
        tier = self.compute_tier()
        safe, restricted, _ = self._classify_workloads(tier)

        safe_rationale = {
            name: DENIED_CONNECTIVITY_RATIONALE.get(name, "Safe during denied connectivity")
            for name in safe
        }
        restricted_rationale = {
            name: DENIED_CONNECTIVITY_RATIONALE.get(name, "Restricted during denied connectivity")
            for name in restricted
        }

        actions: list[str] = []
        if "enterprise_sync" in restricted:
            actions.append("Sync queue holds staged commands for later upload")
        if tier == ComputeTier.MINIMAL:
            actions.append("Switch to backpack or AC to restore compute tier")
            actions.append("Only C2, spool, and alerting remain active")
        elif tier == ComputeTier.REDUCED:
            actions.append("Heavy batch workloads paused; C2 and fusion active")
        if self._connectivity_mode == "offline":
            actions.append("Local C2 is the authority; all drone commands are local")
        if "sensor_emulation" in restricted:
            actions.append("Sensor emulation paused to conserve compute")

        return DeniedConnectivityGuide(
            safe_workloads=safe,
            safe_rationale=safe_rationale,
            restricted_workloads=restricted,
            restricted_rationale=restricted_rationale,
            operator_actions=actions,
        )

    def get_battery_assumption(self) -> BatteryAssumption:
        """Return the documented assumptions behind runtime estimates.

        These values match PowerPostureConfig defaults and are
        operator-visible so they can tune the model for their
        specific hardware (laptop model, backpack generator capacity).
        """
        cfg = self.config
        notes: list[str] = []
        notes.append(
            f"Drain rate: {cfg.battery_drain_rate_full:.4f} %/min "
            f"({cfg.battery_full_runtime_min:.0f} min at 100%)"
        )
        if self._power_source == PowerSource.BATTERY:
            remaining = self.estimated_runtime_min()
            if remaining < 30:
                notes.append("URGENT: Switch to backpack generator or AC mains")
            elif remaining < 60:
                notes.append("Prepare alternate power source")
        if self._power_source == PowerSource.BACKPACK_GENERATOR:
            notes.append("Backpack assumed running with infinite fuel during mission")
        if self._power_source == PowerSource.AC_MAINS:
            notes.append("AC mains: no runtime constraint assumed")

        return BatteryAssumption(
            laptop_battery_wh=56.0,  # typical 14" laptop
            avg_power_draw_w=56.0 / 3.0,  # ~18.7 W
            drain_rate_pct_per_min=cfg.battery_drain_rate_full,
            backpack_output_w=65.0,  # typical portable generator
            backpack_fuel_runtime_min=cfg.backpack_runtime_min,
            ac_mains_infinite=True,
            notes=notes,
        )

    def _battery_assumption_summary(self) -> str:
        """Short summary of battery assumptions for the posture snapshot."""
        ba = self.get_battery_assumption()
        return (
            f"{ba.laptop_battery_wh:.0f} Wh · "
            f"{ba.drain_rate_pct_per_min:.3f} %/min · "
            f"backpack {ba.backpack_output_w:.0f} W"
        )

    def get_runbook_summary(self) -> str:
        """Generate a runbook-visible text summary of the current posture."""
        posture = self.get_posture()
        latency = self.get_latency_budget()
        guide = self.get_denied_connectivity_guide()
        battery = self.get_battery_assumption()
        lines = [
            "=== TAC-FUSE Power/Latency Posture ===",
            f"Power source:   {posture.power_source}",
            f"Battery:        {posture.battery_pct}%",
            f"Runtime:        {posture.estimated_runtime_min} min",
            f"Compute tier:   {posture.compute_tier}",
            f"Thermal:        {posture.thermal_headroom}",
            f"Connectivity:   {posture.connectivity_mode}",
            f"CPU fallback:   {'yes' if posture.cpu_fallback else 'no'}",
            f"Latency budget: {latency.local_budget_ms:.0f} ms "
            f"(feed avg {latency.feed_latency_avg_ms:.0f} ms, "
            f"remaining {latency.budget_remaining_ms:.0f} ms)",
            f"Battery model:  {posture.battery_assumption}",
            "",
            "Safe workloads:",
        ]
        for w in posture.safe_workloads:
            lines.append(f"  - {w}")
        if posture.restricted_workloads:
            lines.append("")
            lines.append("Restricted workloads:")
            for w in posture.restricted_workloads:
                lines.append(f"  - {w}")
        lines.append("")
        lines.append("Denied connectivity guide:")
        lines.append("  Safe:")
        for w in guide.safe_workloads:
            rationale = guide.safe_rationale.get(w, "")
            lines.append(f"    - {w}: {rationale}")
        if guide.restricted_workloads:
            lines.append("  Restricted:")
            for w in guide.restricted_workloads:
                rationale = guide.restricted_rationale.get(w, "")
                lines.append(f"    - {w}: {rationale}")
        if guide.operator_actions:
            lines.append("  Operator actions:")
            for action in guide.operator_actions:
                lines.append(f"    - {action}")
        lines.append("")
        lines.append("Battery assumptions:")
        lines.append(f"  Laptop battery:     {battery.laptop_battery_wh:.0f} Wh")
        lines.append(f"  Avg power draw:     {battery.avg_power_draw_w:.1f} W")
        lines.append(f"  Drain rate:         {battery.drain_rate_pct_per_min:.4f} %/min")
        lines.append(f"  Backpack output:    {battery.backpack_output_w:.0f} W")
        lines.append(f"  Backpack runtime:   {battery.backpack_fuel_runtime_min:.0f} min")
        for note in battery.notes:
            lines.append(f"  - {note}")
        if posture.notes:
            lines.append("")
            lines.append("Notes:")
            for note in posture.notes:
                lines.append(f"  - {note}")
        lines.append("=== End Posture ===")
        return "\n".join(lines)
