"""SigLIP2 INT8 OpenVINO export configuration for TAC-FUSE."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SigLIP2INT8Config:
    """Deployment-oriented defaults for google/siglip2-base-patch16-224."""

    model_id: str = "google/siglip2-base-patch16-224"
    target_device: str = "NPU"
    precision: str = "INT8"
    weight_format: str = "int8"
    image_size: int = 224
    patch_size: int = 16
    max_text_tokens: int = 64
    export_dir: Path = Path("artifacts/siglip2_openvino_int8")
    level_zero_alt_driver: Path = Path("/usr/lib/x86_64-linux-gnu/libze_intel_npu.so.1.32.1")
    class_prompts: tuple[str, ...] = field(
        default_factory=lambda: (
            "a drone",
            "a quadcopter drone",
            "a fixed wing unmanned aerial vehicle",
            "a helicopter",
            "a ground vehicle",
            "a military truck",
            "a person",
            "a road obstruction",
            "damaged infrastructure",
            "a landing zone",
        )
    )

    def __post_init__(self) -> None:
        if self.precision.upper() != "INT8" or self.weight_format.lower() != "int8":
            raise ValueError("TAC-FUSE NPU training/export must stay INT8.")

    @property
    def static_input_shapes(self) -> dict[str, list[int]]:
        return {
            "input_ids": [1, self.max_text_tokens],
            "pixel_values": [1, 3, self.image_size, self.image_size],
        }

    def optimum_export_command(self) -> list[str]:
        """Build the Optimum Intel export command for INT8 OpenVINO IR."""

        return [
            "optimum-cli",
            "export",
            "openvino",
            "--model",
            self.model_id,
            "--task",
            "zero-shot-image-classification",
            "--weight-format",
            self.weight_format,
            str(self.export_dir),
        ]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["export_dir"] = str(self.export_dir)
        payload["level_zero_alt_driver"] = str(self.level_zero_alt_driver)
        return payload
