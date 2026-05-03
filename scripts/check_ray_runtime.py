"""Inspect TAC-FUSE local ray-query runtime readiness.

This script is optional.  Core TAC-FUSE functionality (local C2, sensor
fusion, alerting, drone coordination) works on CPU-only hardware.  The
RTX/CUDA acceleration path is a supporting capability that reduces latency
for spatial queries when a compatible GPU and CUDA drivers are present.
"""

from __future__ import annotations

import argparse
import json
import sys

from tac_fuse.ray_query import inspect_ray_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-rtx", action="store_true",
        help="Exit non-zero if no RTX/CUDA runtime is available.  Omit this "
             "flag to simply report readiness.  Core C2 does NOT depend on RTX.",
    )
    args = parser.parse_args(argv)

    status = inspect_ray_runtime(require_rtx=args.require_rtx)
    print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
    if args.require_rtx and not status.accelerated:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
