"""Visual-asset catalogue — Pydantic models and loader for visual_asset_sources.yaml.

Design constraints
------------------
* No network I/O is performed by this module.
* Large or license-sensitive assets are ``manual=True``; the loader never
  attempts to download them.
* ``source_url: null`` is used for operator-supplied or Foundry-managed content.
* The local manifest is a plain JSON file written to the repository root so
  the web UI can load asset metadata without a live backend.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, Field

# ── Enumerations ────────────────────────────────────────────────────────────────


class AssetModality(Enum):
    """Modality axis for visual assets."""

    AERIAL_ORTHO = "aerial_ortho"
    DRONE_POV = "drone_pov"
    GROUND_TEXTURE = "ground_texture"
    MATERIAL_REF = "material_ref"
    OBJECT_REF = "object_ref"


class LicenseType(Enum):
    """Canonical set of recognised license identifiers.

    ``PROPRIETARY`` is used for operator / game-asset sources that cannot be
    redistributed at all.
    """

    CC0_1_0 = "CC0-1.0"
    CC_BY_4 = "CC BY 4.0"
    CC_BY_NC_ND_3 = "CC BY-NC-ND 3.0"
    CC_BY_SA_3_0_IGO = "CC BY-SA 3.0 IGO"
    ODBL = "ODbL"
    APACHE_2 = "Apache-2.0"
    NVIDIA_EULA = "NVIDIA Isaac Sim EULA"
    PROPRIETARY = "operator_proprietary"
    UNKNOWN = "unknown"


class AutoDownloadPolicy(Enum):
    """Whether a given asset may be fetched automatically."""

    AUTO = "auto"       # small, permissively licensed — safe to fetch
    MANUAL = "manual"    # operator must obtain manually
    PROHIBITED = "prohibited"  # game / commercial asset — never download


# ── Dataclass layer (plain, serialisable) ──────────────────────────────────────


@dataclass(frozen=True)
class VisualAsset:
    """Canonical description of one visual asset entry.

    This is the serialisable unit stored in the registry and written to the
    browser / SigLIP2 manifest.  No binary data is held here.
    """

    id: str
    description: str
    source_url: str | None
    license: str
    attribution: str
    capture_date: str | None
    modality: AssetModality
    expected_labels: list[str]
    local_cache_path: str
    manual: bool
    file_size_mb: float | str | None
    restriction_note: str

    _LICENSE_MAP: ClassVar[dict[str, LicenseType]] = {
        "CC0-1.0": LicenseType.CC0_1_0,
        "CC BY 4.0": LicenseType.CC_BY_4,
        "CC BY-NC-ND 3.0": LicenseType.CC_BY_NC_ND_3,
        "CC BY-SA 3.0 IGO": LicenseType.CC_BY_SA_3_0_IGO,
        "ODbL": LicenseType.ODBL,
        "Apache-2.0": LicenseType.APACHE_2,
        "NVIDIA Isaac Sim EULA": LicenseType.NVIDIA_EULA,
        "operator_proprietary": LicenseType.PROPRIETARY,
    }

    @property
    def license_type(self) -> LicenseType:
        return self._LICENSE_MAP.get(self.license, LicenseType.UNKNOWN)

    @property
    def download_policy(self) -> AutoDownloadPolicy:
        if self.manual:
            return AutoDownloadPolicy.MANUAL
        if self.license_type in (LicenseType.NVIDIA_EULA, LicenseType.PROPRIETARY):
            return AutoDownloadPolicy.PROHIBITED
        return AutoDownloadPolicy.AUTO

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["modality"] = self.modality.value
        d["download_policy"] = self.download_policy.value
        d["license_type"] = self.license_type.value
        return d


# ── Pydantic validation layer ──────────────────────────────────────────────────


class AssetEntryModel(BaseModel):
    """Validated YAML entry for one asset."""

    description: str = Field(description="Human-readable description of the asset")
    source_url: str | None = Field(
        default=None,
        description="URL to source. Null for operator / Foundry-managed content.",
    )
    license: str = Field(description="License identifier or 'operator_proprietary'")
    attribution: str = Field(description="Required attribution string")
    capture_date: str | None = Field(
        default=None,
        description="ISO-8601 capture date, if known",
    )
    modality: AssetModality = Field(
        description="One of the AssetModality enum values"
    )
    expected_labels: list[str] = Field(
        default_factory=list,
        description="Labels the asset is expected to contain",
    )
    local_cache_path: str = Field(
        description="Relative path under the repo root where this asset lives (or is placed)"
    )
    manual: bool = Field(
        default=False,
        description="If True, auto-download is prohibited; operator must acquire manually",
    )
    file_size_mb: float | str | None = Field(
        default=None,
        description="Approximate size in MB; null means unknown",
    )
    restriction_note: str = Field(
        description="Human-readable restriction / provenance caveat"
    )

    model_config = {"extra": "forbid"}


class VisualAssetSourcesModel(BaseModel):
    """Root of the visual_asset_sources.yaml schema."""

    assets: dict[str, AssetEntryModel] = Field(
        description="Mapping of asset ID → asset entry"
    )


# ── Catalog ────────────────────────────────────────────────────────────────────


@dataclass
class AssetCatalog:
    """In-memory registry of visual assets loaded from the YAML configuration.

    Attributes
    ----------
    sources_path : Path
        Path to the originating YAML file.
    assets : dict[str, VisualAsset]
        Map of asset ID → parsed :class:`VisualAsset`.
    _by_modality : dict[AssetModality, list[VisualAsset]]
        Secondary index built lazily on first access.
    """

    sources_path: Path
    assets: dict[str, VisualAsset] = field(default_factory=dict)
    _by_modality: dict[AssetModality, list[VisualAsset]] | None = None

    # ── loading ────────────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: Path | str) -> AssetCatalog:
        """Parse a visual_asset_sources.yaml file into an AssetCatalog.

        Args:
            path: Path to the YAML file.

        Returns:
            Populated AssetCatalog instance.

        Raises:
            FileNotFoundError: the file does not exist.
            ValidationError: Pydantic validation of the YAML failed.
        """
        path = Path(path)
        raw = yaml.safe_load(path.read_text()) or {}

        # Validate top-level structure
        model = VisualAssetSourcesModel.model_validate(raw)

        cat = cls(sources_path=path)
        for asset_id, entry in model.assets.items():
            cat.assets[asset_id] = VisualAsset(
                id=asset_id,
                description=entry.description,
                source_url=entry.source_url,
                license=entry.license,
                attribution=entry.attribution,
                capture_date=entry.capture_date,
                modality=entry.modality,
                expected_labels=list(entry.expected_labels),
                local_cache_path=entry.local_cache_path,
                manual=entry.manual,
                file_size_mb=entry.file_size_mb,
                restriction_note=entry.restriction_note,
            )

        return cat

    # ── query ──────────────────────────────────────────────────────────────────

    @property
    def by_modality(self) -> dict[AssetModality, list[VisualAsset]]:
        """Lazily-built secondary index on asset modality."""
        if self._by_modality is None:
            index: dict[AssetModality, list[VisualAsset]] = {m: [] for m in AssetModality}
            for asset in self.assets.values():
                index[asset.modality].append(asset)
            self._by_modality = index
        return self._by_modality

    def filter(
        self,
        modality: AssetModality | None = None,
        download_policy: AutoDownloadPolicy | None = None,
        license_type: LicenseType | None = None,
    ) -> list[VisualAsset]:
        """Return assets matching all non-None criteria."""
        results = list(self.assets.values())
        if modality is not None:
            results = [a for a in results if a.modality == modality]
        if download_policy is not None:
            results = [a for a in results if a.download_policy == download_policy]
        if license_type is not None:
            results = [a for a in results if a.license_type == license_type]
        return results

    def auto_downloadable(self) -> list[VisualAsset]:
        """Return assets eligible for automatic download (small, permissive license)."""
        return self.filter(download_policy=AutoDownloadPolicy.AUTO)

    def manual_only(self) -> list[VisualAsset]:
        """Return assets that must be manually acquired."""
        return self.filter(download_policy=AutoDownloadPolicy.MANUAL)

    def prohibited(self) -> list[VisualAsset]:
        """Return assets that must never be downloaded."""
        return self.filter(download_policy=AutoDownloadPolicy.PROHIBITED)

    # ── manifest generation ────────────────────────────────────────────────────

    def generate_manifest(
        self,
        *,
        root: Path | None = None,
        output_path: Path | str | None = None,
        include_proprietary: bool = False,
    ) -> dict[str, Any]:
        """Write a compact JSON manifest for the browser UI and SigLIP2 pipeline.

        Args:
            root: Repo root (defaults to ``sources_path.parent.parent.parent``).
            output_path: File to write. When None, manifest is returned but not saved.
            include_proprietary: If False (default), proprietary/prohibited entries
                are omitted from the manifest output.

        Returns:
            The manifest dict (also written to ``output_path`` when provided).
        """
        if root is None:
            root = self.sources_path.parent.parent.parent  # …/configs/assets → repo root

        manifest: dict[str, Any] = {
            "version": "1.0",
            "generated_from": str(self.sources_path.relative_to(root)),
            "catalog_size": len(self.assets),
            "assets": {},
        }

        for asset in self.assets.values():
            if not include_proprietary and asset.download_policy in (
                AutoDownloadPolicy.PROHIBITED,
                AutoDownloadPolicy.MANUAL,
            ):
                continue

            manifest["assets"][asset.id] = {
                "modality": asset.modality.value,
                "labels": asset.expected_labels,
                "license": asset.license,
                "attribution": asset.attribution,
                "local_path": asset.local_cache_path,
                "capture_date": asset.capture_date,
                "download_policy": asset.download_policy.value,
            }

        if output_path is not None:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(manifest, indent=2))

        return manifest

    # ── local file validation ──────────────────────────────────────────────────

    def validate_local(
        self,
        *,
        root: Path | None = None,
        dry_run: bool = True,
        allowed_local_only: bool = False,
    ) -> dict[str, Any]:
        """Check that locally-referenced asset paths actually exist on disk.

        Args:
            root: Repo root (defaults to repo root from sources_path).
            dry_run: If True, only report what *would* be checked.
            allowed_local_only: If True, fail on any asset with ``source_url is not None``.
                This enforces the "local-file-only validation" requirement.

        Returns:
            Dict with keys: ``checked``, ``present``, ``missing``, ``remote_only``
            (assets with no local path or source_url != None when
            ``allowed_local_only`` is True).
        """
        if root is None:
            root = self.sources_path.parent.parent.parent

        checked: list[str] = []
        present: list[str] = []
        missing: list[str] = []
        remote_only: list[str] = []

        for asset in self.assets.values():
            local = root / asset.local_cache_path
            checked.append(asset.id)

            if allowed_local_only and asset.source_url is not None:
                remote_only.append(asset.id)
                continue

            if dry_run:
                # In dry-run mode, just record the path we would check
                present.append(asset.id)
            else:
                if local.exists():
                    present.append(asset.id)
                else:
                    missing.append(asset.id)

        return {
            "checked": checked,
            "present": present,
            "missing": missing,
            "remote_only": remote_only,
            "dry_run": dry_run,
        }


# ── Module-level convenience ───────────────────────────────────────────────────


def load_catalog(
    config_path: Path | str | None = None,
) -> AssetCatalog:
    """Load the visual-asset catalog from the default or specified YAML path.

    Args:
        config_path: Path to ``visual_asset_sources.yaml``.  When ``None`` the
            package default (``configs/assets/visual_asset_sources.yaml``) is used.

    Returns:
        Populated ``AssetCatalog``.
    """
    if config_path is None:
        import tac_fuse

        config_path = (
            Path(tac_fuse.__file__).parent.parent
            / "configs"
            / "assets"
            / "visual_asset_sources.yaml"
        )
    return AssetCatalog.from_yaml(config_path)
