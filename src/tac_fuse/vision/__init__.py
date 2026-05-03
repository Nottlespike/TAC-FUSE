"""Optional semantic vision utilities for TAC-FUSE."""

__all__ = [
    "OpenVINOZeroShotClassifier",
    "ZeroShotCandidate",
    "ZeroShotClassification",
    "ZeroShotPrompt",
    "default_zero_shot_prompts",
    "rank_zero_shot_logits",
]


def __getattr__(name: str) -> object:
    if name in __all__:
        from tac_fuse.vision import zero_shot

        return getattr(zero_shot, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
