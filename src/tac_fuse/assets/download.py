"""Controlled visual-asset downloader for approved Earth imagery."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from tac_fuse.assets.catalog import AssetCatalog, AssetEntry, AssetRestriction

DEFAULT_MAX_DOWNLOAD_BYTES = 120 * 1024 * 1024
DEFAULT_TIMEOUT_SEC = 45.0
_CHUNK_SIZE = 1024 * 1024


class AssetDownloadError(Exception):
    """Raised when an approved asset cannot be downloaded or verified."""


@dataclass(frozen=True)
class DownloadRecord:
    """Per-source download result."""

    source_id: str
    status: str
    local_path: str
    source_url: str = ""
    bytes_written: int = 0
    sha256: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, str | int]:
        """Return a JSON-serializable record."""
        return asdict(self)


@dataclass(frozen=True)
class DownloadReport:
    """Aggregate result for a visual-asset cache run."""

    records: tuple[DownloadRecord, ...]

    @property
    def has_errors(self) -> bool:
        """Whether any source failed."""
        return any(record.status == "error" for record in self.records)

    def summary(self) -> dict[str, int]:
        """Return compact counts by status."""
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.status] = counts.get(record.status, 0) + 1
        counts["total"] = len(self.records)
        return counts

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report."""
        return {
            "summary": self.summary(),
            "records": [record.to_dict() for record in self.records],
        }


def download_auto_assets(
    catalog: AssetCatalog,
    project_root: Path,
    *,
    source_ids: Iterable[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    allow_file_urls: bool = False,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> DownloadReport:
    """Download approved ``auto_download`` visual assets into the local cache."""
    selected = set(source_ids or [])
    found_selected: set[str] = set()
    records: list[DownloadRecord] = []

    for entry in catalog.entries:
        if selected and entry.id not in selected:
            continue
        if selected:
            found_selected.add(entry.id)

        if not entry.auto_download:
            if selected:
                records.append(_skip(entry, project_root, "auto_download is false"))
            continue

        if entry.restriction != AssetRestriction.NONE.value:
            records.append(_skip(entry, project_root, f"restriction is {entry.restriction}"))
            continue

        if not entry.source_url:
            records.append(_skip(entry, project_root, "source_url is empty"))
            continue

        try:
            records.append(
                _download_entry(
                    entry,
                    project_root,
                    force=force,
                    dry_run=dry_run,
                    allow_file_urls=allow_file_urls,
                    max_bytes=max_bytes,
                    timeout_sec=timeout_sec,
                )
            )
        except AssetDownloadError as exc:
            records.append(
                DownloadRecord(
                    source_id=entry.id,
                    status="error",
                    local_path=str(_target_path(entry, project_root)),
                    source_url=entry.source_url,
                    reason=str(exc),
                )
            )

    for missing_id in sorted(selected - found_selected):
        records.append(
            DownloadRecord(
                source_id=missing_id,
                status="error",
                local_path="",
                reason="source id not found in catalog",
            )
        )

    return DownloadReport(records=tuple(records))


def _skip(entry: AssetEntry, project_root: Path, reason: str) -> DownloadRecord:
    return DownloadRecord(
        source_id=entry.id,
        status="skipped",
        local_path=str(_target_path(entry, project_root)),
        source_url=entry.source_url,
        reason=reason,
    )


def _download_entry(
    entry: AssetEntry,
    project_root: Path,
    *,
    force: bool,
    dry_run: bool,
    allow_file_urls: bool,
    max_bytes: int,
    timeout_sec: float,
) -> DownloadRecord:
    target = _target_path(entry, project_root)
    source_max = entry.max_download_bytes or max_bytes
    _validate_url(entry.source_url, allow_file_urls=allow_file_urls)

    if target.exists() and not force:
        sha256 = _file_sha256(target)
        if entry.expected_sha256 and sha256.lower() != entry.expected_sha256.lower():
            raise AssetDownloadError(
                f"existing file sha256 mismatch: expected {entry.expected_sha256}, got {sha256}"
            )
        return DownloadRecord(
            source_id=entry.id,
            status="exists",
            local_path=str(target),
            source_url=entry.source_url,
            bytes_written=target.stat().st_size,
            sha256=sha256,
        )

    if dry_run:
        return DownloadRecord(
            source_id=entry.id,
            status="dry_run",
            local_path=str(target),
            source_url=entry.source_url,
            reason=f"would download up to {source_max} bytes",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        entry.source_url,
        headers={"User-Agent": "TAC-FUSE asset-cache/0.1"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > source_max:
                raise AssetDownloadError(
                    f"content length {declared_length} exceeds limit {source_max}"
                )
            return _write_response(entry, response, target, source_max)
    except urllib.error.URLError as exc:
        raise AssetDownloadError(f"download failed: {exc}") from exc
    except OSError as exc:
        raise AssetDownloadError(f"cache write failed: {exc}") from exc


def _write_response(
    entry: AssetEntry,
    response: object,
    target: Path,
    max_bytes: int,
) -> DownloadRecord:
    hasher = hashlib.sha256()
    bytes_written = 0
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = response.read(_CHUNK_SIZE)  # type: ignore[attr-defined]
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise AssetDownloadError(f"download exceeded limit {max_bytes} bytes")
                hasher.update(chunk)
                out.write(chunk)

        digest = hasher.hexdigest()
        if entry.expected_sha256 and digest.lower() != entry.expected_sha256.lower():
            raise AssetDownloadError(
                f"sha256 mismatch: expected {entry.expected_sha256}, got {digest}"
            )

        tmp_path.replace(target)
        return DownloadRecord(
            source_id=entry.id,
            status="downloaded",
            local_path=str(target),
            source_url=entry.source_url,
            bytes_written=bytes_written,
            sha256=digest,
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _validate_url(source_url: str, *, allow_file_urls: bool) -> None:
    parsed = urllib.parse.urlparse(source_url)
    allowed = {"https"}
    if allow_file_urls:
        allowed.add("file")
    if parsed.scheme not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise AssetDownloadError(
            f"unsupported source_url scheme '{parsed.scheme}'; allowed: {allowed_text}"
        )
    if parsed.scheme == "https" and not parsed.netloc:
        raise AssetDownloadError("source_url must include a hostname")


def _target_path(entry: AssetEntry, project_root: Path) -> Path:
    local = project_root / entry.local_cache_path
    if str(entry.local_cache_path).endswith("/") or local.suffix == "":
        parsed = urllib.parse.urlparse(entry.source_url)
        filename = Path(parsed.path).name or f"{entry.id}.bin"
        return local / filename
    return local


def _file_sha256(path: Path, block_size: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(block_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()
