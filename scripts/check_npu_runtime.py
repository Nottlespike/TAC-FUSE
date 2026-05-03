"""Inspect TAC-FUSE Intel NPU SigLIP2 runtime readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tac_fuse.npu_siglip import IntelNPUSigLIP2Adapter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--require-npu", action="store_true")
    args = parser.parse_args(argv)

    adapter = IntelNPUSigLIP2Adapter(model_dir=args.model_dir, device=args.device)
    status = adapter.inspect_runtime()
    print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
    if args.require_npu and not status.ready:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
