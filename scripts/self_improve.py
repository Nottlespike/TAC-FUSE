#!/usr/bin/env python3
"""Problem-aware self-improvement task generator for TAC-FUSE.

This is intentionally narrower than AlphaHENG's root self-improvement script.
TAC-FUSE targets Problem Statement 2: Edge Deployments and Drone Operation, so
the audit and generated work stay centered on hardened-laptop local C2 under
degraded or denied connectivity. Accelerator and object-detection work is
treated as a supporting proof point, not the product thesis.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

PROBLEM_STATEMENT = "Problem Statement 2: Edge Deployments and Drone Operation"
TASK_SCOPE = "contrib/TAC-FUSE/"
GENERATED_BY = "contrib/TAC-FUSE/scripts/self_improve.py"

PRIORITY_ORDER: tuple[tuple[str, str], ...] = (
    ("local_c2_authority", "Local C2 authority"),
    ("disconnected_resilience", "Disconnected resilience"),
    ("drone_coordination", "Drone coordination"),
    ("sensor_fusion_alerting", "Sensor fusion and alerting"),
    ("object_map_quantification", "3D field-C2 quantification"),
    ("power_latency_posture", "Power/latency posture"),
    ("enterprise_sync_boundary", "Enterprise sync boundary"),
)

WORKFLOW_ORDER: tuple[tuple[str, str], ...] = (
    ("explore", "Explore"),
    ("create", "Create"),
    ("beautify", "Beautify"),
    ("cleanup", "Cleanup"),
)

ANCHOR_TERMS: dict[str, tuple[str, ...]] = {
    "local_c2_authority": (
        "local c2",
        "command-and-control",
        "command authority",
        "operator tasking",
        "operator command",
        "mission state",
        "audit",
    ),
    "disconnected_resilience": (
        "offline",
        "degraded",
        "denied",
        "disconnected",
        "local-state-only",
        "sync queue",
    ),
    "drone_coordination": (
        "drone",
        "swarm",
        "vehicle",
        "retask",
        "deconflict",
        "route conflict",
    ),
    "sensor_fusion_alerting": (
        "sensor",
        "fusion",
        "rf",
        "video",
        "alert",
        "prioritized",
    ),
    "object_map_quantification": (
        "3d field view",
        "field c2 view",
        "local cue pass",
        "priority contacts",
        "quantified",
        "detector",
        "detectionconfidence",
        "range and altitude",
    ),
    "power_latency_posture": (
        "power",
        "battery",
        "latency",
        "backpack",
        "lightweight",
        "bounded",
    ),
    "enterprise_sync_boundary": (
        "foundry",
        "maven",
        "export",
        "upload",
        "deferred",
        "external sync",
    ),
}

CRITICAL_SURFACES: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "docs/demo_runbook.md",
    "docs/problem_statement_alignment.md",
    "web/index.html",
    "web/app.js",
)

TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".toml", ".yaml", ".yml"}
SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}
INFERENCE_TERMS = (
    "intel npu",
    "npu",
    "siglip",
    "openvino",
    "object detection",
    "model accuracy",
    "benchmark",
)
CENTRALITY_RISK_TERMS = (
    "availability",
    "benchmark",
    "center",
    "centers",
    "centered",
    "core",
    "focus",
    "gate",
    "main",
    "model accuracy",
    "must",
    "optimize",
    "primary",
    "require",
    "required",
    "requires",
)
SUPPORTING_CONTEXT_TERMS = (
    "do not",
    "supporting",
    "optional",
    "not the main",
    "not the core",
    "not the application",
    "not run a model",
    "must not require",
    "not require",
    "after the c2",
    "proof point",
    "graceful",
    "fallback",
    "without intel npu",
    "not required",
    "unavailable",
)
INFERENCE_OWNED_PATHS = (
    "configs/training/",
    "scripts/check_npu_runtime.py",
    "src/tac_fuse/npu_siglip.py",
    "tests/test_npu_siglip.py",
)
OBJECT_MAP_REQUIRED_TERMS: dict[str, tuple[str, ...]] = {
    "web/app.js": (
        "3d field view",
        "pov_map_anchor",
        "projectpovmappoint",
        "sceneclasstargets",
        "route_guard_path",
        "route guard corridor",
        "detectionconfidence",
        "range and altitude labels",
        "wheeled vehicle",
        "rf source",
    ),
    "web/index.html": (
        "3d field view",
        "power",
        "sync",
    ),
    "tests/visual/tac-fuse.spec.js": (
        "3d field view",
        "target-label",
        "metric-strip",
    ),
}
POV_TERRAIN_DRIFT_TERMS = (
    "drawpovlocalterrain",
    "drawpovcorridor",
)


@dataclass(frozen=True)
class Finding:
    """One problem-statement alignment issue."""

    code: str
    severity: str
    path: str
    message: str
    line: int | None = None
    focus: str = "local_c2_authority"

    def label(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"[{self.severity}] {self.code} {location} - {self.message}"


@dataclass
class AlignmentAudit:
    """Collected alignment scan results."""

    root: Path
    coverage: dict[str, list[str]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    ruff_returncode: int | None = None
    ruff_output: str = ""

    @property
    def ok(self) -> bool:
        return not self.findings and self.ruff_returncode in (None, 0)

    def finding_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts


@dataclass(frozen=True)
class TaskBlueprint:
    """A reusable TAC-FUSE improvement task."""

    name: str
    priority: str
    phase: str
    title: str
    focus: str
    body: str
    verify_command: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = _normalise(text)
    return any(term in lowered for term in terms)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _is_inference_owned_path(relative_path: str) -> bool:
    return relative_path in INFERENCE_OWNED_PATHS or any(
        relative_path.startswith(prefix) for prefix in INFERENCE_OWNED_PATHS if prefix.endswith("/")
    )


def _line_context(lines: list[str], index: int, radius: int = 2) -> str:
    start = max(0, index - radius)
    stop = min(len(lines), index + radius + 1)
    return "\n".join(lines[start:stop])


def _inference_centrality_findings(root: Path, path: Path, text: str) -> list[Finding]:
    relative_path = _relative(path, root)
    if _is_inference_owned_path(relative_path):
        return []

    findings: list[Finding] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        lowered = line.lower()
        if not any(term in lowered for term in INFERENCE_TERMS):
            continue
        if "npu-label" in lowered:
            continue
        context = _line_context(lines, index)
        if not _has_any(context, CENTRALITY_RISK_TERMS):
            continue
        if _has_any(context, SUPPORTING_CONTEXT_TERMS):
            continue
        if _has_any(context, ANCHOR_TERMS["local_c2_authority"]) and _has_any(
            context, ANCHOR_TERMS["disconnected_resilience"]
        ):
            continue
        findings.append(
            Finding(
                code="inference-centrality",
                severity="P1",
                path=relative_path,
                line=index + 1,
                message=(
                    "Inference or accelerator language lacks nearby optional/supporting "
                    "context; keep the thesis on local C2 continuity."
                ),
                focus="local_c2_authority",
            )
        )
    return findings


def _object_map_findings(root: Path, path: Path, text: str) -> list[Finding]:
    relative_path = _relative(path, root)
    required_terms = OBJECT_MAP_REQUIRED_TERMS.get(relative_path)
    if not required_terms:
        return []

    findings: list[Finding] = []
    normalised = _normalise(text)
    missing = [term for term in required_terms if term not in normalised]
    if missing:
        findings.append(
            Finding(
                code="object-map-quantification-drift",
                severity="P1",
                path=relative_path,
                message=(
                    "3D field-C2 quantification guard is missing terms: "
                    + ", ".join(missing)
                ),
                focus="object_map_quantification",
            )
        )

    if relative_path == "web/app.js":
        for term in POV_TERRAIN_DRIFT_TERMS:
            if term in normalised:
                findings.append(
                    Finding(
                        code="pov-terrain-camera-drift",
                        severity="P1",
                        path=relative_path,
                        message=(
                            "Operator POV drifted back toward a forward terrain/corridor "
                            "camera; keep it as a 3D field C2 view with quantifiable contacts."
                        ),
                        focus="object_map_quantification",
                    )
                )
                break

    return findings


def audit_alignment(root: Path | None = None) -> AlignmentAudit:
    root = (root or project_root()).resolve()
    audit = AlignmentAudit(root=root)

    alignment_doc = root / "docs" / "problem_statement_alignment.md"
    if not alignment_doc.exists():
        audit.findings.append(
            Finding(
                code="missing-alignment-doc",
                severity="P0",
                path="docs/problem_statement_alignment.md",
                message="Create this file and make it the local thesis for TAC-FUSE.",
                focus="local_c2_authority",
            )
        )

    for surface in CRITICAL_SURFACES:
        path = root / surface
        if not path.exists():
            audit.findings.append(
                Finding(
                    code="missing-critical-surface",
                    severity="P1",
                    path=surface,
                    message="Critical operator-facing surface is missing.",
                    focus="local_c2_authority",
                )
            )
            continue

        text = _read_text(path)
        surface_hits: list[str] = []
        for focus, terms in ANCHOR_TERMS.items():
            if _has_any(text, terms):
                surface_hits.append(focus)
        audit.coverage[surface] = surface_hits

        if surface in {"README.md", "AGENTS.md", "docs/demo_runbook.md"} and (
            "problem statement 2" not in text.lower()
        ):
            audit.findings.append(
                Finding(
                    code="missing-problem-statement",
                    severity="P1",
                    path=surface,
                    message=f"Name {PROBLEM_STATEMENT} explicitly.",
                    focus="local_c2_authority",
                )
            )

        required = {"local_c2_authority", "disconnected_resilience"}
        missing_required = sorted(required.difference(surface_hits))
        if missing_required:
            audit.findings.append(
                Finding(
                    code="missing-core-anchor",
                    severity="P1",
                    path=surface,
                    message="Missing core alignment anchors: " + ", ".join(missing_required),
                    focus=missing_required[0],
                )
            )

        if len(surface_hits) < 3:
            audit.findings.append(
                Finding(
                    code="thin-priority-coverage",
                    severity="P2",
                    path=surface,
                    message=(
                        "Surface should connect local C2, denial resilience, drone "
                        "coordination, alerts, power/latency, or sync boundary."
                    ),
                    focus="local_c2_authority",
                )
            )

    for path in iter_text_files(root):
        relative_path = _relative(path, root)
        if (
            relative_path not in CRITICAL_SURFACES
            and not relative_path.startswith("docs/")
            and relative_path not in OBJECT_MAP_REQUIRED_TERMS
        ):
            continue
        text = _read_text(path)
        audit.findings.extend(_inference_centrality_findings(root, path, text))
        audit.findings.extend(_object_map_findings(root, path, text))
        audit.files_scanned += 1

    return audit


def run_ruff(root: Path, targets: list[str]) -> tuple[int, str]:
    command = ["uv", "run", "ruff", "check", *targets]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        return 127, "uv executable not found"
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return 124, output.strip() or "ruff timed out"
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output


def run_audit(
    *,
    root: Path | None = None,
    skip_ruff: bool = False,
    ruff_targets: list[str] | None = None,
) -> AlignmentAudit:
    root = (root or project_root()).resolve()
    audit = audit_alignment(root)
    if not skip_ruff:
        audit.ruff_returncode, audit.ruff_output = run_ruff(
            root, ruff_targets or ["scripts/self_improve.py", "src", "tests"]
        )
    return audit


def default_backlog() -> list[TaskBlueprint]:
    return [
        TaskBlueprint(
            name="tac-fuse-p0-local-c2-state-first",
            priority="P0",
            phase="explore",
            title="Make local C2 state writes the first-class proof path",
            focus="local_c2_authority",
            body=(
                "Audit the operator-command path and make sure every tasking or retasking "
                "action persists to local mission state, audit log, and outbound sync queue "
                "before any enterprise export/upload path can run. Keep the implementation "
                "offline and deterministic."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run pytest "
                "tests/test_mission_state.py tests/test_connectivity.py -q"
            ),
        ),
        TaskBlueprint(
            name="tac-fuse-p0-denied-link-swarm-control",
            priority="P0",
            phase="create",
            title="Prove a single operator can control the swarm while denied",
            focus="drone_coordination",
            body=(
                "Strengthen the web demo, runbook, or local replay fixtures so a single "
                "operator can task and retask multiple drones while OFFLINE/DEGRADED. "
                "The proof should show local state, map/replay context, alerts, and queued "
                "enterprise sync continuing without Foundry, Maven, internet, or central C2."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run pytest "
                "tests/test_mission_state.py tests/test_connectivity.py -q"
            ),
        ),
        TaskBlueprint(
            name="tac-fuse-p1-local-alert-prioritization",
            priority="P1",
            phase="create",
            title="Turn local sensor and geometry events into prioritized alerts",
            focus="sensor_fusion_alerting",
            body=(
                "Improve the local sensor/fusion path so video, RF, position, stale-feed, "
                "restricted-zone, route-conflict, or battery observations become prioritized "
                "operator alerts without cloud infrastructure. Object detection may be used "
                "only as an optional source of cue data after the alert path works."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run pytest "
                "tests/test_local_sensor_ingest_bus.py tests/test_sensor_models.py "
                "tests/test_mission_state.py -q"
            ),
        ),
        TaskBlueprint(
            name="tac-fuse-p1-3d-object-map-quantification",
            priority="P1",
            phase="beautify",
            title="Keep the operator surface on 3D field-C2 quantification",
            focus="object_map_quantification",
            body=(
                "Maintain the selected-feed surface as a 3D field C2 view with "
                "detector-visible priority contacts, class labels, confidence, range, "
                "and altitude quantification. Do not regress to a forward terrain/corridor camera. "
                "NPU or MPU detection can be represented as a supporting local cue pass, "
                "but local C2 continuity remains the product thesis."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run python scripts/self_improve.py "
                "audit --skip-ruff --fail-on-findings && npm run test:visual"
            ),
        ),
        TaskBlueprint(
            name="tac-fuse-p1-enterprise-sync-boundary",
            priority="P1",
            phase="create",
            title="Keep Maven and Foundry behind a deferred sync boundary",
            focus="enterprise_sync_boundary",
            body=(
                "Verify and tighten the export/upload boundary: exports can be created from "
                "local state while disconnected, but uploads must be gated by ONLINE mode and "
                "credential presence. Missing Foundry or Maven configuration must never block "
                "local operator C2."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run pytest "
                "tests/test_connectivity.py tests/test_maven_foundry_config.py -q"
            ),
        ),
        TaskBlueprint(
            name="tac-fuse-p2-power-latency-posture",
            priority="P2",
            phase="beautify",
            title="Make laptop/backpack power and latency constraints visible",
            focus="power_latency_posture",
            body=(
                "Add a lightweight operator-facing or runbook-visible power/latency posture: "
                "bounded local workloads, CPU fallback, battery/backpack assumptions, and "
                "what work is safe to run during denied connectivity. Avoid model benchmark "
                "charts as the center of the demo."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run python scripts/self_improve.py "
                "audit --skip-ruff --fail-on-findings"
            ),
        ),
        TaskBlueprint(
            name="tac-fuse-p2-accelerator-supporting-role",
            priority="P2",
            phase="cleanup",
            title="Keep NPU, MPU, GPU, and RTX paths in a supporting role",
            focus="local_c2_authority",
            body=(
                "Audit docs, UI copy, and scripts so accelerator and object-detection paths "
                "are clearly optional supporting capabilities. The accepted thesis is: local "
                "C2 continues on the hardened laptop even when inference hardware, model "
                "downloads, or cloud services are unavailable."
            ),
            verify_command=(
                "cd contrib/TAC-FUSE && uv run python scripts/self_improve.py "
                "audit --skip-ruff --fail-on-findings"
            ),
        ),
    ]


def _prompt_for_blueprint(blueprint: TaskBlueprint) -> str:
    priority_text = "\n".join(
        f"{index}. {label}" for index, (_key, label) in enumerate(PRIORITY_ORDER, start=1)
    )
    workflow_text = "\n".join(
        f"{index}. {label}" for index, (_key, label) in enumerate(WORKFLOW_ORDER, start=1)
    )
    workflow_labels = dict(WORKFLOW_ORDER)
    return f"""IMPORTANT - TAC-FUSE targets {PROBLEM_STATEMENT}.

Working directory: AlphaHENG repo root.
Scope: {TASK_SCOPE}

Workflow:
{workflow_text}

Priority order:
{priority_text}

Current stage: {workflow_labels[blueprint.phase]}

Task: {blueprint.title}

{blueprint.body}

Guardrails:
- Do not make Intel NPU availability, model accuracy, or object detection the center of the work.
- If object detection is shown, render quantifiable objects on a local 3D map rather than
  a forward terrain/corridor camera.
- Core behavior must remain offline-testable and must not require Foundry, Maven, OpenVINO,
  internet, Hugging Face downloads, RTX hardware, or an Intel NPU.
- If you touch behavior, add or update focused offline tests.
- Update contrib/TAC-FUSE/CHANGELOG.md for behavior, interface, demo workflow, dependency,
  or validation changes.
"""


def task_from_blueprint(blueprint: TaskBlueprint) -> dict[str, Any]:
    return {
        "name": blueprint.name,
        "priority": blueprint.priority,
        "scope": TASK_SCOPE,
        "validation_lane": "software",
        "prompt": _prompt_for_blueprint(blueprint),
        "verify_command": blueprint.verify_command,
        "metadata": {
            "generated_by": GENERATED_BY,
            "problem_statement": PROBLEM_STATEMENT,
            "workflow_stage": blueprint.phase,
            "alignment_focus": blueprint.focus,
        },
    }


def _phase_for_finding(finding: Finding) -> str:
    if finding.focus == "object_map_quantification":
        return "beautify"
    if finding.code in {"inference-centrality", "pov-terrain-camera-drift"}:
        return "cleanup"
    if finding.code.startswith("missing"):
        return "explore"
    return "create"


def task_from_finding(finding: Finding) -> dict[str, Any]:
    suffix = finding.code.replace("_", "-")
    path_slug = finding.path.replace("/", "-").replace(".", "-").strip("-")
    name = f"tac-fuse-align-{suffix}-{path_slug}"[:96]
    phase = _phase_for_finding(finding)
    workflow_text = "\n".join(
        f"{index}. {label}" for index, (_key, label) in enumerate(WORKFLOW_ORDER, start=1)
    )
    workflow_labels = dict(WORKFLOW_ORDER)
    prompt = f"""IMPORTANT - TAC-FUSE targets {PROBLEM_STATEMENT}.

Working directory: AlphaHENG repo root.
Scope: {TASK_SCOPE}

Workflow:
{workflow_text}

Current stage: {workflow_labels[phase]}

Fix this alignment finding:
{finding.label()}

Keep the product thesis on hardened-laptop local C2 under degraded or denied connectivity.
Accelerator, MPU/NPU/GPU/RTX, and object-detection language must remain optional and supporting.

Guardrails:
- Do not make Intel NPU availability, model accuracy, or object detection the center of the work.
- If object detection is shown, render quantifiable objects on a local 3D map rather than
  a forward terrain/corridor camera.
- Core behavior must remain offline-testable and must not require Foundry, Maven, OpenVINO,
  internet, Hugging Face downloads, RTX hardware, or an Intel NPU.

Update focused docs, UI copy, code, or tests as needed. If this changes behavior, update
contrib/TAC-FUSE/CHANGELOG.md.
"""
    return {
        "name": name,
        "priority": finding.severity,
        "scope": TASK_SCOPE,
        "validation_lane": "software",
        "prompt": prompt,
        "verify_command": (
            "cd contrib/TAC-FUSE && uv run python scripts/self_improve.py "
            "audit --skip-ruff --fail-on-findings"
        ),
        "metadata": {
            "generated_by": GENERATED_BY,
            "problem_statement": PROBLEM_STATEMENT,
            "workflow_stage": phase,
            "alignment_focus": finding.focus,
            "finding_code": finding.code,
            "finding_path": finding.path,
        },
    }


def build_task_pack(
    *,
    root: Path | None = None,
    max_tasks: int = 8,
    include_backlog: bool = True,
) -> dict[str, Any]:
    root = (root or project_root()).resolve()
    audit = audit_alignment(root)

    tasks: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for finding in audit.findings:
        task = task_from_finding(finding)
        name = task["name"]
        if name in seen_names:
            continue
        tasks.append(task)
        seen_names.add(name)
        if len(tasks) >= max_tasks:
            break

    if include_backlog and len(tasks) < max_tasks:
        for blueprint in default_backlog():
            task = task_from_blueprint(blueprint)
            name = task["name"]
            if name in seen_names:
                continue
            tasks.append(task)
            seen_names.add(name)
            if len(tasks) >= max_tasks:
                break

    return {
        "metadata": {
            "generated_by": GENERATED_BY,
            "generated_at": datetime.now(UTC).isoformat(),
            "problem_statement": PROBLEM_STATEMENT,
            "scope": TASK_SCOPE,
            "workflow_order": [label for _key, label in WORKFLOW_ORDER],
            "priority_order": [label for _key, label in PRIORITY_ORDER],
            "alignment_findings": len(audit.findings),
        },
        "tasks": tasks,
    }


def dump_task_pack(task_pack: dict[str, Any]) -> str:
    return yaml.safe_dump(task_pack, sort_keys=False, width=100)


def print_audit(audit: AlignmentAudit) -> None:
    print(f"TAC-FUSE self-improvement audit for {PROBLEM_STATEMENT}")
    print(f"Root: {audit.root}")
    print(f"Files scanned: {audit.files_scanned}")
    print()
    print("Priority coverage on critical surfaces:")
    for surface in CRITICAL_SURFACES:
        hits = audit.coverage.get(surface, [])
        print(f"  {surface}: {len(hits)}/{len(PRIORITY_ORDER)} anchors")
        if hits:
            print("    " + ", ".join(hits))

    print()
    if audit.findings:
        print("Alignment findings:")
        for finding in audit.findings:
            print(f"  {finding.label()}")
    else:
        print("Alignment findings: none")

    if audit.ruff_returncode is not None:
        print()
        print(f"Ruff: {'passed' if audit.ruff_returncode == 0 else 'failed'}")
        if audit.ruff_output:
            print(audit.ruff_output)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit Problem Statement 2 alignment")
    audit_parser.add_argument("--skip-ruff", action="store_true", help="Only run alignment checks")
    audit_parser.add_argument(
        "--ruff-target",
        action="append",
        default=None,
        help="Ruff target to check; can be passed multiple times",
    )
    audit_parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Exit nonzero when alignment findings are present",
    )

    generate_parser = subparsers.add_parser(
        "generate", help="Generate AlphaHENG-compatible TAC-FUSE improvement tasks"
    )
    generate_parser.add_argument(
        "--output",
        default="tasks/self_improve_tasks.yaml",
        help="Output path inside contrib/TAC-FUSE unless absolute",
    )
    generate_parser.add_argument("--max-tasks", type=int, default=8)
    generate_parser.add_argument("--dry-run", action="store_true")
    generate_parser.add_argument(
        "--no-backlog",
        action="store_true",
        help="Only generate tasks for current alignment findings",
    )

    summary_parser = subparsers.add_parser("summary", help="Print compact alignment summary")
    summary_parser.add_argument("--skip-ruff", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    root = project_root()

    if args.command == "audit":
        audit = run_audit(
            root=root,
            skip_ruff=args.skip_ruff,
            ruff_targets=args.ruff_target,
        )
        print_audit(audit)
        if args.fail_on_findings and audit.findings:
            return 1
        if audit.ruff_returncode not in (None, 0):
            return audit.ruff_returncode
        return 0

    if args.command == "summary":
        audit = run_audit(root=root, skip_ruff=args.skip_ruff)
        counts = audit.finding_summary()
        print(f"{PROBLEM_STATEMENT}")
        print(f"findings={len(audit.findings)} files_scanned={audit.files_scanned}")
        if counts:
            print(" ".join(f"{severity}={count}" for severity, count in sorted(counts.items())))
        return 0 if audit.ok else 1

    if args.command == "generate":
        task_pack = build_task_pack(
            root=root,
            max_tasks=args.max_tasks,
            include_backlog=not args.no_backlog,
        )
        yaml_text = dump_task_pack(task_pack)
        if args.dry_run:
            print(yaml_text)
            return 0

        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml_text, encoding="utf-8")
        print(f"Wrote {len(task_pack['tasks'])} task(s) to {output}")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
