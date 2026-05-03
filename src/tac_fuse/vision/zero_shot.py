"""Zero-shot image-text classification helpers for TAC-FUSE frames.

Pure ranking functions (rank_zero_shot_logits, default_zero_shot_prompts, etc.)
have no OpenVINO, NPU, GPU, or internet dependency. They run entirely on CPU.

The OpenVINO classifier imports accelerator libraries only at call time,
preserving the TAC-FUSE CPU-only command-node baseline. Accelerator offload
is an optional enhancement; CPU is the required primary compute path.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tac_fuse.fusion_node.ingest import ContributorSource, SensorEvent
from tac_fuse.training.siglip2_config import SigLIP2INT8Config


@dataclass(frozen=True, slots=True)
class ZeroShotPrompt:
    """A mission label and the natural-language prompt scored for it."""

    label: str
    prompt: str


@dataclass(frozen=True, slots=True)
class ZeroShotCandidate:
    """A ranked zero-shot label candidate."""

    label: str
    prompt: str
    score: float
    logit: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ZeroShotClassification:
    """Zero-shot classification result for one TAC-FUSE frame."""

    frame_path: str
    device: str
    model_xml: str
    candidates: tuple[ZeroShotCandidate, ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def top_candidate(self) -> ZeroShotCandidate | None:
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_path": self.frame_path,
            "device": self.device,
            "model_xml": self.model_xml,
            "timestamp": self.timestamp.isoformat(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    def to_sensor_event(
        self,
        *,
        asset_id: str,
        event_id: str | None = None,
        confidence_floor: float = 0.0,
        as_detection: bool = False,
        emit_alert: bool = False,
        alert_floor: float | None = None,
        source_id: str = "siglip2_zero_shot",
        seq: int = 0,
    ) -> SensorEvent:
        """Represent zero-shot scene semantics as an upstream TAC-FUSE event.

        Zero-shot labels are pseudo-classifications by default: they describe
        the best matching prompt for the frame, not a localized object with a
        bounding box. Set ``as_detection=True`` only when a caller intentionally
        wants the top prompt copied into the standard video detections payload.
        """

        import uuid

        top = self.top_candidate
        confidence = 0.0
        pseudo_classification = None
        detections: list[dict[str, object]] = []
        if top is not None:
            confidence = top.score
            pseudo_classification = top.to_dict()
            if as_detection and top.score >= confidence_floor:
                detections.append(
                    {
                        "class": top.label,
                        "confidence": top.score,
                        "source": "siglip2_zero_shot",
                        "pseudo": True,
                    }
                )

        return SensorEvent(
            event_id=event_id or f"zero-shot-pseudo-{uuid.uuid4()}",
            source=ContributorSource.NPU_VISION.value,
            source_id=source_id,
            timestamp=self.timestamp.isoformat(),
            received_at=datetime.now(UTC).isoformat(),
            confidence=confidence,
            uncertainty=max(0.0, 1.0 - confidence),
            provenance="siglip2_openvino_zero_shot",
            seq=seq,
            payload={
                "asset_id": asset_id,
                "frame_path": self.frame_path,
                "classifier": "siglip2_zero_shot",
                "classification_mode": "pseudo",
                "pseudo_classification": pseudo_classification,
                "pseudo_classification_alert": emit_alert,
                "pseudo_classification_alert_floor": (
                    confidence_floor if alert_floor is None else alert_floor
                ),
                "device": self.device,
                "model_xml": self.model_xml,
                "data": {
                    "detections": detections,
                    "candidates": [candidate.to_dict() for candidate in self.candidates],
                },
            },
        )


def _label_from_prompt(prompt: str) -> str:
    label = prompt.strip()
    for prefix in ("a ", "an ", "the "):
        if label.lower().startswith(prefix):
            return label[len(prefix) :]
    return label


def default_zero_shot_prompts(
    config: SigLIP2INT8Config | None = None,
) -> tuple[ZeroShotPrompt, ...]:
    """Build TAC-FUSE mission prompts from the SigLIP2 config."""

    config = config or SigLIP2INT8Config()
    return tuple(
        ZeroShotPrompt(label=_label_from_prompt(prompt), prompt=prompt)
        for prompt in config.class_prompts
    )


def _flatten_logits(logits: Any) -> list[float]:
    if hasattr(logits, "tolist"):
        logits = logits.tolist()
    if not isinstance(logits, list):
        return [float(logits)]
    if not logits:
        return []
    if all(not isinstance(item, list) for item in logits):
        return [float(item) for item in logits]
    if len(logits) == 1 and isinstance(logits[0], list):
        return [float(item) for item in logits[0]]
    if all(isinstance(item, list) and len(item) == 1 for item in logits):
        return [float(item[0]) for item in logits]
    raise ValueError("Expected logits shaped [labels], [1, labels], or [labels, 1].")


def _softmax(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    maximum = max(values)
    exp_values = [math.exp(value - maximum) for value in values]
    total = sum(exp_values)
    return [value / total for value in exp_values]


def rank_zero_shot_logits(
    prompts: Sequence[ZeroShotPrompt],
    logits: Any,
    *,
    top_k: int | None = None,
) -> tuple[ZeroShotCandidate, ...]:
    """Convert SigLIP/OpenVINO logits into ranked TAC-FUSE candidates."""

    flat_logits = _flatten_logits(logits)
    if len(flat_logits) != len(prompts):
        raise ValueError(
            f"Prompt/logit length mismatch: {len(prompts)} prompts, {len(flat_logits)} logits."
        )

    scores = _softmax(flat_logits)
    candidates = [
        ZeroShotCandidate(
            label=prompt.label,
            prompt=prompt.prompt,
            score=score,
            logit=logit,
        )
        for prompt, score, logit in zip(prompts, scores, flat_logits, strict=True)
    ]
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    if top_k is None:
        return tuple(ranked)
    return tuple(ranked[: max(top_k, 0)])


class OpenVINOZeroShotClassifier:
    """Lazy OpenVINO runtime for TAC-FUSE SigLIP2 zero-shot classification."""

    def __init__(
        self,
        *,
        model_xml: Path,
        config: SigLIP2INT8Config | None = None,
        device: str = "NPU",
        prompts: Iterable[ZeroShotPrompt] | None = None,
        processor_id_or_path: str | Path | None = None,
    ) -> None:
        self.config = config or SigLIP2INT8Config()
        self.model_xml = Path(model_xml)
        self.device = device
        self.prompts = (
            tuple(prompts)
            if prompts is not None
            else default_zero_shot_prompts(self.config)
        )
        self.processor_id_or_path = str(processor_id_or_path or self.config.model_id)
        self._core: Any | None = None
        self._compiled_model: Any | None = None
        self._processor: Any | None = None

    def classify_image(self, frame_path: Path, *, top_k: int = 5) -> ZeroShotClassification:
        """Classify an image against the configured TAC-FUSE prompts."""

        if not self.model_xml.exists():
            raise FileNotFoundError(f"OpenVINO model XML not found: {self.model_xml}")

        import os

        import numpy as np
        import openvino as ov
        from PIL import Image
        from transformers import AutoProcessor

        from tac_fuse.npu_trainer import openvino_env

        os.environ.update(openvino_env(self.config))
        if self._core is None:
            self._core = ov.Core()
        if self._processor is None:
            self._processor = AutoProcessor.from_pretrained(
                self.processor_id_or_path,
                fix_mistral_regex=True,
                use_fast=False,
            )
        if self._compiled_model is None:
            model = self._core.read_model(self.model_xml)
            input_names = {input_.get_any_name() for input_ in model.inputs}
            reshape = {}
            if "input_ids" in input_names:
                reshape["input_ids"] = [len(self.prompts), self.config.max_text_tokens]
            if "pixel_values" in input_names:
                reshape["pixel_values"] = [1, 3, self.config.image_size, self.config.image_size]
            if reshape:
                model.reshape(reshape)
            self._compiled_model = self._core.compile_model(model, self.device)

        image = Image.open(frame_path).convert("RGB")
        batch = self._processor(
            text=[prompt.prompt for prompt in self.prompts],
            images=image,
            padding="max_length",
            truncation=True,
            max_length=self.config.max_text_tokens,
            return_tensors="np",
        )
        infer_inputs: dict[str, Any] = {}
        expected_inputs = {input_.get_any_name() for input_ in self._compiled_model.inputs}
        if "input_ids" in expected_inputs:
            infer_inputs["input_ids"] = np.asarray(batch["input_ids"], dtype=np.int64)
        if "pixel_values" in expected_inputs:
            infer_inputs["pixel_values"] = np.asarray(batch["pixel_values"], dtype=np.float32)

        outputs = self._compiled_model.create_infer_request().infer(infer_inputs)
        logits = None
        for output, value in outputs.items():
            name = output.get_any_name() if hasattr(output, "get_any_name") else str(output)
            if name == "logits_per_image":
                logits = value
                break
        if logits is None:
            logits = next(iter(outputs.values()))

        return ZeroShotClassification(
            frame_path=str(frame_path),
            device=self.device,
            model_xml=str(self.model_xml),
            candidates=rank_zero_shot_logits(self.prompts, logits, top_k=top_k),
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run TAC-FUSE zero-shot classification for one image frame."""

    import argparse
    import json

    config = SigLIP2INT8Config()
    parser = argparse.ArgumentParser(description="Classify a TAC-FUSE frame with SigLIP2/OpenVINO.")
    parser.add_argument("image", type=Path, help="Image frame to classify.")
    parser.add_argument(
        "--model-xml",
        type=Path,
        default=config.export_dir / "openvino_model.xml",
        help="Path to the OpenVINO IR XML model.",
    )
    parser.add_argument(
        "--processor",
        default=None,
        help="Processor directory or Hugging Face model ID. Defaults to the SigLIP2 model ID.",
    )
    parser.add_argument("--device", default=config.target_device, help="OpenVINO device name.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of labels to return.")
    parser.add_argument(
        "--asset-id",
        default="local-frame",
        help="Asset ID for SensorEvent output.",
    )
    parser.add_argument(
        "--confidence-floor",
        type=float,
        default=0.0,
        help="Minimum top score required when copying a pseudo-label into detection_class.",
    )
    parser.add_argument(
        "--as-detection",
        action="store_true",
        help="Copy the top pseudo-label into detection_class when it meets --confidence-floor.",
    )
    parser.add_argument(
        "--emit-alert",
        action="store_true",
        help="Mark event metadata so AlertingEngine emits a pseudo-classification alert.",
    )
    parser.add_argument(
        "--alert-floor",
        type=float,
        default=None,
        help="Minimum top score for pseudo-classification alert routing.",
    )
    parser.add_argument(
        "--as-event",
        action="store_true",
        help="Emit a TAC-FUSE SensorEvent-compatible payload instead of classification JSON.",
    )
    args = parser.parse_args(argv)

    classifier = OpenVINOZeroShotClassifier(
        model_xml=args.model_xml,
        device=args.device,
        processor_id_or_path=args.processor,
    )
    result = classifier.classify_image(args.image, top_k=args.top_k)
    if args.as_event:
        event = result.to_sensor_event(
            asset_id=args.asset_id,
            confidence_floor=args.confidence_floor,
            as_detection=args.as_detection,
            emit_alert=args.emit_alert,
            alert_floor=args.alert_floor,
        )
        payload: dict[str, object] = event.to_dict()
    else:
        payload = result.to_dict()
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
