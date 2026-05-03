"""Inspect TAC-FUSE local ray-query runtime readiness."""

from __future__ import annotations

import argparse
import json
import sys

from tac_fuse.ray_query import inspect_ray_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-rtx", action="store_true")
    args = parser.parse_args(argv)

    status = inspect_ray_runtime(require_rtx=args.require_rtx)
    print(json.dumps(status.to_dict(), indent=2, sort_keys=True))
    if args.require_rtx and not status.accelerated:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
