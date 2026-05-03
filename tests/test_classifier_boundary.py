"""Tests for the unified classifier boundary in tac_fuse.vision.classifier."""

import json
import tempfile
from pathlib import Path

import pytest

from tac_fuse.vision.classifier import (
    BoundingBox,
    ClassifierBoundary,
    ClassifierOutput,
    ModelAssetError,
    NaiveZeroShotClassifier,
    PackagedSigLIP2Classifier,
    SegmentationMask,
    create_classifier,
)


def _write_package_manifest(tmp_path: Path) -> tuple[Path, Path]:
    model_dir = tmp_path / "model"
    manifest = {
        "package_id": "test-siglip2-package",
        "artifact_type": "pytorch_siglip2_image_classifier",
        "package_dir": str(model_dir),
        "base_model": "google/siglip2-base-patch16-224",
        "dataset": {"label_mapping": {"clear_corridor": 0, "low_power_return_corridor": 1}},
        "metrics": {"eval_accuracy": 0.7, "eval_loss": 0.6, "score": 0.64},
        "selection": {"framework": "Ax + BoTorch", "trial_index": 14},
        "files": [
            {"path": "backbone/config.json", "bytes": 2, "sha256": "0" * 64},
            {"path": "processor/processor_config.json", "bytes": 2, "sha256": "1" * 64},
            {"path": "classifier_head.pt", "bytes": 2, "sha256": "2" * 64},
        ],
    }
    for item in manifest["files"]:
        path = model_dir / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "package.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, model_dir


class TestBoundingBox:
    """Tests for BoundingBox dataclass."""

    def test_bounding_box_creation(self) -> None:
        box = BoundingBox(x_min=10.0, y_min=20.0, x_max=100.0, y_max=200.0)
        assert box.x_min == 10.0
        assert box.y_min == 20.0
        assert box.x_max == 100.0
        assert box.y_max == 200.0

    def test_bounding_box_dimensions(self) -> None:
        box = BoundingBox(x_min=10.0, y_min=20.0, x_max=100.0, y_max=200.0)
        assert box.width == 90.0
        assert box.height == 180.0
        assert box.area == 90.0 * 180.0

    def test_bounding_box_to_dict(self) -> None:
        box = BoundingBox(x_min=10.0, y_min=20.0, x_max=100.0, y_max=200.0)
        d = box.to_dict()
        assert d["x_min"] == 10.0
        assert d["y_min"] == 20.0
        assert d["x_max"] == 100.0
        assert d["y_max"] == 200.0

    def test_bounding_box_normalize(self) -> None:
        box = BoundingBox(
            x_min=100.0,
            y_min=200.0,
            x_max=300.0,
            y_max=400.0,
            frame_width=1920.0,
            frame_height=1080.0,
        )
        normalized = box.normalize()
        assert normalized.x_min == pytest.approx(100.0 / 1920.0)
        assert normalized.y_min == pytest.approx(200.0 / 1080.0)
        assert normalized.x_max == pytest.approx(300.0 / 1920.0)
        assert normalized.y_max == pytest.approx(400.0 / 1080.0)
        # Normalized box should have no frame dimensions
        assert normalized.frame_width is None
        assert normalized.frame_height is None

    def test_bounding_box_normalize_no_frame_dims(self) -> None:
        box = BoundingBox(x_min=10.0, y_min=20.0, x_max=100.0, y_max=200.0)
        # Should return self when no frame dimensions
        assert box.normalize() is box


class TestSegmentationMask:
    """Tests for SegmentationMask dataclass."""

    def test_mask_creation(self) -> None:
        mask = SegmentationMask(
            mask_data=[0, 1, 1, 0],
            height=2,
            width=2,
            format="bitmap",
        )
        assert mask.mask_data == [0, 1, 1, 0]
        assert mask.height == 2
        assert mask.width == 2
        assert mask.format == "bitmap"

    def test_mask_num_pixels(self) -> None:
        mask = SegmentationMask(
            mask_data=[0, 1, 1, 0],
            height=2,
            width=2,
        )
        assert mask.num_pixels == 4

    def test_mask_to_dict(self) -> None:
        mask = SegmentationMask(
            mask_data=[0, 1, 1, 0],
            height=2,
            width=2,
        )
        d = mask.to_dict()
        assert d["mask_data"] == [0, 1, 1, 0]
        assert d["height"] == 2
        assert d["width"] == 2
        assert d["format"] == "bitmap"


class TestClassifierOutput:
    """Tests for ClassifierOutput dataclass."""

    def test_minimal_output_creation(self) -> None:
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
        )
        assert output.track_id == "track-001"
        assert output.class_label == "drone"
        assert output.confidence == 0.85
        assert output.box is None
        assert output.mask is None

    def test_output_with_box(self) -> None:
        box = BoundingBox(x_min=100.0, y_min=200.0, x_max=300.0, y_max=400.0)
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
            box=box,
        )
        assert output.box is box
        assert output.box.x_min == 100.0

    def test_output_with_mask(self) -> None:
        mask = SegmentationMask(mask_data=[0, 1], height=1, width=2)
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
            mask=mask,
        )
        assert output.mask is mask

    def test_output_with_all_candidates(self) -> None:
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
            all_candidates=[
                {"label": "drone", "confidence": 0.85},
                {"label": "bird", "confidence": 0.10},
            ],
        )
        assert len(output.all_candidates) == 2

    def test_output_to_dict(self) -> None:
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
        )
        d = output.to_dict()
        assert d["track_id"] == "track-001"
        assert d["class_label"] == "drone"
        assert d["confidence"] == 0.85
        assert "timestamp" in d
        assert d["inference_latency_ms"] == 42.5

    def test_output_to_dict_includes_optional_fields(self) -> None:
        box = BoundingBox(x_min=100.0, y_min=200.0, x_max=300.0, y_max=400.0)
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
            box=box,
            all_candidates=[{"label": "drone", "confidence": 0.85}],
        )
        d = output.to_dict()
        assert "box" in d
        assert "all_candidates" in d
        assert d["box"]["x_min"] == 100.0

    def test_output_invalid_confidence_low(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            ClassifierOutput(
                track_id="track-001",
                source_id="test_classifier",
                frame_path="/tmp/frame.jpg",
                class_label="drone",
                confidence=-0.1,
                device="CPU",
                model_id="test_model_v1",
                inference_latency_ms=42.5,
            )

    def test_output_invalid_confidence_high(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            ClassifierOutput(
                track_id="track-001",
                source_id="test_classifier",
                frame_path="/tmp/frame.jpg",
                class_label="drone",
                confidence=1.5,
                device="CPU",
                model_id="test_model_v1",
                inference_latency_ms=42.5,
            )

    def test_output_invalid_latency(self) -> None:
        with pytest.raises(ValueError, match="inference_latency_ms must be"):
            ClassifierOutput(
                track_id="track-001",
                source_id="test_classifier",
                frame_path="/tmp/frame.jpg",
                class_label="drone",
                confidence=0.85,
                device="CPU",
                model_id="test_model_v1",
                inference_latency_ms=-10.0,
            )

    def test_output_to_sensor_event(self) -> None:
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
        )
        event = output.to_sensor_event(asset_id="asset-123", seq=5)
        assert event.source == "npu_vision"
        assert event.source_id == "test_classifier"
        assert event.confidence == 0.85
        assert event.payload["track_id"] == "track-001"
        assert event.payload["frame_path"] == "/tmp/frame.jpg"
        assert event.payload["class_label"] == "drone"
        assert event.seq == 5

    def test_output_to_sensor_event_includes_box(self) -> None:
        box = BoundingBox(x_min=100.0, y_min=200.0, x_max=300.0, y_max=400.0)
        output = ClassifierOutput(
            track_id="track-001",
            source_id="test_classifier",
            frame_path="/tmp/frame.jpg",
            class_label="drone",
            confidence=0.85,
            device="CPU",
            model_id="test_model_v1",
            inference_latency_ms=42.5,
            box=box,
        )
        event = output.to_sensor_event()
        assert "box" in event.payload
        assert event.payload["box"]["x_min"] == 100.0


class TestModelAssetError:
    """Tests for ModelAssetError exception."""

    def test_error_creation_no_paths(self) -> None:
        err = ModelAssetError("Model not found")
        assert err.message == "Model not found"
        assert err.missing_paths == []

    def test_error_creation_with_paths(self) -> None:
        paths = [Path("/tmp/model.xml"), Path("/tmp/model.bin")]
        err = ModelAssetError("Missing IR files", missing_paths=paths)
        assert err.message == "Missing IR files"
        assert err.missing_paths == paths


class TestNaiveZeroShotClassifier:
    """Tests for NaiveZeroShotClassifier."""

    def test_classifier_always_ready(self) -> None:
        clf = NaiveZeroShotClassifier()
        assert clf.ready() is True

    def test_classifier_inspect_status(self) -> None:
        clf = NaiveZeroShotClassifier()
        status = clf.inspect_status()
        assert status["ready"] is True
        assert status["model_id"] == "naive_zero_shot_v1"
        assert status["source_id"] == "naive_zero_shot"
        assert status["device"] == "CPU"

    def test_classifier_default_label(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier(default_label="test_label")
            result = clf.classify(frame_path)
            assert result.class_label == "test_label"
            assert result.confidence == 0.5
        finally:
            Path(frame_path).unlink()

    def test_classifier_with_metadata_field_condition(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier()
            result = clf.classify_with_metadata(
                frame_path,
                field_condition="clear corridor",
            )
            assert result.class_label == "clear corridor"
            assert result.confidence == 0.75
        finally:
            Path(frame_path).unlink()

    def test_classifier_with_metadata_object_count(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier()
            result = clf.classify_with_metadata(
                frame_path,
                object_count=5,
            )
            assert result.class_label == "dense multi-asset scene"
            assert result.confidence == 0.65
        finally:
            Path(frame_path).unlink()

    def test_classifier_with_metadata_battery(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier()
            result = clf.classify_with_metadata(
                frame_path,
                battery_pct=25.0,
            )
            assert result.class_label == "low battery return"
            assert result.confidence == 0.80
        finally:
            Path(frame_path).unlink()

    def test_classifier_track_id_generation(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier()
            result1 = clf.classify(frame_path)
            result2 = clf.classify(frame_path)
            assert result1.track_id != result2.track_id
            assert "track-naive_zero_shot-" in result1.track_id
        finally:
            Path(frame_path).unlink()

    def test_classifier_custom_track_id(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier()
            result = clf.classify(frame_path, track_id="custom-track-123")
            assert result.track_id == "custom-track-123"
        finally:
            Path(frame_path).unlink()

    def test_classifier_file_not_found(self) -> None:
        clf = NaiveZeroShotClassifier()
        with pytest.raises(FileNotFoundError):
            clf.classify("/nonexistent/path/frame.jpg")

    def test_classifier_inference_latency_positive(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            clf = NaiveZeroShotClassifier()
            result = clf.classify(frame_path)
            assert result.inference_latency_ms >= 0
        finally:
            Path(frame_path).unlink()


class TestPackagedSigLIP2Classifier:
    """Tests for the H100-selected packaged classifier boundary."""

    def test_packaged_classifier_reports_missing_files(self, tmp_path: Path) -> None:
        manifest_path, model_dir = _write_package_manifest(tmp_path)
        (model_dir / "classifier_head.pt").unlink()

        clf = PackagedSigLIP2Classifier(
            model_path=model_dir,
            manifest_path=manifest_path,
        )
        status = clf.inspect_status()

        assert status["ready"] is False
        assert status["model_present"] is False
        assert "classifier_head.pt" in status["missing_paths"][0]

    def test_packaged_classifier_ready_with_runtime_dependencies(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        manifest_path, model_dir = _write_package_manifest(tmp_path)
        monkeypatch.setattr(
            PackagedSigLIP2Classifier,
            "_dependency_status",
            lambda self: {
                "PIL": True,
                "sentencepiece": True,
                "torch": True,
                "transformers": True,
            },
        )

        clf = PackagedSigLIP2Classifier(
            model_path=model_dir,
            manifest_path=manifest_path,
        )
        status = clf.inspect_status()

        assert status["ready"] is True
        assert status["package_id"] == "test-siglip2-package"
        assert status["metrics"]["eval_accuracy"] == 0.7

    def test_create_classifier_can_return_packaged_classifier(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        manifest_path, model_dir = _write_package_manifest(tmp_path)
        monkeypatch.setattr(
            PackagedSigLIP2Classifier,
            "_dependency_status",
            lambda self: {
                "PIL": True,
                "sentencepiece": True,
                "torch": True,
                "transformers": True,
            },
        )

        clf = create_classifier(
            use_trained=True,
            model_path=model_dir,
            manifest_path=manifest_path,
            fallback_to_naive=False,
        )

        assert isinstance(clf, PackagedSigLIP2Classifier)


class TestCreateClassifier:
    """Tests for create_classifier factory function."""

    def test_create_naive_by_default(self) -> None:
        clf = create_classifier()
        assert isinstance(clf, NaiveZeroShotClassifier)
        assert clf.ready() is True

    def test_create_naive_explicit(self) -> None:
        clf = create_classifier(use_trained=False)
        assert isinstance(clf, NaiveZeroShotClassifier)

    def test_create_with_fallback_no_model_path(self) -> None:
        clf = create_classifier(use_trained=True, fallback_to_naive=True)
        assert isinstance(clf, (NaiveZeroShotClassifier, PackagedSigLIP2Classifier))

    def test_create_without_fallback_no_model_path(self) -> None:
        try:
            clf = create_classifier(use_trained=True, fallback_to_naive=False)
        except ModelAssetError as exc:
            assert "Default packaged classifier is not ready" in str(exc)
        else:
            assert isinstance(clf, PackagedSigLIP2Classifier)

    def test_create_with_nonexistent_model_path_fallback(self) -> None:
        clf = create_classifier(
            use_trained=True,
            model_path="/nonexistent/model",
            fallback_to_naive=True,
        )
        assert isinstance(clf, NaiveZeroShotClassifier)

    def test_create_with_nonexistent_model_path_no_fallback(self) -> None:
        with pytest.raises(ModelAssetError, match="No valid model found"):
            create_classifier(
                use_trained=True,
                model_path="/nonexistent/model",
                fallback_to_naive=False,
            )

    def test_create_with_custom_device(self) -> None:
        clf = create_classifier(device="NPU")
        assert clf.device == "NPU"


class TestClassifierBoundaryProtocol:
    """Tests verifying the ClassifierBoundary protocol is satisfied."""

    def test_naive_classifier_satisfies_protocol(self) -> None:
        """Verify NaiveZeroShotClassifier implements ClassifierBoundary."""
        clf: ClassifierBoundary = NaiveZeroShotClassifier()

        # Check all required methods exist
        assert hasattr(clf, "ready")
        assert hasattr(clf, "inspect_status")
        assert hasattr(clf, "classify")
        assert hasattr(clf, "classify_batch")

        # Check return types
        assert isinstance(clf.ready(), bool)
        assert isinstance(clf.inspect_status(), dict)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            frame_path = f.name
        try:
            result = clf.classify(frame_path)
            assert isinstance(result, ClassifierOutput)
        finally:
            Path(frame_path).unlink()

    def test_classifier_batch_method(self) -> None:
        """Test classify_batch functionality."""
        clf = NaiveZeroShotClassifier()

        with (
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f1,
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f2,
        ):
            frame_paths = [f1.name, f2.name]
            try:
                results = clf.classify_batch(frame_paths)
                assert len(results) == 2
                assert all(isinstance(r, ClassifierOutput) for r in results)
                # Track IDs should be unique
                assert results[0].track_id != results[1].track_id
            finally:
                Path(f1.name).unlink()
                Path(f2.name).unlink()

    def test_classifier_batch_with_track_ids(self) -> None:
        """Test classify_batch with custom track IDs."""
        clf = NaiveZeroShotClassifier()
        track_ids = ["track-a", "track-b"]

        with (
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f1,
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f2,
        ):
            frame_paths = [f1.name, f2.name]
            try:
                results = clf.classify_batch(frame_paths, track_ids=track_ids)
                assert len(results) == 2
                assert results[0].track_id == "track-a"
                assert results[1].track_id == "track-b"
            finally:
                Path(f1.name).unlink()
                Path(f2.name).unlink()

    def test_classifier_batch_mismatched_track_ids(self) -> None:
        """Test classify_batch raises on mismatched track IDs."""
        clf = NaiveZeroShotClassifier()

        with (
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f1,
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f2,
        ):
            frame_paths = [f1.name, f2.name]
            try:
                with pytest.raises(ValueError, match="length must match"):
                    clf.classify_batch(frame_paths, track_ids=["only-one"])
            finally:
                Path(f1.name).unlink()
                Path(f2.name).unlink()
