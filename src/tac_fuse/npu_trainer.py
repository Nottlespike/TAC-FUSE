"""Optional INT8 SigLIP2 trainer and OpenVINO NPU deployment scaffold.

This module provides optional accelerator support for TAC-FUSE vision workloads.
It is NOT required for core C2 functionality. The local command node remains
fully operational on CPU alone — without NPU hardware, OpenVINO, model downloads,
or internet access. Use this module only when accelerator hardware is available
and you want to offload inference for improved throughput or latency.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tac_fuse.qat_data import prioritized_datasets
from tac_fuse.training.hpo_config import default_hpo_config
from tac_fuse.training.siglip2_config import SigLIP2INT8Config


@dataclass(frozen=True, slots=True)
class NPUProbeResult:
    """OpenVINO NPU visibility and compile probe result."""

    openvino_version: str | None
    available_devices: tuple[str, ...]
    npu_name: str | None
    optimization_capabilities: tuple[str, ...]
    driver_version: str | None
    compiler_version: str | None
    compile_ok: bool | None = None
    compile_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def openvino_env(config: SigLIP2INT8Config | None = None) -> dict[str, str]:
    """Return the host Intel NPU Level Zero environment when present."""

    config = config or SigLIP2INT8Config()
    env = dict(os.environ)
    if config.level_zero_alt_driver.exists():
        env["ZE_ENABLE_ALT_DRIVERS"] = str(config.level_zero_alt_driver)
    return env


def build_training_plan(config: SigLIP2INT8Config | None = None) -> dict[str, object]:
    """Build the TAC-FUSE SigLIP2 QAT plan for optional accelerator offload."""

    config = config or SigLIP2INT8Config()
    datasets = [dataset.to_dict() for dataset in prioritized_datasets(hf_native_only=True)]
    return {
        "model": config.to_dict(),
        "quantization": {
            "target": "INT8",
            "framework": "OpenVINO + NNCF",
            "approach": "PTQ baseline, then NNCF QAT if validation loss/accuracy drops",
            "export_command": config.optimum_export_command(),
            "static_input_shapes": config.static_input_shapes,
        },
        "datasets": datasets,
        "hpo": default_hpo_config().to_dict(),
    }


def probe_openvino_npu(
    model_xml: Path | None = None,
    *,
    config: SigLIP2INT8Config | None = None,
) -> NPUProbeResult:
    """Probe Intel NPU visibility and optionally compile a static INT8 IR."""

    config = config or SigLIP2INT8Config()
    os.environ.update(openvino_env(config))

    try:
        import openvino as ov
    except Exception as exc:  # pragma: no cover - depends on optional install
        return NPUProbeResult(
            openvino_version=None,
            available_devices=(),
            npu_name=None,
            optimization_capabilities=(),
            driver_version=None,
            compiler_version=None,
            compile_ok=False if model_xml else None,
            compile_error=f"openvino import failed: {exc}",
        )

    core = ov.Core()
    devices = tuple(core.available_devices)

    def prop(name: str) -> Any | None:
        try:
            return core.get_property(config.target_device, name)
        except Exception:
            return None

    npu_name = prop("FULL_DEVICE_NAME")
    capabilities = prop("OPTIMIZATION_CAPABILITIES") or ()
    driver_version = prop("NPU_DRIVER_VERSION")
    compiler_version = prop("NPU_COMPILER_VERSION")
    compile_ok: bool | None = None
    compile_error: str | None = None

    if model_xml is not None:
        try:
            model = core.read_model(model_xml)
            shape_names = {input_.get_any_name() for input_ in model.inputs}
            reshape = {
                name: shape
                for name, shape in config.static_input_shapes.items()
                if name in shape_names
            }
            if reshape:
                model.reshape(reshape)
            core.compile_model(model, config.target_device)
            compile_ok = True
        except Exception as exc:
            compile_ok = False
            compile_error = str(exc)

    return NPUProbeResult(
        openvino_version=getattr(ov, "__version__", None),
        available_devices=devices,
        npu_name=str(npu_name) if npu_name is not None else None,
        optimization_capabilities=tuple(str(item) for item in capabilities),
        driver_version=str(driver_version) if driver_version is not None else None,
        compiler_version=str(compiler_version) if compiler_version is not None else None,
        compile_ok=compile_ok,
        compile_error=compile_error,
    )


def _json_print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="print the INT8 training/export plan")
    subparsers.add_parser("export-command", help="print the Optimum Intel INT8 export command")
    probe_parser = subparsers.add_parser("probe", help="probe OpenVINO NPU availability")
    probe_parser.add_argument("--model-xml", type=Path, default=None)

    args = parser.parse_args(argv)
    config = SigLIP2INT8Config()

    if args.command == "plan":
        _json_print(build_training_plan(config))
        return 0
    if args.command == "export-command":
        print(" ".join(config.optimum_export_command()))
        return 0
    if args.command == "probe":
        _json_print(probe_openvino_npu(args.model_xml, config=config).to_dict())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
