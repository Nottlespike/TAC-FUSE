"""TAC-FUSE local-first command and control demo package."""

from tac_fuse.connectivity import (
    ConnectivityController,
    ConnectivityMode,
    create_connectivity_controller,
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
    RouteConflict,
    SeededReplayEngine,
    demo_conflicts,
    generate_scenario,
)

__all__ = [
    "AssetTrack",
    "BVHPrimitive",
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
    "RayQueryResult",
    "RayQueryStatus",
    "RouteConflict",
    "SeededReplayEngine",
    "build_foundry_export",
    "create_connectivity_controller",
    "demo_conflicts",
    "default_primitives",
    "evaluate_bvh",
    "generate_pov_sequence",
    "generate_scenario",
    "inspect_ray_runtime",
    "project_tracks_to_pov",
    "render_svg_pov",
    "write_foundry_artifacts",
    "write_foundry_export",
]
