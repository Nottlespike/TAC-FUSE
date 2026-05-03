"""Cache approved TAC-FUSE visual assets from their source URLs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from tac_fuse.assets.catalog import load_catalog  # noqa: E402
from tac_fuse.assets.download import (  # noqa: E402
    DEFAULT_MAX_DOWNLOAD_BYTES,
    DEFAULT_TIMEOUT_SEC,
    download_auto_assets,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=_PROJECT_ROOT / "configs" / "assets" / "visual_asset_sources.yaml",
    )
    parser.add_argument("--project-root", type=Path, default=_PROJECT_ROOT)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-file-urls", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_DOWNLOAD_BYTES)
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--no-manifest", action="store_true")
    parser.add_argument("--manifest-output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        catalog = load_catalog(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = download_auto_assets(
        catalog,
        args.project_root,
        source_ids=args.source or None,
        force=args.force,
        dry_run=args.dry_run,
        allow_file_urls=args.allow_file_urls,
        max_bytes=args.max_bytes,
        timeout_sec=args.timeout_sec,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))

    if report.has_errors:
        return 1
    if args.dry_run or args.no_manifest:
        return 0

    output_path = args.manifest_output
    if output_path is None:
        output_path = args.project_root / "configs/assets/visual_asset_manifest.json"
    manifest = catalog.generate_manifest(root=args.project_root, output_path=output_path)
    print(f"\nWrote manifest with {len(manifest['assets'])} assets to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
