from tac_fuse.local_c2 import LocalC2Authority
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.ray_query import BVHPrimitive, RayQueryStatus
from tac_fuse.replay import generate_scenario
from tac_fuse.rt_control import (
    RTControlUnavailable,
    issue_rt_control_plan,
    plan_rt_control,
)


def _accelerated_status() -> RayQueryStatus:
    return RayQueryStatus(
        backend="rtx",
        available=True,
        accelerated=True,
        reason="test accelerated geometry lane",
    )


def _validation_status() -> RayQueryStatus:
    return RayQueryStatus(
        backend="cpu_parity",
        available=True,
        accelerated=False,
        reason="test validation geometry lane",
    )


def test_accelerated_geometry_controls_each_drone_with_canonical_commands() -> None:
    tracks = generate_scenario(frames=1)[0][:4]
    alpha = tracks[0]
    primitive = BVHPrimitive(
        primitive_id="rf-pocket",
        label="RF Denial",
        lat=alpha.lat,
        lon=alpha.lon,
        radius_m=35.0,
        severity="critical",
    )

    plan = plan_rt_control(
        tracks,
        [primitive],
        runtime_status=_accelerated_status(),
    )

    assert plan.backend == "rtx"
    assert plan.accelerated is True
    assert len(plan.decisions) == 4
    assert plan.commands_by_asset()[alpha.asset_id] == "hold"
    assert set(plan.commands_by_asset().values()) <= {"resume", "patrol", "return", "hold", "abort"}

    alpha_decision = next(item for item in plan.decisions if item.asset_id == alpha.asset_id)
    assert alpha_decision.priority == "critical"
    assert alpha_decision.primitive_id == "rf-pocket"
    assert alpha_decision.accelerated is True
    assert "Accelerated geometry" in alpha_decision.reason


def test_validation_lane_returns_same_decision_shape_without_hardware() -> None:
    track = generate_scenario(frames=1)[0][0]

    plan = plan_rt_control([track], runtime_status=_validation_status())

    assert plan.backend == "cpu_parity"
    assert plan.accelerated is False
    assert len(plan.decisions) == 1
    decision = plan.decisions[0]
    assert decision.command == "resume"
    assert decision.priority == "normal"
    assert decision.to_dict()["asset_id"] == track.asset_id


def test_low_battery_track_returns_before_other_geometry() -> None:
    track = generate_scenario(frames=1)[0][0]
    low_battery_track = track.__class__(
        **{**track.to_dict(), "battery_pct": 39},
    )

    plan = plan_rt_control([low_battery_track], runtime_status=_accelerated_status())

    assert plan.decisions[0].command == "return"
    assert plan.decisions[0].priority == "watch"
    assert plan.decisions[0].accelerated is True


def test_require_accelerated_raises_when_hardware_lane_missing() -> None:
    track = generate_scenario(frames=1)[0][0]

    try:
        plan_rt_control(
            [track],
            runtime_status=RayQueryStatus(
                backend="unavailable",
                available=False,
                accelerated=False,
                reason="no CUDA runtime",
            ),
            require_accelerated=True,
        )
    except RTControlUnavailable as exc:
        assert "no CUDA runtime" in str(exc)
    else:
        raise AssertionError("require_accelerated should fail without accelerated geometry")


def test_rt_control_decisions_persist_through_local_c2_authority() -> None:
    tracks = generate_scenario(frames=1)[0][:2]
    alpha = tracks[0]
    primitive = BVHPrimitive(
        primitive_id="rf-pocket",
        label="RF Denial",
        lat=alpha.lat,
        lon=alpha.lon,
        radius_m=35.0,
        severity="critical",
    )
    plan = plan_rt_control(
        tracks,
        [primitive],
        runtime_status=_accelerated_status(),
    )
    store = MissionStateStore(operator="field_op")
    authority = LocalC2Authority(store)

    receipts = issue_rt_control_plan(authority, plan, include_resume=True)

    assert len(receipts) == 2
    for receipt in receipts:
        proof = store.verify_state_first("operator_task", receipt.task_id)
        assert proof["proof_complete"] is True

    alpha_task = store.get_task(receipts[0].task_id)
    assert alpha_task is not None
    assert alpha_task["metadata"]["control_source"] == "rt_geometry_control"
    assert alpha_task["metadata"]["accelerated"] is True
    assert alpha_task["metadata"]["geometry_backend"] == "rtx"
