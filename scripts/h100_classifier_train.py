#!/usr/bin/env python3
"""Temporary H100 SigLIP2 classifier training entrypoint for TAC-FUSE.

This script is intentionally standalone so it can be copied to a temporary
training host with the repo tree. It reads the existing TAC-FUSE SigLIP2 YAML,
supports synthetic smoke samples, and only imports torch/transformers/Pillow
inside commands that need them.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when training config or manifests are invalid."""


@dataclass(frozen=True, slots=True)
class TrainConfig:
    model_id: str
    manifest_train: Path
    manifest_eval: Path | None
    image_root: Path
    label_mapping: dict[str, int]
    output_dir: Path
    run_name: str | None
    epochs: int
    batch_size: int
    gradient_accumulation: int
    lr: float
    weight_decay: float
    warmup_ratio: float
    max_grad_norm: float
    fp16: bool
    bf16: bool
    num_workers: int
    pin_memory: bool
    drop_last: bool
    logging_steps: int
    freeze_backbone: bool
    local_files_only: bool
    cache_dir: Path | None
    seed: int
    allow_tf32: bool

    @property
    def run_dir(self) -> Path:
        return self.output_dir / (self.run_name or f"siglip2_{time.strftime('%Y%m%d_%H%M%S')}")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("manifest_train", "manifest_eval", "image_root", "output_dir", "cache_dir"):
            if payload[key] is not None:
                payload[key] = str(payload[key])
        return payload


@dataclass(frozen=True, slots=True)
class Sample:
    image_path: Path
    label: int
    label_name: str


def load_config(
    path: Path, *, allow_download: bool, output_dir: Path | None, run_name: str | None
) -> TrainConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping")
    model = _mapping(raw, "model")
    dataset = _mapping(raw, "dataset")
    training = _mapping(raw, "training")
    output = _mapping(raw, "output")
    offline = raw.get("offline") if isinstance(raw.get("offline"), dict) else {}

    labels_raw = dataset.get("label_mapping")
    if not isinstance(labels_raw, dict) or not labels_raw:
        raise ConfigError("dataset.label_mapping must be a non-empty mapping")
    labels = {str(key): int(value) for key, value in labels_raw.items()}
    cache_raw = offline.get("hf_cache_dir")
    eval_raw = dataset.get("manifest_eval")

    return TrainConfig(
        model_id=str(model.get("name", "google/siglip2-base-patch16-224")),
        manifest_train=Path(str(dataset["manifest_train"])),
        manifest_eval=Path(str(eval_raw)) if eval_raw else None,
        image_root=Path(str(dataset.get("image_root", "."))),
        label_mapping=labels,
        output_dir=output_dir
        or Path(str(output.get("output_dir", "outputs/siglip2-field-conditions"))),
        run_name=run_name if run_name is not None else output.get("run_name"),
        epochs=int(training.get("epochs", 1)),
        batch_size=int(training.get("batch_size", 4)),
        gradient_accumulation=max(1, int(training.get("gradient_accumulation", 1))),
        lr=float(training.get("lr", 2e-5)),
        weight_decay=float(training.get("weight_decay", 0.01)),
        warmup_ratio=float(training.get("warmup_ratio", 0.0)),
        max_grad_norm=float(training.get("max_grad_norm", 1.0)),
        fp16=bool(training.get("fp16", False)),
        bf16=bool(training.get("bf16", False)),
        num_workers=int(training.get("num_workers", 0)),
        pin_memory=bool(training.get("pin_memory", False)),
        drop_last=bool(training.get("dataloader_drop_last", False)),
        logging_steps=max(1, int(training.get("logging_steps", 10))),
        freeze_backbone=bool(model.get("freeze_vision_encoder", False)),
        local_files_only=bool(offline.get("local_files_only", offline.get("enabled", False)))
        and not allow_download,
        cache_dir=Path(str(cache_raw)) if cache_raw else None,
        seed=int(raw.get("seed", 42)),
        allow_tf32=bool(raw.get("allow_tf32", False)),
    )


def build_plan(
    config: TrainConfig, *, synthetic_samples: int, max_steps: int | None, device: str
) -> dict[str, object]:
    if synthetic_samples > 0:
        train_count = synthetic_samples
        eval_count = max(1, synthetic_samples // 4)
    else:
        train_count = len(load_manifest(config.manifest_train, config))
        eval_count = (
            len(load_manifest(config.manifest_eval, config))
            if config.manifest_eval and config.manifest_eval.exists()
            else 0
        )
    return {
        "config": config.to_dict(),
        "device": device,
        "train_count": train_count,
        "eval_count": eval_count,
        "max_steps": max_steps,
        "synthetic_samples": synthetic_samples,
        "labels": sorted(config.label_mapping, key=config.label_mapping.get),
    }


def load_manifest(path: Path | None, config: TrainConfig) -> list[Sample]:
    if path is None:
        return []
    if not path.exists():
        raise ConfigError(f"manifest not found: {path}")
    records = _read_records(path)
    samples = [_record_to_sample(record, config) for record in records]
    if not samples:
        raise ConfigError(f"manifest has no samples: {path}")
    return samples


def smoke_cuda(args: argparse.Namespace) -> int:
    import torch

    device = _resolve_device(torch, args.device)
    _seed(torch, args.seed)
    model = torch.nn.Sequential(
        torch.nn.Linear(128, 256), torch.nn.GELU(), torch.nn.Linear(256, 6)
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    losses: list[float] = []
    for _ in range(args.steps):
        x = torch.randn(args.batch_size, 128, device=device)
        y = torch.randint(0, 6, (args.batch_size,), device=device)
        opt.zero_grad(set_to_none=True)
        with torch.autocast(
            "cuda", dtype=torch.float16, enabled=device.type == "cuda" and not args.no_fp16
        ):
            loss = torch.nn.functional.cross_entropy(model(x), y)
        loss.backward()
        opt.step()
        losses.append(float(loss.detach().cpu()))
    payload = {
        "device": str(device),
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "steps": args.steps,
        "final_loss": losses[-1],
        "peak_memory_mb": (
            torch.cuda.max_memory_allocated(device) / (1024 * 1024)
            if device.type == "cuda"
            else None
        ),
    }
    _json_print(payload)
    return 0


def train(args: argparse.Namespace) -> int:
    config = load_config(
        args.config,
        allow_download=args.allow_download,
        output_dir=args.output_dir,
        run_name=args.run_name,
    )
    if args.dry_run:
        _json_print(
            build_plan(
                config,
                synthetic_samples=args.synthetic_samples,
                max_steps=args.max_steps,
                device=args.device,
            )
        )
        return 0

    import torch
    from PIL import Image
    from torch.utils.data import DataLoader, Dataset
    from transformers import AutoModel, AutoProcessor, get_cosine_schedule_with_warmup

    device = _resolve_device(torch, args.device)
    _seed(torch, config.seed)
    torch.backends.cuda.matmul.allow_tf32 = config.allow_tf32
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.allow_tf32 = config.allow_tf32

    labels = sorted(config.label_mapping, key=config.label_mapping.get)
    train_samples = (
        synthetic_samples(config, args.synthetic_samples)
        if args.synthetic_samples
        else load_manifest(config.manifest_train, config)
    )
    eval_samples = (
        synthetic_samples(config, max(1, args.synthetic_samples // 4))
        if args.synthetic_samples
        else load_manifest(config.manifest_eval, config)
        if config.manifest_eval and config.manifest_eval.exists()
        else []
    )

    hf_kwargs: dict[str, object] = {"local_files_only": config.local_files_only}
    if config.cache_dir:
        hf_kwargs["cache_dir"] = str(config.cache_dir)
    processor = AutoProcessor.from_pretrained(config.model_id, **hf_kwargs)
    backbone = AutoModel.from_pretrained(config.model_id, **hf_kwargs).to(device)
    if config.freeze_backbone:
        for param in backbone.parameters():
            param.requires_grad = False
    backbone.train()

    class ImageDataset(Dataset):
        def __init__(self, samples: list[Sample]) -> None:
            self.samples = samples

        def __len__(self) -> int:
            return len(self.samples)

        def __getitem__(self, index: int) -> tuple[Any, int]:
            sample = self.samples[index]
            if _is_synthetic_path(sample.image_path):
                rng = random.Random(config.seed + index)
                pixels = bytes(rng.randrange(0, 255) for _ in range(224 * 224 * 3))
                image = Image.frombytes("RGB", (224, 224), pixels)
            else:
                image = Image.open(sample.image_path).convert("RGB")
            return image, sample.label

    def collate(batch: list[tuple[Any, int]]) -> dict[str, Any]:
        images, batch_labels = zip(*batch, strict=True)
        encoded = processor(images=list(images), return_tensors="pt")
        encoded["labels"] = torch.tensor(batch_labels, dtype=torch.long)
        return encoded

    train_loader = DataLoader(
        ImageDataset(train_samples),
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=config.num_workers,
        pin_memory=config.pin_memory and device.type == "cuda",
        drop_last=config.drop_last and len(train_samples) >= config.batch_size,
        collate_fn=collate,
    )
    eval_loader = (
        DataLoader(
            ImageDataset(eval_samples),
            batch_size=config.batch_size,
            shuffle=False,
            collate_fn=collate,
        )
        if eval_samples
        else None
    )

    first_batch = next(iter(train_loader))
    with torch.no_grad():
        feature_dim = image_features(backbone, first_batch["pixel_values"].to(device)).shape[-1]
    head = torch.nn.Linear(feature_dim, len(config.label_mapping)).to(device)
    params = list(head.parameters()) + [p for p in backbone.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=config.lr, weight_decay=config.weight_decay)
    total_steps = max(1, (len(train_loader) * config.epochs) // config.gradient_accumulation)
    if args.max_steps is not None:
        total_steps = min(total_steps, args.max_steps)
    scheduler = get_cosine_schedule_with_warmup(
        opt,
        num_warmup_steps=int(total_steps * config.warmup_ratio),
        num_training_steps=total_steps,
    )
    amp = device.type == "cuda" and (config.fp16 or config.bf16)
    amp_dtype = torch.bfloat16 if config.bf16 else torch.float16
    step = 0
    history: list[dict[str, float | int]] = []
    opt.zero_grad(set_to_none=True)
    for epoch in range(config.epochs):
        for batch_idx, batch in enumerate(train_loader):
            pixels = batch["pixel_values"].to(device, non_blocking=True)
            batch_labels = batch["labels"].to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=amp_dtype, enabled=amp):
                logits = head(image_features(backbone, pixels))
                loss = torch.nn.functional.cross_entropy(logits, batch_labels)
                scaled_loss = loss / config.gradient_accumulation
            scaled_loss.backward()
            if (batch_idx + 1) % config.gradient_accumulation == 0:
                torch.nn.utils.clip_grad_norm_(params, config.max_grad_norm)
                opt.step()
                scheduler.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                if step == 1 or step % config.logging_steps == 0:
                    history.append(
                        {"epoch": epoch, "step": step, "loss": float(loss.detach().cpu())}
                    )
                if args.max_steps is not None and step >= args.max_steps:
                    break
        if args.max_steps is not None and step >= args.max_steps:
            break

    metrics = evaluate(torch, backbone, head, eval_loader, device, amp, amp_dtype)
    run_dir = config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "head_state_dict": head.state_dict(),
            "feature_dim": feature_dim,
            "label_mapping": config.label_mapping,
            "labels": labels,
        },
        run_dir / "classifier_head.pt",
    )
    backbone.save_pretrained(run_dir / "backbone")
    processor.save_pretrained(run_dir / "processor")
    summary = {
        "run_dir": str(run_dir),
        "device": str(device),
        "model_id": config.model_id,
        "global_step": step,
        "train_samples": len(train_samples),
        "eval_samples": len(eval_samples),
        "history": history,
        "metrics": metrics,
        "label_mapping": config.label_mapping,
    }
    (run_dir / "training_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    _json_print(summary)
    return 0


def image_features(backbone: Any, pixel_values: Any) -> Any:
    if hasattr(backbone, "get_image_features"):
        return _feature_tensor(backbone.get_image_features(pixel_values=pixel_values))
    outputs = backbone(pixel_values=pixel_values)
    return _feature_tensor(outputs)


def _feature_tensor(outputs: Any) -> Any:
    if getattr(outputs, "image_embeds", None) is not None:
        return outputs.image_embeds
    if getattr(outputs, "pooler_output", None) is not None:
        return outputs.pooler_output
    if getattr(outputs, "last_hidden_state", None) is not None:
        return outputs.last_hidden_state.mean(dim=1)
    if isinstance(outputs, (tuple, list)) and outputs:
        tensor = outputs[0]
    else:
        tensor = outputs
    if getattr(tensor, "ndim", 0) > 2:
        return tensor.mean(dim=1)
    return tensor


def evaluate(
    torch: Any, backbone: Any, head: Any, loader: Any | None, device: Any, amp: bool, amp_dtype: Any
) -> dict[str, float | int | None]:
    if loader is None:
        return {"eval_loss": None, "eval_accuracy": None, "eval_samples": 0}
    backbone.eval()
    head.eval()
    losses: list[float] = []
    correct = 0
    total = 0
    with torch.no_grad():
        for batch in loader:
            pixels = batch["pixel_values"].to(device, non_blocking=True)
            labels = batch["labels"].to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=amp_dtype, enabled=amp):
                logits = head(image_features(backbone, pixels))
                loss = torch.nn.functional.cross_entropy(logits, labels)
            losses.append(float(loss.detach().cpu()))
            correct += int((logits.argmax(dim=-1) == labels).sum().detach().cpu())
            total += int(labels.numel())
    backbone.train()
    head.train()
    return {
        "eval_loss": sum(losses) / len(losses) if losses else None,
        "eval_accuracy": correct / total if total else None,
        "eval_samples": total,
    }


def synthetic_samples(config: TrainConfig, count: int) -> list[Sample]:
    labels = sorted(config.label_mapping, key=config.label_mapping.get)
    return [
        Sample(
            image_path=Path(f"synthetic://sample-{idx}"),
            label=config.label_mapping[labels[idx % len(labels)]],
            label_name=labels[idx % len(labels)],
        )
        for idx in range(count)
    ]


def _is_synthetic_path(path: Path) -> bool:
    return str(path).startswith(("synthetic://", "synthetic:/"))


def _read_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = next(
            (
                payload[key]
                for key in ("samples", "records", "items", "data")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        if records is None:
            raise ConfigError(f"{path} must contain samples, records, items, or data")
    else:
        raise ConfigError(f"{path} must be JSON list/object")
    if not all(isinstance(record, dict) for record in records):
        raise ConfigError(f"{path} contains non-object records")
    return records


def _record_to_sample(record: dict[str, Any], config: TrainConfig) -> Sample:
    image_value = _first(
        record, ("rgb_path", "image_path", "image", "path", "file_name", "filename")
    )
    if image_value is None:
        raise ConfigError(f"record missing image path: {record}")
    image_path = Path(str(image_value))
    if not image_path.is_absolute() and not _is_synthetic_path(image_path):
        image_path = config.image_root / image_path

    label_value = _first(record, ("label", "field_condition", "class_name", "class", "target"))
    if label_value is None:
        raise ConfigError(f"record missing label: {record}")
    if isinstance(label_value, int):
        label = label_value
        label_name = next(
            (name for name, idx in config.label_mapping.items() if idx == label), str(label)
        )
    else:
        label_name = str(label_value)
        if label_name not in config.label_mapping:
            raise ConfigError(f"unknown label {label_name!r}")
        label = config.label_mapping[label_name]
    return Sample(image_path=image_path, label=label, label_name=label_name)


def _mapping(raw: dict[str, object], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping")
    return value


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        if record.get(key) not in (None, ""):
            return record[key]
    return None


def _resolve_device(torch: Any, device: str) -> Any:
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but torch.cuda.is_available() is false")
    return torch.device(device)


def _seed(torch: Any, seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _json_print(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke-cuda")
    smoke.add_argument("--device", default="cuda", choices=("auto", "cuda", "cpu"))
    smoke.add_argument("--steps", type=int, default=5)
    smoke.add_argument("--batch-size", type=int, default=64)
    smoke.add_argument("--seed", type=int, default=42)
    smoke.add_argument("--no-fp16", action="store_true")
    smoke.set_defaults(func=smoke_cuda)

    train_parser = sub.add_parser("train-gpu")
    train_parser.add_argument(
        "--config", type=Path, default=Path("configs/training/siglip2_field_conditions.yaml")
    )
    train_parser.add_argument("--device", default="cuda", choices=("auto", "cuda", "cpu"))
    train_parser.add_argument("--allow-download", action="store_true")
    train_parser.add_argument("--dry-run", action="store_true")
    train_parser.add_argument("--max-steps", type=int, default=None)
    train_parser.add_argument("--synthetic-samples", type=int, default=0)
    train_parser.add_argument("--output-dir", type=Path, default=None)
    train_parser.add_argument("--run-name", default=None)
    train_parser.set_defaults(func=train)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
