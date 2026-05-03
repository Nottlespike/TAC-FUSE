"""Visual-asset catalogue for TAC-FUSE computer-vision demos.

The catalogue registers operator-provided imagery, texture references, and label
taxonomies.  It tracks provenance, license, download policy, and local cache
paths so that the demo can reference assets without embedding large binaries
or proprietary data.

Public API
-----------
:class:`VisualAsset`   — typed description of a single asset entry.
:class:`AssetCatalog`  — in-memory registry loaded from ``visual_asset_sources.yaml``.
:func:`load_catalog`   — construct an ``AssetCatalog`` from a YAML path.
:func:`generate_manifest` — write the compact browser / SigLIP2 JSON manifest.
:func:`validate_local` — check that locally-referenced files actually exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tac_fuse.assets.catalog import AssetCatalog, VisualAsset, load_catalog

__all__ = [
    "AssetCatalog",
    "VisualAsset",
    "load_catalog",
    "generate_manifest",
    "validate_local",
]

# Re-export from catalog for public API
generate_manifest = AssetCatalog.generate_manifest
validate_local = AssetCatalog.validate_local
