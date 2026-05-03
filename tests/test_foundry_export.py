import json

from tac_fuse.foundry_export import (
    ARTIFACT_NAMES,
    build_foundry_export,
    write_foundry_artifacts,
    write_foundry_export,
)
from tac_fuse.mission_state import MissionStateStore
from tac_fuse.replay import generate_scenario


def test_build_foundry_export_keeps_upload_boundary() -> None:
    store = MissionStateStore()
    store.create_task(title="Classify POV frame")
    store.insert_tracks(generate_scenario(frames=1)[0])

    payload = build_foundry_export(store)

    assert payload["schema"] == "tac_fuse.foundry_export.v1"
    assert payload["operator_tasks"][0]["title"] == "Classify POV frame"
    assert payload["sync_queue"][0]["status"] == "pending"
    assert payload["asset_states"]


def test_write_foundry_export(tmp_path) -> None:
    store = MissionStateStore()
    output = write_foundry_export(store, tmp_path / "foundry_export.json")

    payload = json.loads(output.read_text())
    assert payload["schema"] == "tac_fuse.foundry_export.v1"


def test_write_foundry_artifacts(tmp_path) -> None:
    store = MissionStateStore()
    store.create_task(title="Export task")
    store.create_alert("Local alert")
    store.insert_tracks(generate_scenario(frames=1)[0])

    output_dir = write_foundry_artifacts(store, tmp_path / "foundry")

    assert {path.name for path in output_dir.iterdir()} == set(ARTIFACT_NAMES)
    manifest = json.loads((output_dir / "sync_manifest.json").read_text())
    assert manifest["record_counts"]["operator_tasks.jsonl"] == 1
