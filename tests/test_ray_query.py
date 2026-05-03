from tac_fuse.ray_query import BVHPrimitive, evaluate_bvh, inspect_ray_runtime
from tac_fuse.replay import generate_scenario


def test_ray_runtime_falls_back_to_cpu_parity() -> None:
    status = inspect_ray_runtime()

    assert status.available
    assert status.backend in {"rtx", "cpu_parity"}


def test_require_rtx_reports_unavailable_without_hard_failure() -> None:
    status = inspect_ray_runtime(require_rtx=True)

    assert status.backend in {"rtx", "unavailable"}
    assert isinstance(status.reason, str)


def test_bvh_cpu_and_rtx_result_shape_match() -> None:
    track = generate_scenario(frames=1)[0][0]
    primitive = BVHPrimitive(
        primitive_id="near-alpha",
        label="Near Alpha",
        lat=track.lat,
        lon=track.lon,
        radius_m=25.0,
    )

    cpu = evaluate_bvh([track], [primitive], backend="cpu_parity")
    rtx = evaluate_bvh([track], [primitive], backend="rtx")

    assert cpu[0].asset_id == rtx[0].asset_id == track.asset_id
    assert cpu[0].primitive_id == rtx[0].primitive_id == "near-alpha"
    assert cpu[0].backend == "cpu_parity"
    assert rtx[0].backend == "rtx"
    assert rtx[0].latency_ms < cpu[0].latency_ms
