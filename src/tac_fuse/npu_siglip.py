"""Intel NPU boundary for a fine-tuned SigLIP2 field-condition classifier."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tac_fuse.pov import DronePOVFrame

MODEL_ID = "google/siglip2-base-patch16-224"
DEFAULT_MODEL_DIR = Path("models/siglip2-field-npu")
MODEL_DIR_ENV = "TAC_FUSE_SIGLIP_MODEL_DIR"
DEVICE_ENV = "TAC_FUSE_SIGLIP_DEVICE"

FIELD_CONDITION_LABELS = (
    "clear corridor",
    "dense multi asset formation",
    "drone near restricted area",
    "low altitude clutter",
    "low power return corridor",
    "reduced visibility field conditions",
)


@dataclass(frozen=True)
class NPUStatus:
    model_id: str
    model_dir: str
    device: str
    model_present: bool
    openvino_available: bool
    npu_device_visible: bool
    ready: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FieldConditionScore:
    label: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FieldConditionResult:
    model_id: str
    device: str
    emulated: bool
    top_label: str
    scores: list[FieldConditionScore]
    frame_timestamp_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "device": self.device,
            "emulated": self.emulated,
            "top_label": self.top_label,
            "scores": [score.to_dict() for score in self.scores],
            "frame_timestamp_s": self.frame_timestamp_s,
        }


class IntelNPUSigLIP2Adapter:
    """Adapter boundary for local OpenVINO SigLIP2 inference on Intel NPU."""

    def __init__(
        self,
        model_dir: str | os.PathLike[str] | None = None,
        *,
        device: str | None = None,
        labels: Iterable[str] = FIELD_CONDITION_LABELS,
    ) -> None:
        self.model_dir = Path(model_dir or os.environ.get(MODEL_DIR_ENV, DEFAULT_MODEL_DIR))
        self.device = device or os.environ.get(DEVICE_ENV, "NPU")
        self.labels = tuple(labels)

    @property
    def model_xml(self) -> Path:
        return self.model_dir / "openvino_model.xml"

    @property
    def model_bin(self) -> Path:
        return self.model_dir / "openvino_model.bin"

    def inspect_runtime(self) -> NPUStatus:
        openvino_available = False
        visible_devices: list[str] = []
        try:
            import openvino as ov  # type: ignore[import-not-found]

            openvino_available = True
            try:
                visible_devices = [str(device) for device in ov.Core().available_devices]
            except Exception:
                visible_devices = []
        except Exception:
            openvino_available = False

        model_present = self.model_xml.exists() and self.model_bin.exists()
        npu_visible = self.device in visible_devices or (
            self.device != "NPU" and openvino_available
        )
        ready = model_present and openvino_available and npu_visible
        if not model_present:
            reason = f"missing OpenVINO IR at {self.model_dir}"
        elif not openvino_available:
            reason = "openvino package is not installed"
        elif not npu_visible:
            reason = f"device {self.device!r} is not visible; available={visible_devices}"
        else:
            reason = "ready"
        return NPUStatus(
            model_id=MODEL_ID,
            model_dir=str(self.model_dir),
            device=self.device,
            model_present=model_present,
            openvino_available=openvino_available,
            npu_device_visible=npu_visible,
            ready=ready,
            reason=reason,
        )

    def classify_emulated(self, frame: DronePOVFrame) -> FieldConditionResult:
        top = frame.field_condition if frame.field_condition in self.labels else self.labels[0]
        object_pressure = min(0.18, len(frame.objects) * 0.035)
        scores: list[FieldConditionScore] = []
        for label in self.labels:
            score = 0.09
            if label == top:
                score = min(0.97, frame.confidence + object_pressure)
            elif "dense" in label and len(frame.objects) >= 3:
                score = 0.51
            elif "low power" in label and frame.ownship.battery_pct < 72:
                score = 0.48
            scores.append(FieldConditionScore(label=label, score=round(score, 4)))
        scores.sort(key=lambda item: item.score, reverse=True)
        return FieldConditionResult(
            model_id=MODEL_ID,
            device=self.device,
            emulated=True,
            top_label=scores[0].label,
            scores=scores,
            frame_timestamp_s=frame.timestamp_s,
        )

    def export_instructions(self) -> str:
        return (
            "Export a fine-tuned SigLIP2 checkpoint to OpenVINO IR before the demo:\n"
            f"  optimum-cli export openvino --model {MODEL_ID} "
            "--task zero-shot-image-classification --weight-format fp16 "
            f"{DEFAULT_MODEL_DIR}\n"
            f"Then set {MODEL_DIR_ENV}={DEFAULT_MODEL_DIR} and {DEVICE_ENV}=NPU."
        )
