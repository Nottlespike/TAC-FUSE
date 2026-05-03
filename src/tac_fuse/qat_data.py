"""Dataset registry for TAC-FUSE SigLIP2 INT8/QAT work."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QATDatasetSpec:
    """A candidate dataset for drone-oriented INT8 calibration and QAT."""

    name: str
    priority: int
    task: str
    hf_repo: str | None
    splits: tuple[str, ...]
    hf_native: bool
    required: bool
    rationale: str
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["splits"] = list(self.splits)
        return payload


DATASET_REGISTRY: tuple[QATDatasetSpec, ...] = (
    QATDatasetSpec(
        name="VisDrone2019-DET",
        priority=1,
        task="object_detection",
        hf_repo="Voxel51/VisDrone2019-DET",
        splits=("train",),
        hf_native=True,
        required=True,
        rationale=(
            "Primary drone-view object detection corpus for people, vehicles, and traffic "
            "objects in aerial imagery."
        ),
    ),
    QATDatasetSpec(
        name="DroneVehicle",
        priority=1,
        task="object_detection",
        hf_repo="McCheng/DroneVehicle",
        splits=("train", "validation", "test"),
        hf_native=True,
        required=True,
        rationale=(
            "Drone-mounted visible/infrared vehicle detection data for command-and-control "
            "asset identification."
        ),
    ),
    QATDatasetSpec(
        name="Drone Detection Dataset",
        priority=2,
        task="drone_detection",
        hf_repo="pathikg/drone-detection-dataset",
        splits=("train", "test"),
        hf_native=True,
        required=False,
        rationale="Supplemental positive/negative drone presence data for classifier prompts.",
    ),
    QATDatasetSpec(
        name="DOTA",
        priority=4,
        task="oriented_object_detection",
        hf_repo=None,
        splits=(),
        hf_native=False,
        required=False,
        rationale="Optional oriented-box aerial benchmark; use only if HF-native sets overfit.",
        notes="Keep optional because the initial training path prefers Hugging Face-native data.",
    ),
)


def prioritized_datasets(*, hf_native_only: bool = True) -> tuple[QATDatasetSpec, ...]:
    """Return datasets in the order the trainer should try them."""

    candidates = (
        dataset for dataset in DATASET_REGISTRY if dataset.hf_native or not hf_native_only
    )
    return tuple(sorted(candidates, key=lambda item: (item.priority, item.name)))


def required_hf_repos() -> tuple[str, ...]:
    """Return required Hugging Face dataset repos for the first QAT run."""

    repos = [
        dataset.hf_repo
        for dataset in prioritized_datasets(hf_native_only=True)
        if dataset.required and dataset.hf_repo
    ]
    return tuple(repos)


def write_manifest(path: Path, *, hf_native_only: bool = True) -> Path:
    """Write a JSON dataset manifest for reproducible QAT preflight runs."""

    datasets = [
        dataset.to_dict()
        for dataset in prioritized_datasets(hf_native_only=hf_native_only)
    ]
    payload = {
        "policy": {
            "prefer_huggingface_native": hf_native_only,
            "dota_optional": True,
            "primary_use": (
                "SigLIP2 INT8 calibration and NNCF QAT for TAC-FUSE vision "
                "(optional accelerator path; core C2 does not require this)"
            ),
        },
        "datasets": datasets,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
