"""Metadata helpers for packaged TAC-FUSE classifier artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SIGLIP2_CLASSIFIER_PACKAGE = (
    PACKAGE_ROOT / "configs/model_packages/siglip2_expanded_vehicle_hpo_best.json"
)


def load_siglip2_classifier_package(
    path: str | Path = DEFAULT_SIGLIP2_CLASSIFIER_PACKAGE,
) -> dict[str, Any]:
    """Load the tracked manifest for the packaged SigLIP2 classifier."""

    manifest_path = Path(path)
    if not manifest_path.is_absolute():
        manifest_path = PACKAGE_ROOT / manifest_path
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def packaged_siglip2_model_dir(
    manifest: dict[str, Any] | None = None,
) -> Path:
    """Resolve the ignored local model directory from a package manifest."""

    package = manifest or load_siglip2_classifier_package()
    package_dir = Path(str(package["package_dir"]))
    if package_dir.is_absolute():
        return package_dir
    return PACKAGE_ROOT / package_dir


def packaged_siglip2_required_files(
    manifest: dict[str, Any] | None = None,
) -> tuple[Path, ...]:
    """Return model-package file paths relative to the resolved package dir."""

    package = manifest or load_siglip2_classifier_package()
    model_dir = packaged_siglip2_model_dir(package)
    return tuple(model_dir / str(item["path"]) for item in package.get("files", ()))
