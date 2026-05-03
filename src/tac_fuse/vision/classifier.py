"""Unified classifier boundary for TAC-FUSE vision inference.

This module defines the shared output contract that allows a trained model
to replace the naive zero-shot labeler without changing local C2, route
pathing, sync, or alert contracts.

The ClassifierOutput dataclass includes all required fields for downstream
consumers: track ID, source ID, frame path, class label, confidence, optional
box or mask, device, model ID, and inference latency.

Missing model assets must fail clearly in the hardware lane and never block
the core route-guard demo. The ClassifierBoundary interface provides a
ready() method for checking model availability before inference.
"""

from __future__ import annotations

import importlib.util
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from tac_fuse.fusion_node.ingest import ContributorSource, SensorEvent
from tac_fuse.training.model_package import (
    inspect_packaged_siglip2_package,
    load_siglip2_classifier_package,
    packaged_siglip2_model_dir,
)


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    frame_width: float | None = None
    frame_height: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        return self.width * self.height

    def normalize(self) -> BoundingBox:
        if self.frame_width is None or self.frame_height is None:
            return self
        return BoundingBox(
            x_min=self.x_min / self.frame_width,
            y_min=self.y_min / self.frame_height,
            x_max=self.x_max / self.frame_width,
            y_max=self.y_max / self.frame_height,
            frame_width=None,
            frame_height=None,
        )


@dataclass(frozen=True, slots=True)
class SegmentationMask:
    mask_data: list[int | float]
    height: int
    width: int
    format: str = "bitmap"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def num_pixels(self) -> int:
        return self.height * self.width


@dataclass(frozen=True, slots=True)
class ClassifierOutput:
    track_id: str
    source_id: str
    frame_path: str
    class_label: str
    confidence: float
    device: str
    model_id: str
    inference_latency_ms: float
    box: BoundingBox | None = None
    mask: SegmentationMask | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    all_candidates: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.inference_latency_ms < 0:
            raise ValueError(f"inference_latency_ms must be >= 0, got {self.inference_latency_ms}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "track_id": self.track_id,
            "source_id": self.source_id,
            "frame_path": self.frame_path,
            "class_label": self.class_label,
            "confidence": self.confidence,
            "device": self.device,
            "model_id": self.model_id,
            "inference_latency_ms": self.inference_latency_ms,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.box is not None:
            result["box"] = self.box.to_dict()
        if self.mask is not None:
            result["mask"] = self.mask.to_dict()
        if self.all_candidates:
            result["all_candidates"] = self.all_candidates
        return result

    def to_sensor_event(
        self,
        *,
        asset_id: str | None = None,
        event_id: str | None = None,
        seq: int = 0,
        provenance: str = "classifier_boundary",
    ) -> SensorEvent:
        import uuid

        payload: dict[str, Any] = {
            "track_id": self.track_id,
            "frame_path": self.frame_path,
            "class_label": self.class_label,
            "confidence": self.confidence,
            "device": self.device,
            "model_id": self.model_id,
            "inference_latency_ms": self.inference_latency_ms,
        }
        if self.box is not None:
            payload["box"] = self.box.to_dict()
        if self.mask is not None:
            payload["mask"] = self.mask.to_dict()
        if self.all_candidates:
            payload["all_candidates"] = self.all_candidates

        return SensorEvent(
            event_id=event_id or f"cls-{uuid.uuid4()}",
            source=ContributorSource.NPU_VISION.value,
            source_id=self.source_id,
            timestamp=self.timestamp.isoformat(),
            received_at=datetime.now(UTC).isoformat(),
            confidence=self.confidence,
            uncertainty=max(0.0, 1.0 - self.confidence),
            provenance=provenance,
            seq=seq,
            payload=payload,
        )


class ModelAssetError(Exception):
    def __init__(self, message: str, missing_paths: list[Path] | None = None) -> None:
        self.message = message
        self.missing_paths = missing_paths or []
        super().__init__(message)


class ClassifierBoundary(Protocol):
    def ready(self) -> bool: ...
    def inspect_status(self) -> dict[str, Any]: ...
    def classify(
        self,
        frame_path: str | Path,
        *,
        track_id: str | None = None,
    ) -> ClassifierOutput: ...
    def classify_batch(
        self,
        frame_paths: list[str | Path],
        *,
        track_ids: list[str] | None = None,
    ) -> list[ClassifierOutput]: ...


class BaseClassifier(ABC):
    def __init__(self, *, model_id: str, source_id: str, device: str = "CPU") -> None:
        self.model_id = model_id
        self.source_id = source_id
        self.device = device
        self._track_counter = 0

    def _generate_track_id(self) -> str:
        self._track_counter += 1
        return f"track-{self.source_id}-{self._track_counter:06d}"

    def _time_inference(self, fn: Any) -> tuple[Any, float]:
        start = time.perf_counter()
        result = fn()
        latency_ms = (time.perf_counter() - start) * 1000
        return result, latency_ms

    def ready(self) -> bool:
        return self._ready_impl()

    def inspect_status(self) -> dict[str, Any]:
        status = self._inspect_status_impl()
        status["model_id"] = self.model_id
        status["source_id"] = self.source_id
        status["device"] = self.device
        return status

    def classify(self, frame_path: str | Path, *, track_id: str | None = None) -> ClassifierOutput:
        frame_path = Path(frame_path)
        if not frame_path.exists():
            raise FileNotFoundError(f"Frame not found: {frame_path}")

        if not self.ready():
            status = self.inspect_status()
            reason = status.get("reason", "classifier not ready")
            raise ModelAssetError(f"Cannot classify: {reason}", self._get_missing_paths())

        track_id = track_id or self._generate_track_id()

        def _run() -> tuple[str, float, list[dict[str, Any]]]:
            return self._classify_impl(frame_path)

        (class_label, confidence, all_candidates), latency_ms = self._time_inference(_run)

        return ClassifierOutput(
            track_id=track_id,
            source_id=self.source_id,
            frame_path=str(frame_path),
            class_label=class_label,
            confidence=confidence,
            device=self.device,
            model_id=self.model_id,
            inference_latency_ms=latency_ms,
            all_candidates=all_candidates,
        )

    def classify_batch(
        self,
        frame_paths: list[str | Path],
        *,
        track_ids: list[str] | None = None,
    ) -> list[ClassifierOutput]:
        if track_ids is None:
            track_ids = [self._generate_track_id() for _ in frame_paths]
        elif len(track_ids) != len(frame_paths):
            raise ValueError("track_ids length must match frame_paths length")

        results: list[ClassifierOutput] = []
        for frame_path, track_id in zip(frame_paths, track_ids, strict=True):
            results.append(self.classify(frame_path, track_id=track_id))
        return results

    @abstractmethod
    def _ready_impl(self) -> bool:
        pass

    @abstractmethod
    def _inspect_status_impl(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def _classify_impl(self, frame_path: Path) -> tuple[str, float, list[dict[str, Any]]]:
        pass

    def _get_missing_paths(self) -> list[Path]:
        return []


class NaiveZeroShotClassifier(BaseClassifier):
    def __init__(
        self,
        *,
        source_id: str = "naive_zero_shot",
        device: str = "CPU",
        default_label: str = "unknown",
        default_confidence: float = 0.5,
    ) -> None:
        super().__init__(model_id="naive_zero_shot_v1", source_id=source_id, device=device)
        self.default_label = default_label
        self.default_confidence = default_confidence

    def _ready_impl(self) -> bool:
        return True

    def _inspect_status_impl(self) -> dict[str, Any]:
        return {
            "ready": True,
            "reason": "naive classifier has no model dependencies",
            "model_present": False,
            "openvino_available": False,
        }

    def _get_missing_paths(self) -> list[Path]:
        return []

    def _classify_impl(self, frame_path: Path) -> tuple[str, float, list[dict[str, Any]]]:
        all_candidates = [{"label": self.default_label, "confidence": self.default_confidence}]
        return self.default_label, self.default_confidence, all_candidates

    def classify_with_metadata(
        self,
        frame_path: str | Path,
        *,
        field_condition: str | None = None,
        object_count: int = 0,
        battery_pct: float | None = None,
        track_id: str | None = None,
    ) -> ClassifierOutput:
        frame_path = Path(frame_path)
        if not frame_path.exists():
            raise FileNotFoundError(f"Frame not found: {frame_path}")

        track_id = track_id or self._generate_track_id()
        start = time.perf_counter()

        label = self.default_label
        confidence = self.default_confidence
        all_candidates: list[dict[str, Any]] = []

        if field_condition is not None:
            label = field_condition
            confidence = 0.75
            all_candidates = [{"label": label, "confidence": confidence}]
        elif object_count >= 3:
            label = "dense multi-asset scene"
            confidence = 0.65
            all_candidates = [{"label": label, "confidence": confidence}]
        elif battery_pct is not None and battery_pct < 30:
            label = "low battery return"
            confidence = 0.80
            all_candidates = [{"label": label, "confidence": confidence}]

        latency_ms = (time.perf_counter() - start) * 1000

        return ClassifierOutput(
            track_id=track_id,
            source_id=self.source_id,
            frame_path=str(frame_path),
            class_label=label,
            confidence=confidence,
            device=self.device,
            model_id=self.model_id,
            inference_latency_ms=latency_ms,
            all_candidates=all_candidates,
        )


class PackagedSigLIP2Classifier(BaseClassifier):
    """Lazy PyTorch runtime for the H100-selected SigLIP2 classifier package."""

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        manifest_path: str | Path | None = None,
        source_id: str = "siglip2_expanded_vehicle_hpo",
        device: str = "CPU",
    ) -> None:
        self.manifest = load_siglip2_classifier_package(
            manifest_path
        ) if manifest_path is not None else load_siglip2_classifier_package()
        model_dir = Path(model_path) if model_path is not None else packaged_siglip2_model_dir(
            self.manifest
        )
        self.model_dir = model_dir
        self._runtime: dict[str, Any] | None = None
        super().__init__(
            model_id=str(self.manifest.get("base_model", "google/siglip2-base-patch16-224")),
            source_id=source_id,
            device=device,
        )

    def _ready_impl(self) -> bool:
        status = self._inspect_status_impl()
        return bool(status["ready"])

    def _inspect_status_impl(self) -> dict[str, Any]:
        package_status = inspect_packaged_siglip2_package(
            self.manifest,
            model_dir=self.model_dir,
            verify_checksums=False,
        )
        dependencies = self._dependency_status()
        runtime_available = all(dependencies.values())
        ready = bool(package_status["ready_for_demo"] and runtime_available)
        if not package_status["ready_for_demo"]:
            reason = str(package_status["reason"])
        elif not runtime_available:
            missing = sorted(name for name, present in dependencies.items() if not present)
            reason = f"missing classifier runtime dependencies: {', '.join(missing)}"
        else:
            reason = "ready"

        return {
            "ready": ready,
            "reason": reason,
            "model_present": package_status["package_present"],
            "package_id": package_status["package_id"],
            "artifact_type": package_status["artifact_type"],
            "model_dir": package_status["model_dir"],
            "runtime_dependencies": dependencies,
            "metrics": package_status["metrics"],
            "selection": package_status["selection"],
            "missing_paths": package_status["missing_paths"],
        }

    def _get_missing_paths(self) -> list[Path]:
        status = inspect_packaged_siglip2_package(self.manifest, model_dir=self.model_dir)
        return [Path(path) for path in status["missing_paths"]]

    @staticmethod
    def _module_available(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            return False

    def _dependency_status(self) -> dict[str, bool]:
        return {
            "PIL": self._module_available("PIL"),
            "google.protobuf": self._module_available("google.protobuf"),
            "sentencepiece": self._module_available("sentencepiece"),
            "torch": self._module_available("torch"),
            "torchvision": self._module_available("torchvision"),
            "transformers": self._module_available("transformers"),
        }

    def load(self) -> None:
        """Load the packaged backbone, processor, and classifier head into memory."""

        self._ensure_loaded()

    def _classify_impl(self, frame_path: Path) -> tuple[str, float, list[dict[str, Any]]]:
        runtime = self._ensure_loaded()
        torch = runtime["torch"]
        image_cls = runtime["Image"]
        processor = runtime["processor"]
        backbone = runtime["backbone"]
        head = runtime["head"]
        labels = runtime["labels"]
        device = runtime["device"]

        image = image_cls.open(frame_path).convert("RGB")
        encoded = processor(images=[image], return_tensors="pt")
        pixel_values = encoded["pixel_values"].to(device)
        with torch.no_grad():
            logits = head(self._image_features(backbone, pixel_values))
            probabilities = torch.softmax(logits, dim=-1)[0].detach().cpu()

        ranked = sorted(
            (
                {
                    "label": labels[index],
                    "confidence": float(probabilities[index]),
                }
                for index in range(len(labels))
            ),
            key=lambda item: item["confidence"],
            reverse=True,
        )
        top = ranked[0]
        return str(top["label"]), float(top["confidence"]), ranked

    def _ensure_loaded(self) -> dict[str, Any]:
        if self._runtime is not None:
            return self._runtime

        if not self.ready():
            status = self.inspect_status()
            raise ModelAssetError(f"Cannot load packaged classifier: {status['reason']}")

        import torch
        from PIL import Image
        from transformers import AutoModel, AutoProcessor

        torch_device = self._torch_device(torch)
        processor = AutoProcessor.from_pretrained(
            str(self.model_dir / "processor"),
            local_files_only=True,
            use_fast=True,
        )
        backbone = AutoModel.from_pretrained(
            str(self.model_dir / "backbone"),
            local_files_only=True,
        ).to(torch_device)
        backbone.eval()

        head_payload = torch.load(
            self.model_dir / "classifier_head.pt",
            map_location=torch_device,
            weights_only=False,
        )
        labels = tuple(
            str(label)
            for label in head_payload.get(
                "labels",
                sorted(
                    self.manifest["dataset"]["label_mapping"],
                    key=self.manifest["dataset"]["label_mapping"].get,
                ),
            )
        )
        feature_dim = int(head_payload["feature_dim"])
        head = torch.nn.Linear(feature_dim, len(labels)).to(torch_device)
        head.load_state_dict(head_payload["head_state_dict"])
        head.eval()

        self._runtime = {
            "Image": Image,
            "backbone": backbone,
            "device": torch_device,
            "head": head,
            "labels": labels,
            "processor": processor,
            "torch": torch,
        }
        self.device = str(torch_device)
        return self._runtime

    def _torch_device(self, torch: Any) -> Any:
        requested = self.device.lower()
        if requested == "auto":
            requested = "cuda" if torch.cuda.is_available() else "cpu"
        if requested == "cpu":
            return torch.device("cpu")
        if requested == "cuda":
            if not torch.cuda.is_available():
                raise ModelAssetError("CUDA requested but torch.cuda.is_available() is false")
            return torch.device("cuda")
        raise ModelAssetError(
            f"Packaged PyTorch classifier supports CPU/CUDA devices, not {self.device!r}"
        )

    @staticmethod
    def _image_features(backbone: Any, pixel_values: Any) -> Any:
        if hasattr(backbone, "get_image_features"):
            return PackagedSigLIP2Classifier._feature_tensor(
                backbone.get_image_features(pixel_values=pixel_values)
            )
        outputs = backbone(pixel_values=pixel_values)
        return PackagedSigLIP2Classifier._feature_tensor(outputs)

    @staticmethod
    def _feature_tensor(outputs: Any) -> Any:
        if getattr(outputs, "image_embeds", None) is not None:
            return outputs.image_embeds
        if getattr(outputs, "pooler_output", None) is not None:
            return outputs.pooler_output
        if getattr(outputs, "last_hidden_state", None) is not None:
            return outputs.last_hidden_state.mean(dim=1)
        if isinstance(outputs, (tuple, list)) and outputs:
            tensor = outputs[0]
        else:
            tensor = outputs
        if getattr(tensor, "ndim", 0) > 2:
            return tensor.mean(dim=1)
        return tensor


def create_classifier(
    *,
    use_trained: bool = False,
    model_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    device: str = "CPU",
    fallback_to_naive: bool = True,
) -> ClassifierBoundary:
    if not use_trained:
        return NaiveZeroShotClassifier(device=device)

    if model_path is None:
        packaged = PackagedSigLIP2Classifier(device=device, manifest_path=manifest_path)
        if packaged.ready():
            return packaged
        if fallback_to_naive:
            return NaiveZeroShotClassifier(device=device)
        status = packaged.inspect_status()
        raise ModelAssetError(
            f"Default packaged classifier is not ready: {status['reason']}",
            missing_paths=packaged._get_missing_paths(),
        )

    model_path = Path(model_path)
    packaged = PackagedSigLIP2Classifier(
        model_path=model_path,
        manifest_path=manifest_path,
        device=device,
    )
    package_status = packaged.inspect_status()
    if package_status["model_present"]:
        if packaged.ready():
            return packaged
        if fallback_to_naive:
            return NaiveZeroShotClassifier(device=device)
        raise ModelAssetError(
            f"Packaged classifier is not ready: {package_status['reason']}",
            missing_paths=packaged._get_missing_paths(),
        )

    model_xml = model_path / "openvino_model.xml"
    model_bin = model_path / "openvino_model.bin"

    if model_xml.exists() and model_bin.exists():
        if fallback_to_naive:
            return NaiveZeroShotClassifier(device=device)
        raise ModelAssetError(
            "OpenVINO model found but trained classifier not yet implemented",
            missing_paths=[],
        )

    if fallback_to_naive:
        return NaiveZeroShotClassifier(device=device)

    raise ModelAssetError(
        f"No valid model found at {model_path}",
        missing_paths=[model_xml, model_bin],
    )
