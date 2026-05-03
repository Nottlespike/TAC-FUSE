"""Tests for the TAC-FUSE self-improvement task generator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml


def _load_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "self_improve.py"
    spec = importlib.util.spec_from_file_location("tac_fuse_self_improve", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


self_improve = _load_module()


def test_supporting_accelerator_language_is_allowed(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text(
        "Local C2 authority continues offline and degraded. "
        "Intel NPU object detection is optional supporting proof point after the C2 loop works.",
        encoding="utf-8",
    )

    findings = self_improve._inference_centrality_findings(tmp_path, doc, doc.read_text())

    assert findings == []


def test_npu_first_language_is_flagged(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "demo_runbook.md"
    doc.parent.mkdir()
    doc.write_text(
        "The demo centers on Intel NPU model accuracy benchmarks for object detection.",
        encoding="utf-8",
    )

    findings = self_improve._inference_centrality_findings(tmp_path, doc, doc.read_text())

    assert [finding.code for finding in findings] == ["inference-centrality"]
    assert findings[0].severity == "P1"


def test_alignment_audit_requires_problem_statement_doc(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "Problem Statement 2 local C2 command authority offline drone swarm alerts Foundry "
        "battery latency.",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "Problem Statement 2 local C2 command authority offline drone swarm alerts Foundry "
        "battery latency.",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "demo_runbook.md").write_text(
        "Problem Statement 2 local C2 command authority offline drone swarm alerts Foundry "
        "battery latency.",
        encoding="utf-8",
    )
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text(
        "local C2 command authority offline drone swarm alerts Foundry battery latency.",
        encoding="utf-8",
    )
    (tmp_path / "web" / "app.js").write_text(
        "local C2 command authority offline drone swarm alerts Foundry battery latency.",
        encoding="utf-8",
    )

    audit = self_improve.audit_alignment(tmp_path)

    assert any(finding.code == "missing-alignment-doc" for finding in audit.findings)


def test_generated_tasks_are_problem_statement_2_scoped() -> None:
    task_pack = self_improve.build_task_pack(max_tasks=3)

    assert task_pack["metadata"]["problem_statement"] == self_improve.PROBLEM_STATEMENT
    assert task_pack["metadata"]["scope"] == "contrib/TAC-FUSE/"
    assert task_pack["tasks"]
    for task in task_pack["tasks"]:
        assert task["scope"] == "contrib/TAC-FUSE/"
        assert task["validation_lane"] == "software"
        assert self_improve.PROBLEM_STATEMENT in task["prompt"]
        assert "Intel NPU availability" in task["prompt"]
        assert "Workflow:" in task["prompt"]
        assert task["metadata"]["workflow_stage"] in {
            "explore",
            "create",
            "beautify",
            "cleanup",
        }
        assert task["verify_command"].startswith("cd contrib/TAC-FUSE &&")


def test_task_pack_yaml_contains_priority_order() -> None:
    task_pack = self_improve.build_task_pack(max_tasks=2)

    parsed = yaml.safe_load(self_improve.dump_task_pack(task_pack))

    assert parsed["metadata"]["priority_order"] == [
        "Local C2 authority",
        "Disconnected resilience",
        "Drone coordination",
        "Sensor fusion and alerting",
        "3D field-C2 quantification",
        "Power/latency posture",
        "Enterprise sync boundary",
    ]
    assert parsed["metadata"]["workflow_order"] == [
        "Explore",
        "Create",
        "Beautify",
        "Cleanup",
    ]


def test_object_map_task_is_beautify_stage() -> None:
    task_pack = self_improve.build_task_pack(max_tasks=4)
    object_map_task = next(
        task
        for task in task_pack["tasks"]
        if task["metadata"]["alignment_focus"] == "object_map_quantification"
    )

    assert object_map_task["metadata"]["workflow_stage"] == "beautify"
    assert "Current stage: Beautify" in object_map_task["prompt"]
