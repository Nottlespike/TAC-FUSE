#!/usr/bin/env -S uv run python
"""Prepare visual assets for TAC-FUSE computer-vision demos.

This script loads the visual-asset catalogue, validates local paths, and emits
a compact JSON manifest for the browser UI and the SigLIP2 dataset pipeline.

Usage
-----
    # Dry-run (default) — report what would be validated without touching disk
    uv run python scripts/prepare_visual_assets.py

    # Validate existing local files
    uv run python scripts/prepare_visual_assets.py --no-dry-run

    # Strict local-file-only check (fail if any source_url is non-null)
    uv run python scripts/prepare_visual_assets.py --no-dry-run --local-only

    # Write manifest to a custom path
    uv run python scripts/prepare_visual_assets.py --manifest-out web/assets_manifest.json

Exit codes
----------
    0 — success (or dry-run with no issues)
    1 — validation errors or I/O failures
    2 — illegal option combination
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure tac_fuse is importable
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from tac_fuse.assets import AssetCatalog


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare TAC-FUSE visual-asset catalogue and generate browser manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to visual_asset_sources.yaml "
        "(default: configs/assets/visual_asset_sources.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action=EnableDisableFlag,
        default=True,
        dest="dry_run",
        help="Validate paths but do not write the manifest (default: %(default)s)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="Actually write the manifest and check local file existence",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        default=False,
        help="Fail validation for any asset that has a non-null source_url. "
        "Enforces the 'never require live downloads in verification' constraint.",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output path for the JSON manifest "
        "(default: <repo_root>/web/assets_manifest.json)",
    )
    parser.add_argument(
        "--siglip2-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Output path for the SigLIP2 dataset index JSON "
        "(default: <repo_root>/assets/siglip2_dataset_index.json)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Emit per-asset detail"
    )
    return parser


class EnableDisableFlag(argparse.Action):
    """Store True/False from --flag / --no-flag arguments."""

    def __init__(self, option_strings: list[str], dest: str, nargs: int = 0, **kwargs):
        super().__init__(option_strings, nargs=nargs, dest=dest, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | None,
        option_string: str | None,
    ) -> None:
        setattr(namespace, self.dest, True)


def _repo_root(sources_path: Path) -> Path:
    return sources_path.parent.parent.parent  # …/configs/assets → repo root


def _default_manifest_path(root: Path) -> Path:
    path = root / "web" / "assets_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _default_siglip2_path(root: Path) -> Path:
    path = root / "assets" / "siglip2_dataset_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _report(catalog: AssetCatalog, verbose: bool) -> None:
    """Print a human-readable catalogue summary."""
    print(f"\nLoaded {len(catalog.assets)} asset(s) from {catalog.sources_path}")
    print(f"\n{'ID':<35} {'Modality':<20} {'Download':<12} {'License'}")
    print("-" * 85)
    for asset in catalog.assets.values():
        policy = asset.download_policy.value
        print(
            f"{asset.id:<35} {asset.modality.value:<20} {policy:<12} {asset.license}"
        )

    if verbose:
        print("\n--- Per-asset detail ---")
        for asset in catalog.assets.values():
            print(f"\n  [{asset.id}]")
            print(f"    description: {asset.description}")
            print(f"    local_path:  {asset.local_cache_path}")
            print(f"    source_url:  {asset.source_url}")
            print(f"    restriction: {asset.restriction_note}")


def _validate(
    catalog: AssetCatalog,
    root: Path,
    dry_run: bool,
    local_only: bool,
) -> int:
    """Run local file validation; return 0 on success, 1 on failure."""
    result = catalog.validate_local(
        root=root,
        dry_run=dry_run,
        allowed_local_only=local_only,
    )

    issues: list[str] = []
    if result["remote_only"]:
        ids = ", ".join(result["remote_only"])
        issues.append(
            "  [remote_only] "
            f"{len(result['remote_only'])} asset(s) have non-null source_url: {ids}"
        )

    if not dry_run and result["missing"]:
        ids = ", ".join(result["missing"])
        issues.append(f"  [missing] {len(result['missing'])} local path(s) not found: {ids}")

    if issues:
        print("\n[VALIDATION ERRORS]")
        for line in issues:
            print(line)
        return 1

    print(f"\n[VALIDATION OK] checked={len(result['checked'])} present={len(result['present'])}")
    if result["dry_run"]:
        print("  (dry-run — local paths not checked on disk)")
    return 0


def _write_manifest(
    catalog: AssetCatalog,
    root: Path,
    manifest_out: Path | None,
    siglip2_out: Path | None,
    dry_run: bool,
) -> int:
    """Write the browser manifest and SigLIP2 index; return 0 on success."""
    manifest_path = manifest_out or _default_manifest_path(root)

    manifest = catalog.generate_manifest(
        root=root,
        output_path=manifest_path if not dry_run else None,
        include_proprietary=False,
    )

    print(f"\n[MANIFEST] {len(manifest['assets'])} downloadable asset(s)")
    print(f"  Path: {manifest_path if not dry_run else '(dry-run)'}")

    if siglip2_out is not None:
        siglip2_path = siglip2_out
    else:
        siglip2_path = _default_siglip2_path(root)

    # Build a SigLIP2-compatible index: modality → list of {id, labels, path}
    siglip2_index: dict[str, list[dict[str, Any]]] = {}
    for asset in catalog.assets.values():
        modality = asset.modality.value
        siglip2_index.setdefault(modality, []).append(
            {
                "id": asset.id,
                "labels": asset.expected_labels,
                "path": asset.local_cache_path,
            }
        )

    if not dry_run:
        siglip2_path.parent.mkdir(parents=True, exist_ok=True)
        siglip2_path.write_text(json.dumps(siglip2_index, indent=2))
        print(f"  SigLIP2 index: {siglip2_path}")
    else:
        print(f"  SigLIP2 index: (dry-run) {siglip2_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Resolve config path
    if args.config is not None:
        config_path = args.config
    else:
        import tac_fuse

        config_path = (
            Path(tac_fuse.__file__).parent.parent
            / "configs"
            / "assets"
            / "visual_asset_sources.yaml"
        )

    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}", file=sys.stderr)
        return 1

    try:
        catalog = AssetCatalog.from_yaml(config_path)
    except Exception as exc:
        print(f"[ERROR] Failed to load config: {exc}", file=sys.stderr)
        return 1

    root = _repo_root(config_path)
    _report(catalog, args.verbose)

    rc = _validate(catalog, root, args.dry_run, args.local_only)
    if rc != 0:
        return rc

    return _write_manifest(
        catalog,
        root,
        args.manifest_out,
        args.siglip2_out,
        args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
