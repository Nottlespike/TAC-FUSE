"""Optional semantic vision utilities for TAC-FUSE."""

__all__ = [
    "BaseClassifier",
    "BoundingBox",
    "ClassifierBoundary",
    "ClassifierOutput",
    "ModelAssetError",
    "NaiveZeroShotClassifier",
    "OpenVINOZeroShotClassifier",
    "SegmentationMask",
    "ZeroShotCandidate",
    "ZeroShotClassification",
    "ZeroShotPrompt",
    "create_classifier",
    "default_zero_shot_prompts",
    "rank_zero_shot_logits",
]


def __getattr__(name: str) -> object:
    if name in {
        "BaseClassifier",
        "BoundingBox",
        "ClassifierBoundary",
        "ClassifierOutput",
        "ModelAssetError",
        "NaiveZeroShotClassifier",
        "SegmentationMask",
        "create_classifier",
    }:
        from tac_fuse.vision import classifier

        return getattr(classifier, name)
    if name in __all__:
        from tac_fuse.vision import zero_shot

        return getattr(zero_shot, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
