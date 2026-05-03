from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _task_pack() -> dict:
    return yaml.safe_load((ROOT / "tasks" / "alpha_test_polish_tasks.yaml").read_text())


def test_alpha_test_pack_keeps_accelerator_contracts_explicit() -> None:
    task_pack = _task_pack()
    metadata = task_pack["metadata"]

    assert metadata["rtx_pathing_required"] is True
    assert metadata["strix_npu_zero_shot_required"] is True
    assert metadata["trained_model_ready"] is True
    assert metadata["playwright_visual_required"] is True


def test_alpha_test_pack_covers_required_gates() -> None:
    task_pack = _task_pack()
    gates = {task["metadata"]["alpha_gate"] for task in task_pack["tasks"]}

    assert {
        "Route Guard C2",
        "Visual Polish",
        "RTX Pathing",
        "NPU Zero-Shot Labels",
        "Trained Model Readiness",
        "Scenario Portfolio",
    } <= gates


def test_alpha_test_pack_points_at_real_local_validation() -> None:
    task_pack = _task_pack()
    commands = "\n".join(task["verify_command"] for task in task_pack["tasks"])

    assert "tests/test_ray_query.py" in commands
    assert "tests/test_zero_shot_vision.py" in commands
    assert "tests/test_npu_trainer_int8.py" in commands
    assert "npm run test:visual" in commands


def test_alpha_test_plan_names_handoff_artifact() -> None:
    plan_text = (ROOT / "docs" / "alpha_test_plan.md").read_text()

    assert "tasks/alpha_test_polish_tasks.yaml" in plan_text
    assert "RTX ray-tracing cores" in plan_text
    assert "zero-shot labeler" in plan_text
    assert "trained classifiers" in plan_text
    assert "Automatic corridor guard" in plan_text
    assert "separate tab" in plan_text
    assert "Replan Route" not in plan_text
