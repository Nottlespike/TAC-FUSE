"""Local sensor ingest bus for the laptop fusion node.

Accepts structured events from seven contributor sources, normalizes every
input into a common :class:`SensorEvent` envelope, and supports deterministic
replay from JSONL files.  The bus is entirely local-only and network-free.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ContributorSource(Enum):
    """Canonical set of contributor sources for the fusion ingest bus."""

    DRONE_POV = "drone_pov"
    DRONE_TELEMETRY = "drone_telemetry"
    NPU_VISION = "npu_vision"
    ROUTE_SOLVER = "route_solver"
    C2_COMMAND_AUDIT = "c2_command_audit"
    OPERATOR_OBSERVATIONS = "operator_observations"
    EXTERNAL_FIELD_SENSORS = "external_field_sensors"


class IngestRejection(Exception):
    """Raised when an event is rejected by the ingest bus."""

    def __init__(self, reason: str, raw: Any = None) -> None:
        self.reason = reason
        self.raw = raw
        super().__init__(f"Ingest rejected: {reason}")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_source(value: str) -> ContributorSource:
    try:
        return ContributorSource(value)
    except ValueError:
        valid = ", ".join(s.value for s in ContributorSource)
        raise IngestRejection(
            f"unknown source {value!r}; valid sources: {valid}", raw=value
        ) from None


@dataclass(frozen=True)
class SensorEvent:
    """Normalized contributor event envelope.

    Every event that enters the fusion bus is converted to this shape so
    downstream consumers have a single, predictable structure.
    """

    event_id: str
    source: str
    source_id: str
    timestamp: str
    received_at: str
    confidence: float
    uncertainty: float
    provenance: str
    seq: int
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def normalize_event(
    raw: dict[str, Any],
    *,
    received_at: str | None = None,
    provenance: str = "local_bus",
) -> SensorEvent:
    """Normalize a raw contributor dict into a :class:`SensorEvent`.

    Required keys in *raw*: ``source``, ``source_id``, ``timestamp``.
    Optional keys: ``confidence`` (default 0.0), ``uncertainty`` (default 1.0),
    ``seq`` (default 0), ``payload`` (default {}).
    """
    if not isinstance(raw, dict):
        raise IngestRejection("event must be a dict", raw=raw)

    # --- required fields ---
    source_val = raw.get("source")
    if source_val is None:
        raise IngestRejection("missing required field 'source'", raw=raw)
    source = _validate_source(str(source_val))

    source_id = raw.get("source_id")
    if source_id is None:
        raise IngestRejection("missing required field 'source_id'", raw=raw)

    timestamp = raw.get("timestamp")
    if timestamp is None:
        raise IngestRejection("missing required field 'timestamp'", raw=raw)

    # --- optional fields with safe defaults ---
    confidence = float(raw.get("confidence", 0.0))
    uncertainty = float(raw.get("uncertainty", 1.0))
    seq = int(raw.get("seq", 0))
    payload = dict(raw.get("payload", {}))

    return SensorEvent(
        event_id=str(raw.get("event_id") or uuid.uuid4()),
        source=source.value,
        source_id=str(source_id),
        timestamp=str(timestamp),
        received_at=received_at or _utc_now_iso(),
        confidence=confidence,
        uncertainty=uncertainty,
        provenance=provenance,
        seq=seq,
        payload=payload,
    )


class IngestBus:
    """Local-only sensor ingest bus for the laptop fusion node.

    Collects :class:`SensorEvent` objects from contributor sources.  Each
    contributor has its own monotonically-increasing sequence counter so
    gaps or out-of-order delivery can be detected by downstream consumers.
    Events may be ingested one-by-one via :meth:`ingest`, batch-loaded from
    JSONL via :meth:`replay_jsonl`, or iterated with :meth:`drain`.
    """

    def __init__(
        self,
        *,
        max_staleness_s: float = 300.0,
        provenance: str = "local_bus",
    ) -> None:
        self.max_staleness_s = max_staleness_s
        self.provenance = provenance
        self._events: list[SensorEvent] = []
        self._seq_counters: dict[str, int] = {}
        self._rejected: list[IngestRejection] = []

    # -- public helpers --------------------------------------------------

    @property
    def events(self) -> list[SensorEvent]:
        """Snapshot of all accepted events."""
        return list(self._events)

    @property
    def rejected(self) -> list[IngestRejection]:
        """Snapshot of all rejection records."""
        return list(self._rejected)

    def count(self) -> int:
        return len(self._events)

    def rejection_count(self) -> int:
        return len(self._rejected)

    def latest(self, source: str | ContributorSource | None = None) -> SensorEvent | None:
        """Return the most-recently accepted event, optionally filtered by *source*."""
        if source is not None:
            src_val = source.value if isinstance(source, ContributorSource) else source
            filtered = [e for e in self._events if e.source == src_val]
            return filtered[-1] if filtered else None
        return self._events[-1] if self._events else None

    # -- core ingest -----------------------------------------------------

    def ingest(self, raw: dict[str, Any]) -> SensorEvent:
        """Validate, normalize, and accept a single raw event dict.

        Raises :class:`IngestRejection` (and records it internally) for
        malformed or stale events, but never crashes the fusion loop.
        """
        try:
            event = normalize_event(raw, provenance=self.provenance)
        except IngestRejection as exc:
            self._rejected.append(exc)
            raise

        # Staleness guard
        if self.max_staleness_s > 0:
            try:
                ts = datetime.fromisoformat(event.timestamp)
                now = datetime.now(UTC)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age = (now - ts).total_seconds()
                if age > self.max_staleness_s:
                    exc = IngestRejection(
                        f"event age {age:.1f}s exceeds max_staleness_s={self.max_staleness_s}",
                        raw=raw,
                    )
                    self._rejected.append(exc)
                    raise exc from None
            except (ValueError, TypeError):
                pass  # non-ISO timestamp — skip staleness check

        # Sequence tracking
        key = event.source
        expected = self._seq_counters.get(key, 0) + 1
        if event.seq > 0 and event.seq < expected:
            exc = IngestRejection(
                f"stale seq {event.seq} for source {key!r} (expected >= {expected})",
                raw=raw,
            )
            self._rejected.append(exc)
            raise exc from None
        self._seq_counters[key] = max(expected, event.seq) if event.seq > 0 else expected

        self._events.append(event)
        return event

    def ingest_many(self, raws: Iterable[dict[str, Any]]) -> list[SensorEvent]:
        """Ingest an iterable of raw event dicts, skipping rejections."""
        accepted: list[SensorEvent] = []
        for raw in raws:
            try:
                accepted.append(self.ingest(raw))
            except IngestRejection:
                continue
        return accepted

    # -- replay ----------------------------------------------------------

    def replay_jsonl(self, path: str | Any) -> list[SensorEvent]:
        """Load events from a JSONL file for deterministic replay.

        *path* can be a string path or any :class:`os.PathLike`.
        Malformed lines are silently recorded as rejections.
        """
        accepted: list[SensorEvent] = []
        with open(path) as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._rejected.append(
                        IngestRejection(f"line {line_no}: invalid JSON: {exc}", raw=line)
                    )
                    continue
                try:
                    accepted.append(self.ingest(raw))
                except IngestRejection:
                    continue
        return accepted

    # -- drain / snapshot ------------------------------------------------

    def drain(self) -> Iterator[SensorEvent]:
        """Yield all accepted events and clear the internal buffer."""
        while self._events:
            yield self._events.pop(0)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a JSON-serializable snapshot of all accepted events."""
        return [e.to_dict() for e in self._events]

    def write_jsonl(self, path: str | Any) -> int:
        """Append all accepted events to a JSONL file for later replay."""
        count = 0
        with open(path, "a") as fh:
            for event in self._events:
                fh.write(event.to_jsonl() + "\n")
                count += 1
        return count
