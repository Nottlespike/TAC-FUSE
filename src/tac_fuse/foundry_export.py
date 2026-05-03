"""Foundry-compatible local export helpers.

LOCAL C2 STATE-FIRST GUARANTEE:
All export functions read from MissionStateStore, which persists operator commands
to local SQLite state, audit log, and outbound sync queue BEFORE any export path
can run. Exports are deterministic, offline artifacts derived from persisted state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import demo_conflicts, generate_scenario

ARTIFACT_NAMES = (
    "mission_events.jsonl",
    "asset_states.jsonl",
    "operator_tasks.jsonl",
    "alerts.jsonl",
    "sync_manifest.json",
)


def build_foundry_export(store: MissionStateStore) -> dict[str, Any]:
    scenario = generate_scenario()
    return {
        "schema": "tac_fuse.foundry_export.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "operator_tasks": store.list_tasks(),
        "sync_queue": store.list_sync_queue(),
        "mission_events": store.list_audit_events(),
        "alerts": store.list_alerts(),
        "route_conflicts": [conflict.to_dict() for conflict in demo_conflicts(scenario)],
        "asset_states": store.list_asset_states(),
        "asset_tracks": [[track.to_dict() for track in frame] for frame in scenario],
    }


def write_foundry_export(store: MissionStateStore, output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix != ".json":
        return write_foundry_artifacts(store, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_foundry_export(store), indent=2, sort_keys=True) + "\n")
    return path


def write_foundry_artifacts(store: MissionStateStore, output_dir: str | Path) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = build_foundry_export(store)
    artifacts = {
        "mission_events.jsonl": payload["mission_events"],
        "asset_states.jsonl": payload["asset_states"],
        "operator_tasks.jsonl": payload["operator_tasks"],
        "alerts.jsonl": payload["alerts"],
    }
    for name, rows in artifacts.items():
        _write_jsonl(directory / name, rows)

    manifest = {
        "schema": "tac_fuse.sync_manifest.v1",
        "generated_at": payload["generated_at"],
        "local_node_id": "tac-fuse-local",
        "schema_versions": {
            "mission_events": "v1",
            "asset_states": "v1",
            "operator_tasks": "v1",
            "alerts": "v1",
        },
        "record_counts": {name: len(rows) for name, rows in artifacts.items()},
        "sync_item_ids": [item["id"] for item in payload["sync_queue"]],
    }
    (directory / "sync_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return directory


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
