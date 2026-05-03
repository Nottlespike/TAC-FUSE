from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    script_path = ROOT / "scripts" / "write_strix_compute_status.py"
    spec = importlib.util.spec_from_file_location("tac_fuse_strix_compute_status", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


strix_status = _load_module()


class _FakeStatus:
    def __init__(self, payload: dict):
        self.payload = payload

    def to_dict(self) -> dict:
        return dict(self.payload)


def _payload_from_js(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    marker = "window.TAC_FUSE_STRIX_COMPUTE = "
    assert marker in text
    return json.loads(text.split(marker, 1)[1].rsplit(";", 1)[0])


def test_writer_emits_strix_accelerated_status(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "strix_compute_status.js"

    monkeypatch.setattr(
        strix_status,
        "inspect_ray_runtime",
        lambda: _FakeStatus(
            {
                "backend": "rtx",
                "available": True,
                "accelerated": True,
                "reason": "cuda driver bindings importable",
            }
        ),
    )

    class ReadyAdapter:
        def __init__(self, *, model_dir: Path | None = None, device: str | None = None) -> None:
            self.model_dir = model_dir
            self.device = device

        def inspect_runtime(self) -> _FakeStatus:
            return _FakeStatus(
                {
                    "model_id": "google/siglip2-base-patch16-224",
                    "model_dir": str(self.model_dir),
                    "device": self.device,
                    "model_present": True,
                    "openvino_available": True,
                    "npu_device_visible": True,
                    "ready": True,
                    "reason": "ready",
                }
            )

    monkeypatch.setattr(strix_status, "IntelNPUSigLIP2Adapter", ReadyAdapter)

    assert strix_status.main(["--output", str(output), "--model-dir", "models/siglip2-field-npu"]) == 0

    payload = _payload_from_js(output)
    assert payload["ray"]["accelerated"] is True
    assert payload["npu"]["ready"] is True
    assert payload["ui"]["backend_label"] == "Strix CUDA/RTX"
    assert payload["ui"]["npu_label"] == "Strix NPU Ready"
    assert payload["ui"]["summary_label"] == "Strix CUDA/RTX + NPU"
    assert payload["ui"]["compute_mode"] == "strix_cuda_npu"


def test_writer_keeps_demo_safe_when_strix_compute_is_pending(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "strix_compute_status.js"

    monkeypatch.setattr(
        strix_status,
        "inspect_ray_runtime",
        lambda: _FakeStatus(
            {
                "backend": "cpu_parity",
                "available": True,
                "accelerated": False,
                "reason": "using CPU BVH parity path",
            }
        ),
    )

    class PendingAdapter:
        def __init__(self, *, model_dir: Path | None = None, device: str | None = None) -> None:
            self.model_dir = model_dir
            self.device = device

        def inspect_runtime(self) -> _FakeStatus:
            return _FakeStatus(
                {
                    "model_id": "google/siglip2-base-patch16-224",
                    "model_dir": str(self.model_dir),
                    "device": self.device,
                    "model_present": False,
                    "openvino_available": False,
                    "npu_device_visible": False,
                    "ready": False,
                    "reason": "missing OpenVINO IR",
                }
            )

    monkeypatch.setattr(strix_status, "IntelNPUSigLIP2Adapter", PendingAdapter)

    assert strix_status.main(["--output", str(output), "--device", "NPU"]) == 0

    payload = _payload_from_js(output)
    assert payload["ray"]["available"] is True
    assert payload["ray"]["accelerated"] is False
    assert payload["npu"]["ready"] is False
    assert payload["ui"]["backend_label"] == "CPU BVH Parity"
    assert payload["ui"]["npu_label"] == "NPU Pending"
    assert payload["ui"]["summary_label"] == "CPU BVH + NPU Pending"
    assert payload["ui"]["compute_mode"] == "cpu_parity"


def test_checked_in_browser_status_is_parseable() -> None:
    payload = _payload_from_js(ROOT / "web" / "strix_compute_status.js")

    assert payload["pipeline"]["generated_by"] == "scripts/write_strix_compute_status.py"
    assert payload["ui"]["route_guard_use_case"]
