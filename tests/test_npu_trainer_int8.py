from pathlib import Path

from tac_fuse.npu_trainer import build_training_plan, openvino_env
from tac_fuse.qat_data import prioritized_datasets, required_hf_repos
from tac_fuse.training.hpo_config import should_schedule_hpo
from tac_fuse.training.siglip2_config import SigLIP2INT8Config


def test_siglip2_export_defaults_are_int8() -> None:
    config = SigLIP2INT8Config()

    assert config.precision == "INT8"
    assert config.weight_format == "int8"
    assert str(config.level_zero_alt_driver).startswith("/usr/lib/x86_64-linux-gnu/")
    assert "--weight-format" in config.optimum_export_command()
    assert "int8" in config.optimum_export_command()
    assert config.static_input_shapes["pixel_values"] == [1, 3, 224, 224]


def test_dataset_registry_prefers_hf_native_drone_sets() -> None:
    datasets = prioritized_datasets()
    repos = required_hf_repos()

    assert datasets[0].hf_native
    assert "Voxel51/VisDrone2019-DET" in repos
    assert "McCheng/DroneVehicle" in repos
    assert all(dataset.hf_native for dataset in datasets)


def test_dota_is_optional_when_non_hf_sets_are_enabled() -> None:
    datasets = prioritized_datasets(hf_native_only=False)
    dota = next(dataset for dataset in datasets if dataset.name == "DOTA")

    assert not dota.required
    assert not dota.hf_native
    assert dota.priority > 1


def test_hpo_triggers_on_fast_overfit() -> None:
    assert should_schedule_hpo(
        train_metric=0.92,
        validation_metric=0.70,
        higher_is_better=True,
    )
    assert should_schedule_hpo(
        train_metric=0.50,
        validation_metric=0.70,
        higher_is_better=False,
    )


def test_openvino_env_sets_alt_driver_when_present(tmp_path: Path) -> None:
    driver = tmp_path / "libze_intel_npu.so"
    driver.touch()
    config = SigLIP2INT8Config(level_zero_alt_driver=driver)

    assert openvino_env(config)["ZE_ENABLE_ALT_DRIVERS"] == str(driver)


def test_training_plan_is_int8_and_hf_native() -> None:
    plan = build_training_plan()

    assert plan["quantization"]["target"] == "INT8"
    assert plan["quantization"]["export_command"][-2:] == [
        "int8",
        "artifacts/siglip2_openvino_int8",
    ]
    assert all(dataset["hf_native"] for dataset in plan["datasets"])
