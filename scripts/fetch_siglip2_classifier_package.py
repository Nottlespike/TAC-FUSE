"""Fetch the TAC-FUSE packaged SigLIP2 classifier from Hugging Face.

The normal path is the Hugging Face CLI. A small HTTP fallback is provided for
the single large safetensors file because Xet/CAS transfers can stall before
writing bytes in some locked-down environments.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from tac_fuse.training.model_package import (
    inspect_packaged_siglip2_package,
    load_siglip2_classifier_package,
    packaged_siglip2_model_dir,
)

LARGE_FILE = "backbone/model.safetensors"


class _StripCrossHostAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlparse(req.full_url).netloc
        new_host = urllib.parse.urlparse(newurl).netloc
        if old_host != new_host:
            for name in ("Authorization", "authorization"):
                redirected.headers.pop(name, None)
                redirected.unredirected_hdrs.pop(name, None)
        return redirected


def _manifest(args: argparse.Namespace) -> dict[str, Any]:
    return load_siglip2_classifier_package(args.manifest) if args.manifest else load_siglip2_classifier_package()


def _repo_id(manifest: dict[str, Any], override: str | None) -> str:
    if override:
        return override
    repo_id = manifest.get("hub", {}).get("repo_id")
    if not repo_id:
        raise SystemExit("Model package manifest is missing hub.repo_id")
    return str(repo_id)


def _revision(manifest: dict[str, Any], override: str | None) -> str:
    return str(override or manifest.get("hub", {}).get("revision", "main"))


def _model_dir(manifest: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        return override
    return packaged_siglip2_model_dir(manifest)


def _print_status(status: dict[str, Any]) -> None:
    print(json.dumps(status, indent=2, sort_keys=True))


def _hf_download(
    *,
    repo_id: str,
    revision: str,
    local_dir: Path,
    include: str | None = None,
    exclude: str | None = None,
    force: bool = False,
    timeout: int | None = None,
) -> bool:
    if shutil.which("hf") is None:
        raise SystemExit("Hugging Face CLI `hf` was not found on PATH")

    command = [
        "hf",
        "download",
        repo_id,
        "--revision",
        revision,
        "--local-dir",
        str(local_dir),
        "--max-workers",
        "1",
    ]
    if include:
        command.extend(["--include", include])
    if exclude:
        command.extend(["--exclude", exclude])
    if force:
        command.append("--force-download")

    try:
        completed = subprocess.run(command, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(
            f"[WARN] HF CLI download timed out after {timeout}s: {' '.join(command)}",
            file=sys.stderr,
        )
        return False
    return completed.returncode == 0


def _hf_token() -> str:
    for name in ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value

    try:
        completed = subprocess.run(
            ["hf", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit("Hugging Face CLI `hf` was not found on PATH") from exc

    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        raise SystemExit("No Hugging Face token found; run `hf auth login` first")
    return token


def _direct_download_large_file(
    *,
    repo_id: str,
    revision: str,
    local_dir: Path,
    timeout: int,
    chunk_size: int,
) -> None:
    token = _hf_token()
    target = local_dir / LARGE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp")
    url = f"https://huggingface.co/{repo_id}/resolve/{revision}/{LARGE_FILE}"
    opener = urllib.request.build_opener(_StripCrossHostAuthRedirect)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "tac-fuse-model-fetch/1.0",
        },
    )

    started = time.time()
    downloaded = 0
    last_report = 0
    with opener.open(request, timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        print(f"[INFO] Downloading {LARGE_FILE}: expected {total or 'unknown'} bytes")
        with tmp.open("wb") as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded - last_report >= 128 * 1024 * 1024:
                    last_report = downloaded
                    print(f"[INFO] Downloaded {downloaded} bytes")

    tmp.replace(target)
    elapsed = time.time() - started
    print(f"[INFO] Wrote {target} ({downloaded} bytes) in {elapsed:.1f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--repo-id", default=None)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--check", action="store_true", help="Inspect local package only.")
    parser.add_argument("--verify-checksums", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-cli-large-file", action="store_true")
    parser.add_argument("--no-direct-fallback", action="store_true")
    parser.add_argument("--cli-large-timeout", type=int, default=180)
    parser.add_argument("--http-timeout", type=int, default=60)
    parser.add_argument("--chunk-size", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args(argv)

    manifest = _manifest(args)
    repo_id = _repo_id(manifest, args.repo_id)
    revision = _revision(manifest, args.revision)
    model_dir = _model_dir(manifest, args.model_dir)

    if not args.check:
        model_dir.mkdir(parents=True, exist_ok=True)
        small_files_ok = _hf_download(
            repo_id=repo_id,
            revision=revision,
            local_dir=model_dir,
            exclude=LARGE_FILE,
            force=args.force,
        )
        if not small_files_ok:
            return 1

        large_file_ok = False
        if not args.skip_cli_large_file:
            large_file_ok = _hf_download(
                repo_id=repo_id,
                revision=revision,
                local_dir=model_dir,
                include=LARGE_FILE,
                force=args.force,
                timeout=args.cli_large_timeout,
            )
        if not large_file_ok and not args.no_direct_fallback:
            _direct_download_large_file(
                repo_id=repo_id,
                revision=revision,
                local_dir=model_dir,
                timeout=args.http_timeout,
                chunk_size=args.chunk_size,
            )

    status = inspect_packaged_siglip2_package(
        manifest,
        model_dir=model_dir,
        verify_checksums=args.verify_checksums,
    )
    _print_status(status)
    return 0 if status["ready_for_demo"] else 1


if __name__ == "__main__":
    sys.exit(main())
