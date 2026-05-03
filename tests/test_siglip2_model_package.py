from tac_fuse.training import (
    load_siglip2_classifier_package,
    packaged_siglip2_model_dir,
    packaged_siglip2_required_files,
)


def test_packaged_siglip2_manifest_records_hpo_winner() -> None:
    manifest = load_siglip2_classifier_package()

    assert manifest["package_id"] == "siglip2-expanded-vehicle-hpo-best"
    assert manifest["selection"]["framework"] == "Ax + BoTorch"
    assert manifest["selection"]["trial_index"] == 14
    assert manifest["selection"]["completed_trials"] == 18
    assert manifest["hpo_parameters"]["freeze_backbone"] is False
    assert manifest["hpo_parameters"]["max_steps"] == 115
    assert manifest["metrics"]["eval_accuracy"] > 0.69
    assert manifest["metrics"]["eval_loss"] < 0.68


def test_packaged_siglip2_manifest_is_self_describing() -> None:
    manifest = load_siglip2_classifier_package()
    files = {item["path"]: item for item in manifest["files"]}

    assert packaged_siglip2_model_dir(manifest).name == "siglip2-expanded-vehicle-hpo-best"
    assert "classifier_head.pt" in files
    assert "backbone/model.safetensors" in files
    assert "processor/tokenizer.json" in files
    assert manifest["dataset"]["label_mapping"]["drone_near_restricted_area"] == 2
    assert manifest["dataset"]["train_samples"] == 1152
    assert manifest["dataset"]["eval_samples"] == 288


def test_packaged_siglip2_checksums_are_sha256() -> None:
    manifest = load_siglip2_classifier_package()

    for item in manifest["files"]:
        assert len(item["sha256"]) == 64
        int(item["sha256"], 16)
        assert item["bytes"] > 0


def test_packaged_siglip2_required_files_resolve_under_model_dir() -> None:
    manifest = load_siglip2_classifier_package()
    model_dir = packaged_siglip2_model_dir(manifest)

    required = packaged_siglip2_required_files(manifest)

    assert required
    assert all(path.is_relative_to(model_dir) for path in required)
