from datetime import UTC, datetime

from tac_fuse.fusion_node.ingest import ContributorSource, SensorEvent
from tac_fuse.vision.zero_shot import (
    ZeroShotCandidate,
    ZeroShotClassification,
    ZeroShotPrompt,
    default_zero_shot_prompts,
    rank_zero_shot_logits,
)


def test_default_prompts_are_tac_fuse_mission_labels() -> None:
    prompts = default_zero_shot_prompts()
    labels = {prompt.label for prompt in prompts}

    assert "drone" in labels
    assert "quadcopter drone" in labels
    assert "road obstruction" in labels
    assert "landing zone" in labels


def test_rank_zero_shot_logits_returns_softmax_order() -> None:
    prompts = (
        ZeroShotPrompt(label="drone", prompt="a drone"),
        ZeroShotPrompt(label="ground vehicle", prompt="a ground vehicle"),
        ZeroShotPrompt(label="person", prompt="a person"),
    )

    ranked = rank_zero_shot_logits(prompts, [[0.1, 2.0, 1.0]], top_k=2)

    assert [candidate.label for candidate in ranked] == ["ground vehicle", "person"]
    assert ranked[0].score > ranked[1].score
    assert ranked[0].score <= 1.0


def test_rank_zero_shot_logits_accepts_column_logits() -> None:
    prompts = (
        ZeroShotPrompt(label="drone", prompt="a drone"),
        ZeroShotPrompt(label="landing zone", prompt="a landing zone"),
    )

    ranked = rank_zero_shot_logits(prompts, [[0.0], [3.0]])

    assert ranked[0].label == "landing zone"


def test_zero_shot_classification_maps_to_pseudo_sensor_event() -> None:
    classification = ZeroShotClassification(
        frame_path="/tmp/frame.jpg",
        device="NPU",
        model_xml="/tmp/model.xml",
        timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        candidates=(
            ZeroShotCandidate(
                label="quadcopter drone",
                prompt="a quadcopter drone",
                score=0.82,
                logit=4.0,
            ),
        ),
    )

    event = classification.to_sensor_event(asset_id="asset-1", event_id="event-1")

    assert isinstance(event, SensorEvent)
    assert event.event_id == "event-1"
    assert event.source == ContributorSource.NPU_VISION.value
    assert event.payload["asset_id"] == "asset-1"
    assert event.payload["frame_path"] == "/tmp/frame.jpg"
    assert event.confidence == 0.82
    assert event.payload["classifier"] == "siglip2_zero_shot"
    assert event.payload["classification_mode"] == "pseudo"
    assert event.payload["pseudo_classification"]["label"] == "quadcopter drone"
    assert event.payload["pseudo_classification_alert"] is False
    assert event.payload["data"]["detections"] == []


def test_zero_shot_sensor_event_can_opt_into_detection_payload() -> None:
    classification = ZeroShotClassification(
        frame_path="/tmp/frame.jpg",
        device="NPU",
        model_xml="/tmp/model.xml",
        timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        candidates=(
            ZeroShotCandidate(
                label="quadcopter drone",
                prompt="a quadcopter drone",
                score=0.82,
                logit=4.0,
            ),
        ),
    )

    event = classification.to_sensor_event(
        asset_id="asset-1",
        as_detection=True,
        confidence_floor=0.75,
    )

    assert event.payload["data"]["detections"] == [
        {
            "class": "quadcopter drone",
            "confidence": 0.82,
            "source": "siglip2_zero_shot",
            "pseudo": True,
        }
    ]
    assert event.payload["classification_mode"] == "pseudo"


def test_zero_shot_sensor_event_can_mark_pseudo_alert_metadata() -> None:
    classification = ZeroShotClassification(
        frame_path="/tmp/frame.jpg",
        device="NPU",
        model_xml="/tmp/model.xml",
        timestamp=datetime(2026, 5, 2, tzinfo=UTC),
        candidates=(
            ZeroShotCandidate(
                label="landing zone",
                prompt="a landing zone",
                score=0.9,
                logit=5.0,
            ),
        ),
    )

    event = classification.to_sensor_event(
        asset_id="asset-1",
        emit_alert=True,
        alert_floor=0.8,
    )

    assert event.payload["data"]["detections"] == []
    assert event.payload["pseudo_classification_alert"] is True
    assert event.payload["pseudo_classification_alert_floor"] == 0.8
