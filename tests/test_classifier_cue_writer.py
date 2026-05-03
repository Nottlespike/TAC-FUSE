from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    script_path = ROOT / "scripts" / "write_classifier_cue.py"
    spec = importlib.util.spec_from_file_location("tac_fuse_classifier_cue", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


classifier_cue = _load_module()


class _FakeOutput:
    def __init__(self, frame_path: Path) -> None:
        self.frame_path = frame_path

    def to_dict(self) -> dict:
        return {
            "track_id": "scene-vehicle-17",
            "source_id": "siglip2_expanded_vehicle_hpo",
            "frame_path": str(self.frame_path),
            "class_label": "clear_corridor",
            "confidence": 0.42,
            "device": "cpu",
            "model_id": "google/siglip2-base-patch16-224",
            "inference_latency_ms": 12.5,
            "all_candidates": [
                {"label": "clear_corridor", "confidence": 0.42},
                {"label": "dense_multi_asset_formation", "confidence": 0.23},
            ],
        }


class _ReadyClassifier:
    def __init__(
        self,
        *,
        model_path: Path | None = None,
        manifest_path: Path | None = None,
        device: str = "CPU",
    ) -> None:
        self.model_path = model_path
        self.manifest_path = manifest_path
        self.device = device

    def inspect_status(self) -> dict:
        return {
            "ready": True,
            "reason": "ready",
            "package_id": "siglip2-expanded-vehicle-hpo-best",
            "device": self.device,
        }

    def classify(self, frame_path: Path, *, track_id: str | None = None) -> _FakeOutput:
        assert track_id == "scene-vehicle-17"
        assert frame_path.exists()
        return _FakeOutput(frame_path)


def _package_status() -> dict:
    return {
        "model_dir": "models/siglip2-expanded-vehicle-hpo-best",
        "package_id": "siglip2-expanded-vehicle-hpo-best",
        "ready_for_demo": True,
        "reason": "ready",
        "metrics": {"eval_accuracy": 0.6979166666666666},
        "selection": {"framework": "Ax + BoTorch"},
    }


def _payload_from_js(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    marker = "window.TAC_FUSE_CLASSIFIER_CUE = "
    assert marker in text
    return json.loads(text.split(marker, 1)[1].rsplit(";", 1)[0])


def test_writer_emits_real_model_cue_artifact(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "classifier_cue.js"
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake image bytes")

    monkeypatch.setattr(classifier_cue, "load_siglip2_classifier_package", lambda path=None: {})
    monkeypatch.setattr(
        classifier_cue,
        "inspect_packaged_siglip2_package",
        lambda manifest, model_dir=None: _package_status(),
    )
    monkeypatch.setattr(classifier_cue, "PackagedSigLIP2Classifier", _ReadyClassifier)

    assert (
        classifier_cue.main(
            ["--output", str(output), "--image", str(image), "--device", "CPU"]
        )
        == 0
    )

    payload = _payload_from_js(output)
    assert payload["ready"] is True
    assert payload["classification"]["class_label"] == "clear_corridor"
    assert payload["classification"]["confidence"] == 0.42
    assert payload["top_candidates"][0]["label"] == "clear_corridor"
    assert payload["ui"]["status_label"] == "Generated Model Cue"
    assert payload["pipeline"]["generated_by"] == "scripts/write_classifier_cue.py"


def test_writer_can_emit_unavailable_artifact(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "classifier_cue.js"
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake image bytes")

    class UnavailableClassifier(_ReadyClassifier):
        def inspect_status(self) -> dict:
            return {"ready": False, "reason": "missing classifier runtime dependencies"}

        def classify(self, frame_path: Path, *, track_id: str | None = None) -> _FakeOutput:
            raise classifier_cue.ModelAssetError("missing classifier runtime dependencies")

    monkeypatch.setattr(classifier_cue, "load_siglip2_classifier_package", lambda path=None: {})
    monkeypatch.setattr(
        classifier_cue,
        "inspect_packaged_siglip2_package",
        lambda manifest, model_dir=None: {**_package_status(), "ready_for_demo": False},
    )
    monkeypatch.setattr(classifier_cue, "PackagedSigLIP2Classifier", UnavailableClassifier)

    assert (
        classifier_cue.main(
            [
                "--output",
                str(output),
                "--image",
                str(image),
                "--allow-unavailable",
            ]
        )
        == 0
    )

    payload = _payload_from_js(output)
    assert payload["ready"] is False
    assert payload["classification"] is None
    assert "missing classifier runtime dependencies" in payload["error"]
    assert payload["ui"]["status_label"] == "No Model Cue"


def test_checked_in_classifier_cue_is_parseable() -> None:
    payload = _payload_from_js(ROOT / "web" / "classifier_cue.js")

    assert payload["pipeline"]["generated_by"] == "scripts/write_classifier_cue.py"
    assert "ready" in payload
    if payload["ready"]:
        assert payload["classification"]["class_label"]
        assert payload["top_candidates"]
