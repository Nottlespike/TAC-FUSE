"""Foundry-compatible local export helpers.

LOCAL C2 STATE-FIRST GUARANTEE:
All export functions read from MissionStateStore, which persists operator commands
to local SQLite state, audit log, and outbound sync queue BEFORE any export path
can run. Exports are deterministic, offline artifacts derived from persisted state.

These functions are READ-ONLY and never trigger network I/O. They produce local
artifacts that can be handed off to enterprise systems via operator-gated sync.
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

# Valid operation types that represent a completed state-first command.
# Must stay in sync with every task operation MissionStateStore produces:
# create, update, cancel, retask, complete (via retask/complete/dispatch_command).
_COMMAND_OPS = frozenset({"create", "update", "cancel", "retask", "complete"})


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


def verify_export_readiness(store: MissionStateStore) -> dict[str, Any]:
    """Verify every operator task in the store has complete state-first proofs.

    Returns a readiness report with per-task and aggregate proof status.
    This is the export gate: callers SHOULD check readiness before including
    state in enterprise-bound artifacts.
    """
    tasks = store.list_tasks()
    task_proofs: list[dict[str, Any]] = []
    all_complete = True
    proven = 0
    unproven = 0

    for task in tasks:
        proof = store.verify_state_first("operator_task", task["id"])
        entry = {
            "task_id": task["id"],
            "title": task["title"],
            "status": task["status"],
            "proof_complete": proof["proof_complete"],
        }
        task_proofs.append(entry)
        if proof["proof_complete"]:
            proven += 1
        else:
            all_complete = False
            unproven += 1

    return {
        "ready": all_complete,
        "total_tasks": len(tasks),
        "proven": proven,
        "unproven": unproven,
        "tasks": task_proofs,
    }


def verify_sync_queue_command_integrity(store: MissionStateStore) -> dict[str, Any]:
    """Verify every sync queue entry originates from a valid command operation.

    Returns an integrity report flagging any non-command operations (which could
    indicate data that was not produced through the operator tasking path).
    """
    entries = store.list_sync_queue()
    valid = []
    invalid = []

    for entry in entries:
        if entry["operation"] in _COMMAND_OPS:
            valid.append(entry["id"])
        else:
            invalid.append({
                "id": entry["id"],
                "entity_type": entry["entity_type"],
                "operation": entry["operation"],
            })

    return {
        "integrity_ok": len(invalid) == 0,
        "valid_command_ops": len(valid),
        "non_command_ops": invalid,
    }
