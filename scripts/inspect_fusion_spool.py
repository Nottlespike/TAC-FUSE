#!/usr/bin/env python3
"""Redacted inspection tool for FusionSpool.

Usage:
  uv run python scripts/inspect_fusion_spool.py [--db PATH] [--limit N]

Outputs a redacted view of the spool suitable for operator debugging
without exposing sensitive fields like raw binary or GPS coordinates.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure we can import from src when invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tac_fuse.fusion_node.spool import FusionSpool

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)

def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect FusionSpool contents (redacted)")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.cwd() / "fusion_spool.db",
        help="Path to SQLite database (default: ./fusion_spool.db)",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        help="Path to JSONL side-car (defaults to <db>.jsonl)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of events shown",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only show JSONL integrity stats",
    )
    args = parser.parse_args()

    if not args.db.exists():
        logging.error("Database not found: %s", args.db)
        return 1

    spool = FusionSpool(sqlite_path=args.db, jsonl_path=args.jsonl)
    try:
        if args.stats_only:
            stats = spool.jsonl_stats()
            print(json.dumps(stats, indent=2))
            return 0

        view = spool.inspect_redacted(limit=args.limit)
        print(json.dumps(view, indent=2))
        return 0
    finally:
        spool.close()

if __name__ == "__main__":
    sys.exit(main())
