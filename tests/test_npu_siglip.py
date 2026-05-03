from pathlib import Path

from tac_fuse.npu_siglip import MODEL_ID, IntelNPUSigLIP2Adapter
from tac_fuse.pov import project_tracks_to_pov
from tac_fuse.replay import generate_scenario


def test_npu_status_is_safe_without_model(tmp_path: Path) -> None:
    adapter = IntelNPUSigLIP2Adapter(model_dir=tmp_path)
    status = adapter.inspect_runtime()

    assert status.model_id == MODEL_ID
    assert not status.model_present
    assert not status.ready
    assert str(tmp_path) in status.reason


def test_emulated_classification_uses_pov_condition() -> None:
    frame = project_tracks_to_pov(generate_scenario(frames=7)[6])
    result = IntelNPUSigLIP2Adapter(device="CPU").classify_emulated(frame)

    assert result.emulated
    assert result.device == "CPU"
    assert result.scores[0].label == result.top_label
    assert result.scores[0].score >= 0.7


def test_export_instructions_name_model_and_npu() -> None:
    instructions = IntelNPUSigLIP2Adapter().export_instructions()

    assert MODEL_ID in instructions
    assert "OpenVINO" in instructions
    assert "NPU" in instructions
