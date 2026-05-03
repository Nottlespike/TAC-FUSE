"""TAC-FUSE local-first command and control demo package."""

from tac_fuse.connectivity import (
    ConnectivityController,
    ConnectivityMode,
    create_connectivity_controller,
)
from tac_fuse.foundry import (
    SyncBoundaryViolation,
    assert_sync_allowed,
    can_upload,
    has_upload_credentials,
)
from tac_fuse.foundry_export import (
    build_foundry_export,
    write_foundry_artifacts,
    write_foundry_export,
)
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.npu_siglip import (
    FIELD_CONDITION_LABELS,
    MODEL_ID,
    FieldConditionResult,
    FieldConditionScore,
    IntelNPUSigLIP2Adapter,
    NPUStatus,
)
from tac_fuse.pov import (
    DronePOVFrame,
    POVObject,
    generate_pov_sequence,
    project_tracks_to_pov,
    render_svg_pov,
)
from tac_fuse.power_posture import (
    WORKLOAD_REGISTRY,
    ComputeTier,
    PowerPosture,
    PowerPostureConfig,
    PowerPostureManager,
    PowerSource,
    WorkloadClass,
)
from tac_fuse.ray_query import (
    BVHPrimitive,
    RayQueryResult,
    RayQueryStatus,
    default_primitives,
    evaluate_bvh,
    inspect_ray_runtime,
)
from tac_fuse.replay import (
    AssetTrack,
    RestrictedEntry,
    RouteConflict,
    SeededReplayEngine,
    demo_conflicts,
    demo_restricted_entries,
    generate_scenario,
)

__all__ = [
    "AssetTrack",
    "BVHPrimitive",
    "ComputeTier",
    "ConnectivityController",
    "ConnectivityMode",
    "DronePOVFrame",
    "FIELD_CONDITION_LABELS",
    "FieldConditionResult",
    "FieldConditionScore",
    "IntelNPUSigLIP2Adapter",
    "MODEL_ID",
    "MissionStateStore",
    "NPUStatus",
    "POVObject",
    "PowerPosture",
    "PowerPostureConfig",
    "PowerPostureManager",
    "PowerSource",
    "RayQueryResult",
    "RayQueryStatus",
    "RestrictedEntry",
    "RouteConflict",
    "SeededReplayEngine",
    "SyncBoundaryViolation",
    "WORKLOAD_REGISTRY",
    "WorkloadClass",
    "assert_sync_allowed",
    "build_foundry_export",
    "can_upload",
    "create_connectivity_controller",
    "demo_conflicts",
    "demo_restricted_entries",
    "default_primitives",
    "evaluate_bvh",
    "generate_pov_sequence",
    "generate_scenario",
    "has_upload_credentials",
    "inspect_ray_runtime",
    "project_tracks_to_pov",
    "render_svg_pov",
    "write_foundry_artifacts",
    "write_foundry_export",
]
