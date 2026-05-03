"""Write the packaged classifier cue consumed by the static browser demo.

The browser demo is often opened directly from ``web/index.html``.  It cannot
load the PyTorch SigLIP2 checkpoint itself, so this script runs the packaged
classifier locally and writes a small JavaScript artifact for the TAC views.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tac_fuse.training.model_package import (
    inspect_packaged_siglip2_package,
    load_siglip2_classifier_package,
)
from tac_fuse.vision.classifier import ModelAssetError, PackagedSigLIP2Classifier

DEFAULT_OUTPUT = Path("web/classifier_cue.js")
DEFAULT_SYNTHETIC_FRAME = Path("reports/classifier_cue_route_guard.jpg")
GLOBAL_NAME = "TAC_FUSE_CLASSIFIER_CUE"
TOP_CANDIDATES = 6


def _now_utc() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_synthetic_route_guard_frame(path: Path) -> None:
    """Create a deterministic local frame for the demo cue smoke test."""

    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (224, 224), "#8f9d72")
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, 224, 72), fill="#b8c2a0")
    draw.rectangle((0, 72, 224, 224), fill="#7a7f5f")
    draw.polygon([(0, 163), (224, 92), (224, 137), (18, 224), (0, 224)], fill="#5e6354")
    draw.line([(2, 178), (222, 112)], fill="#d8d0a2", width=5)
    draw.line([(8, 202), (224, 128)], fill="#2f3431", width=2)
    draw.ellipse((164, 30, 205, 68), fill="#8798a6", outline="#5d707d", width=3)

    draw.rectangle((57, 112, 164, 143), fill="#26383c", outline="#10191b", width=3)
    draw.polygon([(78, 96), (132, 96), (155, 112), (62, 112)], fill="#314e56")
    draw.rectangle((88, 101, 121, 113), fill="#9fb4bf")
    draw.rectangle((125, 102, 146, 113), fill="#9fb4bf")
    draw.rectangle((160, 120, 181, 138), fill="#2c3131")
    for cx in (78, 145):
        draw.ellipse((cx - 14, 132, cx + 14, 160), fill="#151819")
        draw.ellipse((cx - 6, 140, cx + 6, 152), fill="#6f7669")

    draw.rectangle((23, 36, 53, 45), fill="#303b40")
    draw.line([(38, 22), (38, 58)], fill="#303b40", width=3)
    draw.line([(22, 40), (55, 40)], fill="#303b40", width=2)

    image.save(path, format="JPEG", quality=92)


def _classification_payload(output: Any) -> dict[str, Any]:
    if hasattr(output, "to_dict"):
        return dict(output.to_dict())
    if isinstance(output, dict):
        return dict(output)
    raise TypeError(f"unsupported classifier output object: {type(output)!r}")


def _top_candidates(classification: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = classification.get("all_candidates", [])
    if not isinstance(candidates, list):
        return []
    return [
        {
            "label": str(item.get("label", "")),
            "confidence": float(item.get("confidence", 0.0)),
        }
        for item in candidates[:TOP_CANDIDATES]
        if isinstance(item, dict)
    ]


def _display_path(path: str | Path | None) -> str:
    if path is None:
        return ""
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(Path.cwd().resolve()))
    except (OSError, ValueError):
        return str(path)


def _package_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": status.get("package_id"),
        "artifact_type": status.get("artifact_type"),
        "base_model": status.get("base_model"),
        "model_dir": _display_path(status.get("model_dir")),
        "package_present": status.get("package_present"),
        "ready_for_demo": status.get("ready_for_demo"),
        "reason": status.get("reason"),
        "metrics": status.get("metrics", {}),
        "selection": status.get("selection", {}),
        "missing_paths": [_display_path(path) for path in status.get("missing_paths", [])],
        "size_mismatches": [_display_path(path) for path in status.get("size_mismatches", [])],
        "checksum_verified": status.get("checksum_verified"),
        "checksum_ok": status.get("checksum_ok"),
    }


def _runtime_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready": status.get("ready"),
        "reason": status.get("reason"),
        "model_id": status.get("model_id"),
        "source_id": status.get("source_id"),
        "device": status.get("device"),
        "model_present": status.get("model_present"),
        "package_id": status.get("package_id"),
        "model_dir": _display_path(status.get("model_dir")),
        "runtime_dependencies": status.get("runtime_dependencies", {}),
    }


def _unavailable_payload(
    *,
    package_status: dict[str, Any],
    runtime_status: dict[str, Any],
    error: str,
    output_path: Path,
    frame_source: dict[str, Any],
    device: str,
) -> dict[str, Any]:
    return {
        "generated_at": _now_utc(),
        "ready": False,
        "error": error,
        "classification": None,
        "top_candidates": [],
        "frame": frame_source,
        "package": _package_summary(package_status),
        "runtime": _runtime_summary(runtime_status),
        "ui": {
            "cue_label": "Classifier Cue Unavailable",
            "confidence_pct": 0,
            "status_label": "No Model Cue",
        },
        "pipeline": {
            "generated_by": "scripts/write_classifier_cue.py",
            "output": str(output_path),
            "device": device,
        },
    }


def collect_classifier_cue(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    image_path: Path | None = None,
    synthetic_frame: Path = DEFAULT_SYNTHETIC_FRAME,
    model_dir: Path | None = None,
    manifest_path: Path | None = None,
    device: str = "CPU",
    track_id: str = "scene-vehicle-17",
) -> dict[str, Any]:
    manifest = (
        load_siglip2_classifier_package(manifest_path)
        if manifest_path is not None
        else load_siglip2_classifier_package()
    )
    package_status = inspect_packaged_siglip2_package(manifest, model_dir=model_dir)
    classifier = PackagedSigLIP2Classifier(
        model_path=model_dir,
        manifest_path=manifest_path,
        device=device,
    )
    runtime_status = classifier.inspect_status()

    generated_frame = image_path is None
    frame_path = image_path or synthetic_frame
    frame_source = {
        "path": str(frame_path),
        "source": "synthetic_route_guard_vehicle_frame"
        if generated_frame
        else "operator_supplied_frame",
    }

    try:
        if generated_frame:
            _write_synthetic_route_guard_frame(frame_path)
        classification = _classification_payload(
            classifier.classify(frame_path, track_id=track_id)
        )
        runtime_status = classifier.inspect_status()
    except (
        FileNotFoundError,
        ImportError,
        ModelAssetError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        return _unavailable_payload(
            package_status=package_status,
            runtime_status=runtime_status,
            error=str(exc),
            output_path=output_path,
            frame_source=frame_source,
            device=device,
        )

    confidence = float(classification.get("confidence", 0.0))
    return {
        "generated_at": _now_utc(),
        "ready": True,
        "classification": classification,
        "top_candidates": _top_candidates(classification),
        "frame": frame_source,
        "package": _package_summary(package_status),
        "runtime": _runtime_summary(runtime_status),
        "ui": {
            "cue_label": str(classification.get("class_label", "unknown")),
            "confidence_pct": round(confidence * 100),
            "status_label": "Generated Model Cue",
        },
        "pipeline": {
            "generated_by": "scripts/write_classifier_cue.py",
            "output": str(output_path),
            "device": device,
            "track_id": track_id,
            "model_dir": _display_path(model_dir or package_status["model_dir"]),
            "manifest": str(manifest_path) if manifest_path is not None else "default",
        },
    }


def render_js(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, indent=2, sort_keys=True)
    return (
        "// Generated by scripts/write_classifier_cue.py.\n"
        "// Regenerate after changing the packaged H100 classifier or demo frame.\n"
        f"window.{GLOBAL_NAME} = {body};\n"
    )


def write_cue(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_js(payload), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--synthetic-frame", type=Path, default=DEFAULT_SYNTHETIC_FRAME)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--device", default="CPU", choices=("CPU", "cpu", "cuda", "auto"))
    parser.add_argument("--track-id", default="scene-vehicle-17")
    parser.add_argument(
        "--allow-unavailable",
        action="store_true",
        help="Write an unavailable cue artifact instead of failing the command.",
    )
    args = parser.parse_args(argv)

    payload = collect_classifier_cue(
        output_path=args.output,
        image_path=args.image,
        synthetic_frame=args.synthetic_frame,
        model_dir=args.model_dir,
        manifest_path=args.manifest,
        device=args.device,
        track_id=args.track_id,
    )
    if not payload["ready"] and not args.allow_unavailable:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1

    write_cue(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
