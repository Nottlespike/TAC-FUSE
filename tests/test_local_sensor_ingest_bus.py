"""Tests for the local sensor ingest bus (fusion_node.ingest).

All tests are network-free and operate entirely in-process using the
local-only :class:`IngestBus`.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tac_fuse.fusion_node.ingest import (
    ContributorSource,
    IngestBus,
    IngestRejection,
    SensorEvent,
    normalize_event,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

ALL_SOURCES = [s.value for s in ContributorSource]


def _event(
    source: str = "drone_pov",
    source_id: str = "uav-alpha",
    timestamp: str | None = None,
    *,
    confidence: float = 0.92,
    uncertainty: float = 0.08,
    seq: int = 1,
    payload: dict | None = None,
    event_id: str | None = None,
) -> dict:
    return {
        "source": source,
        "source_id": source_id,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "confidence": confidence,
        "uncertainty": uncertainty,
        "seq": seq,
        "payload": payload or {},
        **({"event_id": event_id} if event_id else {}),
    }


def _stale_event(age_s: float = 600.0, **overrides) -> dict:
    ts = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    return _event(timestamp=ts, **overrides)


def _write_jsonl(path: Path, events: list[dict]) -> None:
    with open(path, "w") as fh:
        for ev in events:
            fh.write(json.dumps(ev, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# normalize_event
# ---------------------------------------------------------------------------


class TestNormalizeEvent:
    def test_minimal_valid_event(self) -> None:
        raw = {
            "source": "drone_pov",
            "source_id": "cam-1",
            "timestamp": "2025-06-01T12:00:00+00:00",
        }
        evt = normalize_event(raw)
        assert isinstance(evt, SensorEvent)
        assert evt.source == "drone_pov"
        assert evt.source_id == "cam-1"
        assert evt.confidence == 0.0
        assert evt.uncertainty == 1.0
        assert evt.seq == 0
        assert evt.payload == {}
        assert evt.provenance == "local_bus"
        assert evt.event_id  # auto-generated uuid

    def test_full_event_preserves_fields(self) -> None:
        raw = _event(seq=7, payload={"heading_deg": 180})
        evt = normalize_event(raw, provenance="replay")
        assert evt.confidence == 0.92
        assert evt.uncertainty == 0.08
        assert evt.seq == 7
        assert evt.payload == {"heading_deg": 180}
        assert evt.provenance == "replay"
        assert evt.source == "drone_pov"

    def test_missing_source_raises(self) -> None:
        with pytest.raises(IngestRejection, match="missing required field 'source'"):
            normalize_event({"source_id": "x", "timestamp": "t"})

    def test_missing_source_id_raises(self) -> None:
        with pytest.raises(IngestRejection, match="missing required field 'source_id'"):
            normalize_event({"source": "drone_pov", "timestamp": "t"})

    def test_missing_timestamp_raises(self) -> None:
        with pytest.raises(IngestRejection, match="missing required field 'timestamp'"):
            normalize_event({"source": "drone_pov", "source_id": "x"})

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(IngestRejection, match="unknown source"):
            normalize_event({"source": "satellite_feed", "source_id": "x", "timestamp": "t"})

    def test_non_dict_raises(self) -> None:
        with pytest.raises(IngestRejection, match="event must be a dict"):
            normalize_event("not a dict")  # type: ignore[arg-type]

    def test_received_at_injected(self) -> None:
        raw = _event()
        now = datetime.now(UTC).isoformat()
        evt = normalize_event(raw, received_at=now)
        assert evt.received_at == now

    def test_event_id_preserved_when_given(self) -> None:
        raw = _event(event_id="custom-id-42")
        evt = normalize_event(raw)
        assert evt.event_id == "custom-id-42"


# ---------------------------------------------------------------------------
# IngestBus — basic accept / reject
# ---------------------------------------------------------------------------


class TestIngestBusAcceptReject:
    def test_accept_valid_event(self) -> None:
        bus = IngestBus()
        evt = bus.ingest(_event())
        assert bus.count() == 1
        assert bus.latest() is evt

    def test_accepts_all_seven_sources(self) -> None:
        bus = IngestBus()
        for source in ALL_SOURCES:
            bus.ingest(_event(source=source))
        assert bus.count() == len(ALL_SOURCES)

    def test_reject_malformed_and_continue(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(seq=1))
        with pytest.raises(IngestRejection):
            bus.ingest({"bad": True})
        bus.ingest(_event(seq=2))
        assert bus.count() == 2
        assert bus.rejection_count() == 1

    def test_rejection_records_raw(self) -> None:
        bus = IngestBus()
        try:
            bus.ingest({"garbage": True})
        except IngestRejection:
            pass
        assert len(bus.rejected) == 1
        assert bus.rejected[0].raw == {"garbage": True}

    def test_ingest_many_skips_rejections(self) -> None:
        bus = IngestBus()
        raws = [_event(seq=1), {"bad": True}, _event(seq=2)]
        accepted = bus.ingest_many(raws)
        assert len(accepted) == 2
        assert bus.count() == 2
        assert bus.rejection_count() == 1


# ---------------------------------------------------------------------------
# Staleness guard
# ---------------------------------------------------------------------------


class TestStalenessGuard:
    def test_stale_event_rejected(self) -> None:
        bus = IngestBus(max_staleness_s=60.0)
        with pytest.raises(IngestRejection, match="event age"):
            bus.ingest(_stale_event(age_s=120.0))
        assert bus.count() == 0
        assert bus.rejection_count() == 1

    def test_fresh_event_accepted(self) -> None:
        bus = IngestBus(max_staleness_s=60.0)
        bus.ingest(_event(timestamp=datetime.now(UTC).isoformat()))
        assert bus.count() == 1

    def test_staleness_disabled(self) -> None:
        bus = IngestBus(max_staleness_s=0.0)
        bus.ingest(_stale_event(age_s=9999.0))
        assert bus.count() == 1

    def test_non_iso_timestamp_not_stale_rejected(self) -> None:
        """Non-ISO timestamps skip staleness check but may still be accepted."""
        bus = IngestBus(max_staleness_s=5.0)
        raw = _event()
        raw["timestamp"] = "not-a-timestamp"
        bus.ingest(raw)
        assert bus.count() == 1


# ---------------------------------------------------------------------------
# Sequence tracking
# ---------------------------------------------------------------------------


class TestSequenceTracking:
    def test_monotonic_seq_ok(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(seq=1))
        bus.ingest(_event(seq=2))
        bus.ingest(_event(seq=3))
        assert bus.count() == 3

    def test_stale_seq_rejected(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(seq=5))
        with pytest.raises(IngestRejection, match="stale seq"):
            bus.ingest(_event(seq=3))
        assert bus.count() == 1
        assert bus.rejection_count() == 1

    def test_seq_per_source_independent(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(source="drone_pov", seq=1))
        bus.ingest(_event(source="drone_telemetry", seq=1))
        bus.ingest(_event(source="drone_pov", seq=2))
        assert bus.count() == 3

    def test_zero_seq_auto_increments(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(seq=0))
        bus.ingest(_event(seq=0))
        bus.ingest(_event(seq=0))
        assert bus.count() == 3


# ---------------------------------------------------------------------------
# latest() filter
# ---------------------------------------------------------------------------


class TestLatestFilter:
    def test_latest_overall(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(source="drone_pov", seq=1))
        last = bus.ingest(_event(source="drone_telemetry", seq=1))
        assert bus.latest() is last

    def test_latest_by_source(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(source="drone_pov", seq=1))
        bus.ingest(_event(source="drone_telemetry", seq=1))
        tele = bus.ingest(_event(source="drone_telemetry", seq=2))
        assert bus.latest("drone_telemetry") is tele

    def test_latest_by_enum(self) -> None:
        bus = IngestBus()
        bus.ingest(_event(source="npu_vision", seq=1))
        result = bus.latest(ContributorSource.NPU_VISION)
        assert result is not None
        assert result.source == "npu_vision"

    def test_latest_empty_returns_none(self) -> None:
        bus = IngestBus()
        assert bus.latest() is None
        assert bus.latest("drone_pov") is None


# ---------------------------------------------------------------------------
# JSONL replay
# ---------------------------------------------------------------------------


class TestJsonlReplay:
    def test_replay_jsonl_file(self) -> None:
        events = [_event(seq=i, source_id=f"src-{i}") for i in range(1, 6)]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
            for ev in events:
                fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
            path = fh.name

        try:
            bus = IngestBus(max_staleness_s=0.0)
            accepted = bus.replay_jsonl(path)
            assert len(accepted) == 5
            assert bus.count() == 5
        finally:
            Path(path).unlink()

    def test_replay_skips_malformed_lines(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
            fh.write(json.dumps(_event(seq=1)) + "\n")
            fh.write("NOT JSON\n")
            fh.write(json.dumps(_event(seq=2)) + "\n")
            fh.write("\n")
            path = fh.name

        try:
            bus = IngestBus(max_staleness_s=0.0)
            accepted = bus.replay_jsonl(path)
            assert len(accepted) == 2
            assert bus.rejection_count() == 1
        finally:
            Path(path).unlink()

    def test_replay_is_deterministic(self) -> None:
        """Two replays from the same file produce identical event sequences."""
        events = [_event(seq=i, source_id=f"s-{i}", event_id=f"id-{i}") for i in range(1, 4)]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as fh:
            for ev in events:
                fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
            path = fh.name

        try:
            bus_a = IngestBus(max_staleness_s=0.0)
            result_a = bus_a.replay_jsonl(path)

            bus_b = IngestBus(max_staleness_s=0.0)
            result_b = bus_b.replay_jsonl(path)

            assert [e.event_id for e in result_a] == [e.event_id for e in result_b]
            assert [e.source_id for e in result_a] == [e.source_id for e in result_b]
            assert [e.seq for e in result_a] == [e.seq for e in result_b]
        finally:
            Path(path).unlink()


# ---------------------------------------------------------------------------
# drain / snapshot / write_jsonl
# ---------------------------------------------------------------------------


class TestDrainSnapshotWrite:
    def test_drain_yields_and_clears(self) -> None:
        bus = IngestBus(max_staleness_s=0.0)
        bus.ingest(_event(seq=1))
        bus.ingest(_event(seq=2))
        drained = list(bus.drain())
        assert len(drained) == 2
        assert bus.count() == 0

    def test_snapshot_returns_dicts(self) -> None:
        bus = IngestBus(max_staleness_s=0.0)
        bus.ingest(_event(seq=1))
        snap = bus.snapshot()
        assert len(snap) == 1
        assert isinstance(snap[0], dict)
        assert snap[0]["source"] == "drone_pov"

    def test_write_and_roundtrip_jsonl(self) -> None:
        bus = IngestBus(max_staleness_s=0.0)
        bus.ingest(_event(seq=1, event_id="e-1"))
        bus.ingest(_event(seq=2, event_id="e-2"))

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            path = fh.name

        try:
            written = bus.write_jsonl(path)
            assert written == 2

            bus2 = IngestBus(max_staleness_s=0.0)
            reloaded = bus2.replay_jsonl(path)
            assert len(reloaded) == 2
            assert [e.event_id for e in reloaded] == ["e-1", "e-2"]
        finally:
            Path(path).unlink()


# ---------------------------------------------------------------------------
# SensorEvent serialization
# ---------------------------------------------------------------------------


class TestSensorEventSerialization:
    def test_to_dict_roundtrip(self) -> None:
        evt = normalize_event(_event(seq=3, payload={"alt_m": 120.0}))
        d = evt.to_dict()
        assert d["seq"] == 3
        assert d["payload"]["alt_m"] == 120.0

    def test_to_jsonl_is_valid_json(self) -> None:
        evt = normalize_event(_event())
        line = evt.to_jsonl()
        parsed = json.loads(line)
        assert parsed["source"] == evt.source

    def test_to_jsonl_compact(self) -> None:
        evt = normalize_event(_event())
        line = evt.to_jsonl()
        assert "\n" not in line


# ---------------------------------------------------------------------------
# ContributorSource enum
# ---------------------------------------------------------------------------


class TestContributorSource:
    def test_all_seven_sources(self) -> None:
        assert len(ContributorSource) == 7
        values = {s.value for s in ContributorSource}
        assert values == {
            "drone_pov",
            "drone_telemetry",
            "npu_vision",
            "route_solver",
            "c2_command_audit",
            "operator_observations",
            "external_field_sensors",
        }

    def test_source_enum_lookup(self) -> None:
        assert ContributorSource("drone_pov") is ContributorSource.DRONE_POV
