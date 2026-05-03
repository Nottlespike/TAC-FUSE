"""Metadata helpers for packaged TAC-FUSE classifier artifacts."""

from __future__ import annotations

import hashlib
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


def inspect_packaged_siglip2_package(
    manifest: dict[str, Any] | None = None,
    *,
    model_dir: str | Path | None = None,
    verify_checksums: bool = False,
) -> dict[str, Any]:
    """Inspect the local package without importing accelerator/runtime libraries."""

    package = manifest or load_siglip2_classifier_package()
    resolved_model_dir = (
        Path(model_dir) if model_dir is not None else packaged_siglip2_model_dir(package)
    )
    if not resolved_model_dir.is_absolute():
        resolved_model_dir = PACKAGE_ROOT / resolved_model_dir

    file_results: list[dict[str, Any]] = []
    missing_paths: list[str] = []
    checksum_failures: list[str] = []
    size_mismatches: list[str] = []
    for item in package.get("files", ()):
        rel_path = Path(str(item["path"]))
        path = resolved_model_dir / rel_path
        exists = path.exists()
        result = {
            "path": str(rel_path),
            "exists": exists,
            "expected_bytes": item.get("bytes"),
            "expected_sha256": item.get("sha256"),
        }
        if not exists:
            missing_paths.append(str(path))
            file_results.append(result)
            continue

        actual_bytes = path.stat().st_size
        result["bytes"] = actual_bytes
        if actual_bytes != item.get("bytes"):
            size_mismatches.append(str(path))
            result["size_ok"] = False
        else:
            result["size_ok"] = True

        if verify_checksums:
            actual_sha = _sha256(path)
            result["sha256"] = actual_sha
            result["checksum_ok"] = actual_sha == item.get("sha256")
            if not result["checksum_ok"]:
                checksum_failures.append(str(path))
        file_results.append(result)

    package_present = not missing_paths
    checksum_ok = None if not verify_checksums else not checksum_failures
    size_ok = not size_mismatches
    ready_for_demo = package_present and size_ok and (checksum_ok is not False)
    if not package_present:
        reason = "missing packaged classifier files"
    elif not size_ok:
        reason = "packaged classifier file sizes do not match manifest"
    elif checksum_ok is False:
        reason = "packaged classifier checksums do not match manifest"
    else:
        reason = "ready"

    return {
        "package_id": package.get("package_id"),
        "artifact_type": package.get("artifact_type"),
        "base_model": package.get("base_model"),
        "model_dir": str(resolved_model_dir),
        "package_present": package_present,
        "ready_for_demo": ready_for_demo,
        "reason": reason,
        "missing_paths": missing_paths,
        "size_mismatches": size_mismatches,
        "checksum_failures": checksum_failures,
        "checksum_verified": verify_checksums,
        "checksum_ok": checksum_ok,
        "metrics": package.get("metrics", {}),
        "selection": package.get("selection", {}),
        "files": file_results,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
