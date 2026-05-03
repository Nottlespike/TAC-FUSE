"""Ax/BoTorch hyperparameter plan for TAC-FUSE SigLIP2 QAT."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class HPOConfig:
    """Search-space defaults for a small Ax/BoTorch recovery run."""

    max_trials: int = 24
    objective_name: str = "validation_map"
    minimize: bool = False
    overfit_gap: float = 0.15
    search_space: tuple[dict[str, object], ...] = (
        {
            "name": "learning_rate",
            "type": "range",
            "bounds": [1e-7, 5e-5],
            "value_type": "float",
            "log_scale": True,
        },
        {
            "name": "weight_decay",
            "type": "range",
            "bounds": [0.0, 0.05],
            "value_type": "float",
        },
        {
            "name": "warmup_ratio",
            "type": "range",
            "bounds": [0.0, 0.2],
            "value_type": "float",
        },
        {
            "name": "batch_size",
            "type": "choice",
            "values": [4, 8, 16],
            "value_type": "int",
            "is_ordered": True,
        },
        {
            "name": "nncf_subset_size",
            "type": "choice",
            "values": [128, 256, 512, 1024],
            "value_type": "int",
            "is_ordered": True,
        },
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_hpo_config() -> HPOConfig:
    """Return the default HPO plan without importing Ax at module import time."""

    return HPOConfig()


def should_schedule_hpo(
    *,
    train_metric: float,
    validation_metric: float,
    higher_is_better: bool,
    gap_threshold: float | None = None,
) -> bool:
    """Decide whether overfitting is severe enough to start an HPO sweep."""

    threshold = default_hpo_config().overfit_gap if gap_threshold is None else gap_threshold
    if higher_is_better:
        return train_metric - validation_metric >= threshold
    return validation_metric - train_metric >= threshold
