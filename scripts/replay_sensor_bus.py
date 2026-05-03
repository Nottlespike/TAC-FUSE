#!/usr/bin/env python3
"""Replay recorded sensor events from a JSONL file into the local ingest bus.

Usage:
    uv run python scripts/replay_sensor_bus.py <events.jsonl> [--max-staleness 300]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src is importable when run as a script.
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from tac_fuse.fusion_node.ingest import IngestBus  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Replay sensor events from JSONL into the local ingest bus."
    )
    parser.add_argument("jsonl_path", type=Path, help="Path to JSONL event log")
    parser.add_argument(
        "--max-staleness",
        type=float,
        default=300.0,
        help="Max event age in seconds before rejection (0 to disable, default: 300)",
    )
    args = parser.parse_args(argv)

    jsonl_path: Path = args.jsonl_path
    if not jsonl_path.is_file():
        print(f"Error: {jsonl_path} not found", file=sys.stderr)
        sys.exit(1)

    bus = IngestBus(max_staleness_s=args.max_staleness)
    accepted = bus.replay_jsonl(jsonl_path)

    print(f"Replayed {jsonl_path.name}")
    print(f"  accepted : {len(accepted)}")
    print(f"  rejected : {bus.rejection_count()}")

    for event in accepted:
        print(f"  [{event.source}] {event.source_id} seq={event.seq}")


if __name__ == "__main__":
    main()
