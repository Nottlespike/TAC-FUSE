"""Tests for controlled visual-asset caching."""

from __future__ import annotations

from pathlib import Path

from tac_fuse.assets.catalog import AssetCatalog, AssetEntry
from tac_fuse.assets.download import download_auto_assets


def _catalog(*entries: AssetEntry) -> AssetCatalog:
    return AssetCatalog(
        name="test_assets",
        description="test catalog",
        entries=list(entries),
        manifest_config={"hash_algorithm": "sha256"},
    )


def test_downloads_auto_unrestricted_file_url(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"earth imagery bytes")
    entry = AssetEntry(
        id="earth_fixture",
        modality="orthophoto",
        source_url=source.as_uri(),
        restriction="none",
        local_cache_path="assets/visual/earth/fixture.jpg",
        auto_download=True,
        formats=["jpg"],
    )

    report = download_auto_assets(_catalog(entry), tmp_path, allow_file_urls=True)

    assert report.summary() == {"downloaded": 1, "total": 1}
    assert (tmp_path / "assets/visual/earth/fixture.jpg").read_bytes() == b"earth imagery bytes"
    assert len(report.records[0].sha256) == 64


def test_download_dry_run_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"preview only")
    entry = AssetEntry(
        id="earth_fixture",
        modality="orthophoto",
        source_url=source.as_uri(),
        restriction="none",
        local_cache_path="assets/visual/earth/fixture.jpg",
        auto_download=True,
        formats=["jpg"],
    )

    report = download_auto_assets(
        _catalog(entry),
        tmp_path,
        dry_run=True,
        allow_file_urls=True,
    )

    assert report.summary() == {"dry_run": 1, "total": 1}
    assert not (tmp_path / "assets/visual/earth/fixture.jpg").exists()


def test_skips_manual_or_restricted_sources(tmp_path: Path) -> None:
    manual = AssetEntry(
        id="manual_source",
        modality="orthophoto",
        source_url="https://example.invalid/manual.jpg",
        restriction="none",
        local_cache_path="assets/visual/manual.jpg",
        auto_download=False,
    )
    restricted = AssetEntry(
        id="restricted_source",
        modality="object_reference",
        source_url="https://example.invalid/restricted.jpg",
        restriction="restricted",
        local_cache_path="assets/visual/restricted.jpg",
        auto_download=True,
    )

    report = download_auto_assets(
        _catalog(manual, restricted),
        tmp_path,
        source_ids=["manual_source", "restricted_source"],
    )

    assert report.summary() == {"skipped": 2, "total": 2}
    assert {record.reason for record in report.records} == {
        "auto_download is false",
        "restriction is restricted",
    }


def test_rejects_non_https_without_file_opt_in(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"earth imagery bytes")
    entry = AssetEntry(
        id="earth_fixture",
        modality="orthophoto",
        source_url=source.as_uri(),
        restriction="none",
        local_cache_path="assets/visual/earth/fixture.jpg",
        auto_download=True,
        formats=["jpg"],
    )

    report = download_auto_assets(_catalog(entry), tmp_path)

    assert report.has_errors
    assert report.records[0].status == "error"
    assert "unsupported source_url scheme" in report.records[0].reason
