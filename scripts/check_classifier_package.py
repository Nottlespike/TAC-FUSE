"""Inspect the packaged H100 SigLIP2 classifier for demo readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tac_fuse.training.model_package import (
    inspect_packaged_siglip2_package,
    load_siglip2_classifier_package,
)
from tac_fuse.vision.classifier import ModelAssetError, PackagedSigLIP2Classifier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--verify-checksums", action="store_true")
    parser.add_argument("--load-model", action="store_true")
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--device", default="CPU", choices=("CPU", "cpu", "cuda", "auto"))
    parser.add_argument("--require-package", action="store_true")
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args(argv)

    manifest = (
        load_siglip2_classifier_package(args.manifest)
        if args.manifest
        else load_siglip2_classifier_package()
    )
    package_status = inspect_packaged_siglip2_package(
        manifest,
        model_dir=args.model_dir,
        verify_checksums=args.verify_checksums,
    )
    classifier = PackagedSigLIP2Classifier(
        model_path=args.model_dir,
        manifest_path=args.manifest,
        device=args.device,
    )
    runtime_status = classifier.inspect_status()

    loaded = False
    load_error = ""
    classification = None
    if args.load_model or args.image:
        try:
            if args.image:
                classification = classifier.classify(args.image).to_dict()
            else:
                classifier.load()
            loaded = True
            runtime_status = classifier.inspect_status()
        except (
            FileNotFoundError,
            ImportError,
            ModelAssetError,
            RuntimeError,
            OSError,
            ValueError,
        ) as exc:
            load_error = str(exc)

    status = {
        "package": package_status,
        "runtime": runtime_status,
        "loaded": loaded,
        "classification": classification,
        "load_error": load_error,
    }
    print(json.dumps(status, indent=2, sort_keys=True))

    if args.require_package and not package_status["ready_for_demo"]:
        return 1
    if args.require_runtime and not runtime_status["ready"]:
        return 1
    if (args.load_model or args.image) and not loaded:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
