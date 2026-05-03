import subprocess

from tac_fuse import ray_query
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


def test_nvidia_smi_rtx_target_selects_accelerated_backend(monkeypatch) -> None:
    monkeypatch.setattr(ray_query, "_cuda_driver_bindings_available", lambda: False)
    monkeypatch.setattr(ray_query.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout="NVIDIA GeForce RTX 5070 Laptop GPU, 8151, 590.48.01\n",
            stderr="",
        )

    monkeypatch.setattr(ray_query.subprocess, "run", fake_run)

    status = inspect_ray_runtime(require_rtx=True)

    assert status.backend == "rtx"
    assert status.accelerated is True
    assert "RTX 5070" in status.reason


def test_nvidia_smi_low_memory_target_fails_required_rtx(monkeypatch) -> None:
    monkeypatch.setattr(ray_query, "_cuda_driver_bindings_available", lambda: False)
    monkeypatch.setattr(ray_query.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["nvidia-smi"],
            returncode=0,
            stdout="NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 555.01\n",
            stderr="",
        )

    monkeypatch.setattr(ray_query.subprocess, "run", fake_run)

    status = inspect_ray_runtime(require_rtx=True)

    assert status.backend == "unavailable"
    assert status.accelerated is False
    assert "at least" in status.reason


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
