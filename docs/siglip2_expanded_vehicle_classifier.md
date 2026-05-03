# SigLIP2 Expanded Vehicle Classifier Package

The selected H100 classifier checkpoint is packaged locally under:

```text
models/siglip2-expanded-vehicle-hpo-best/
```

`models/` is intentionally ignored by git. The tracked package manifest is:

```text
configs/model_packages/siglip2_expanded_vehicle_hpo_best.json
```

The manifest records the Ax + BoTorch search, dataset provenance, winning
hyperparameters, evaluation metrics, and SHA-256 checksums for the ignored model
files.

## Contents

```text
models/siglip2-expanded-vehicle-hpo-best/
  backbone/
    config.json
    model.safetensors
  processor/
    chat_template.jinja
    processor_config.json
    tokenizer.json
    tokenizer_config.json
  classifier_head.pt
  checksums.sha256
  training_summary.json
```

## Selected Run

- HPO framework: Ax + BoTorch
- Objective: `eval_accuracy - 0.10 * eval_loss`
- Trials completed: 18
- Winning trial: 14
- Base model: `google/siglip2-base-patch16-224`
- Dataset manifest: `expanded_vehicle_v2`
- Train/eval samples: 1152 / 288
- Accuracy: 0.6979166666666666
- Eval loss: 0.676681625812004
- Score: 0.6302485040854662

Winning hyperparameters:

```text
learning_rate=1.728442593317657e-05
weight_decay=0.0
warmup_ratio=0.25
batch_size=4
gradient_accumulation=8
max_steps=115
freeze_backbone=false
```

## Verification

Verify the copied local package bytes from the TAC-FUSE repo root:

```bash
sha256sum -c models/siglip2-expanded-vehicle-hpo-best/checksums.sha256
```

Verify the tracked metadata path without needing the large model files:

```bash
uv run pytest tests/test_siglip2_model_package.py -q
```

Install and validate the optional PyTorch runtime in the project `.venv`:

```bash
uv sync --extra dev --extra classifier-runtime
uv run python scripts/check_classifier_package.py --require-package --require-runtime --load-model
```

For a visible cue smoke test, pass a local frame:

```bash
uv run python scripts/check_classifier_package.py --require-package --require-runtime --image /path/to/frame.jpg
```

## Runtime Boundary

This package is now importable through `tac_fuse.vision.classifier` as
`PackagedSigLIP2Classifier`. It is a PyTorch SigLIP2 backbone plus a trained
classifier head. It is not yet the OpenVINO INT8 IR consumed by
`IntelNPUSigLIP2Adapter`, which expects:

```text
models/siglip2-field-npu/
  openvino_model.xml
  openvino_model.bin
```

Use this package as the H100-selected source checkpoint for the next export
step into the NPU-ready OpenVINO layout.
