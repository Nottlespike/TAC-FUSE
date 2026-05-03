"""Tests for controlled visual-asset caching."""

from __future__ import annotations

from pathlib import Path

from tac_fuse.assets.catalog import AssetCatalog, AssetModality, VisualAsset
from tac_fuse.assets.download import download_auto_assets


def _asset(
    asset_id: str,
    source_url: str | None,
    local_cache_path: str,
    *,
    manual: bool = False,
    license_name: str = "CC0-1.0",
) -> VisualAsset:
    return VisualAsset(
        id=asset_id,
        description="test asset",
        source_url=source_url,
        license=license_name,
        attribution="test attribution",
        capture_date="2026-01-01",
        modality=AssetModality.AERIAL_ORTHO,
        expected_labels=["terrain"],
        local_cache_path=local_cache_path,
        manual=manual,
        file_size_mb=None,
        restriction_note="test only",
    )


def _catalog(tmp_path: Path, *assets: VisualAsset) -> AssetCatalog:
    return AssetCatalog(
        sources_path=tmp_path / "visual_asset_sources.yaml",
        assets={asset.id: asset for asset in assets},
    )


def test_downloads_auto_unrestricted_file_url(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"earth imagery bytes")
    asset = _asset("earth_fixture", source.as_uri(), "assets/visual/earth/fixture.jpg")

    report = download_auto_assets(_catalog(tmp_path, asset), tmp_path, allow_file_urls=True)

    assert report.summary() == {"downloaded": 1, "total": 1}
    assert (tmp_path / "assets/visual/earth/fixture.jpg").read_bytes() == b"earth imagery bytes"
    assert len(report.records[0].sha256) == 64


def test_download_dry_run_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"preview only")
    asset = _asset("earth_fixture", source.as_uri(), "assets/visual/earth/fixture.jpg")

    report = download_auto_assets(
        _catalog(tmp_path, asset),
        tmp_path,
        dry_run=True,
        allow_file_urls=True,
    )

    assert report.summary() == {"dry_run": 1, "total": 1}
    assert not (tmp_path / "assets/visual/earth/fixture.jpg").exists()


def test_skips_manual_or_prohibited_sources(tmp_path: Path) -> None:
    manual = _asset(
        "manual_source",
        "https://example.invalid/manual.jpg",
        "assets/visual/manual.jpg",
        manual=True,
    )
    prohibited = _asset(
        "prohibited_source",
        "https://example.invalid/prohibited.jpg",
        "assets/visual/prohibited.jpg",
        license_name="operator_proprietary",
    )

    report = download_auto_assets(
        _catalog(tmp_path, manual, prohibited),
        tmp_path,
        source_ids=["manual_source", "prohibited_source"],
    )

    assert report.summary() == {"skipped": 2, "total": 2}
    assert {record.reason for record in report.records} == {
        "policy is manual",
        "policy is prohibited",
    }


def test_rejects_non_https_without_file_opt_in(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"earth imagery bytes")
    asset = _asset("earth_fixture", source.as_uri(), "assets/visual/earth/fixture.jpg")

    report = download_auto_assets(_catalog(tmp_path, asset), tmp_path)

    assert report.has_errors
    assert report.records[0].status == "error"
    assert "unsupported source_url scheme" in report.records[0].reason
