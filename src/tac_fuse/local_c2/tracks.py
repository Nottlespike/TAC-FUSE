"""Track authority for persistent tracks with source attribution and stale handling.

Alpha, Bravo, Charlie, and Delta emit simple local classification/prioritization
cues.  The laptop (this module) creates persistent tracks from those cues with
full source attribution and configurable stale-track handling.

Tracks are persisted to the underlying :class:`MissionStateStore` so they
survive connectivity loss and remain available for offline replay and export.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from tac_fuse.mission_state import MissionStateStore

# ── Classification / prioritization cues ────────────────────────────────────


class ClassificationCue(StrEnum):
    """Local classification cues emitted by drone sensors."""

    UNKNOWN = "unknown"
    PERSON = "person"
    VEHICLE = "vehicle"
    STRUCTURE = "structure"
    RF_SOURCE = "rf_source"
    MOVEMENT = "movement"


class PriorityCue(StrEnum):
    """Local prioritization of sensor cues."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Source attribution ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceAttribution:
    """Provenance record: which drone emitted the cue and when."""

    source_id: str
    sensor_type: str
    timestamp: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Staleness policy ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrackStalenessPolicy:
    """Policy for marking tracks as stale.

    A track is stale when the elapsed time since its last update exceeds
    *max_age_seconds*.  Stale tracks are flagged but never deleted — they
    remain in the persistent store for offline replay.
    """

    max_age_seconds: float = 60.0
    critical_max_age_seconds: float = 30.0

    def is_stale(self, last_updated_iso: str, *, now_iso: str = "") -> bool:
        """Return True if the track is stale based on elapsed time."""
        threshold = self.max_age_seconds
        try:
            updated = datetime.fromisoformat(last_updated_iso)
            now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
            elapsed = (now - updated).total_seconds()
            return elapsed > threshold
        except (ValueError, TypeError):
            return True


# ── Asset track cue ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetTrackCue:
    """A single classification/prioritization cue from a drone sensor.

    This is the lightweight structure that Alpha, Bravo, Charlie, and Delta
    emit to the laptop.  The laptop's :class:`TrackAuthority` assembles
    these into persistent tracks.
    """

    cue_id: str
    asset_id: str
    classification: str
    priority: str
    source: SourceAttribution
    lat: float = 0.0
    lon: float = 0.0
    alt_m: float = 0.0
    range_m: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Track authority ─────────────────────────────────────────────────────────


class TrackAuthority:
    """Laptop-side track authority for persistent tracks from drone cues.

    Manages the lifecycle of tracks: creation from cues, source attribution,
    staleness detection, and persistence to the mission-state store.
    """

    def __init__(
        self,
        store: MissionStateStore,
        staleness_policy: TrackStalenessPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = staleness_policy or TrackStalenessPolicy()
        self._tracks: dict[str, dict[str, Any]] = {}

    def ingest_cue(self, cue: AssetTrackCue) -> dict[str, Any]:
        """Ingest a drone cue and create/update a persistent track.

        If a track already exists for the same *cue_id*, it is updated with
        the new cue data (merge).  The track is persisted to the mission-state
        store as an asset_state row with full source attribution.
        """
        track = {
            "track_id": cue.cue_id,
            "asset_id": cue.asset_id,
            "classification": cue.classification,
            "priority": cue.priority,
            "lat": cue.lat,
            "lon": cue.lon,
            "alt_m": cue.alt_m,
            "range_m": cue.range_m,
            "source": cue.source.to_dict(),
            "last_updated": cue.source.timestamp,
            "is_stale": False,
            "metadata": dict(cue.metadata),
        }

        # Check staleness
        track["is_stale"] = self._policy.is_stale(cue.source.timestamp)

        self._tracks[cue.cue_id] = track

        # Persist to mission-state store
        self._store.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_c2_tracks (
                track_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'unknown',
                priority TEXT NOT NULL DEFAULT 'low',
                lat REAL NOT NULL DEFAULT 0.0,
                lon REAL NOT NULL DEFAULT 0.0,
                alt_m REAL NOT NULL DEFAULT 0.0,
                range_m REAL NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL DEFAULT '{}',
                last_updated TEXT NOT NULL,
                is_stale INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        self._store.conn.execute(
            """
            INSERT OR REPLACE INTO local_c2_tracks
            (track_id, asset_id, classification, priority, lat, lon,
             alt_m, range_m, source, last_updated, is_stale, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track["track_id"],
                track["asset_id"],
                track["classification"],
                track["priority"],
                track["lat"],
                track["lon"],
                track["alt_m"],
                track["range_m"],
                str(cue.source.to_dict()),
                track["last_updated"],
                1 if track["is_stale"] else 0,
                str(dict(cue.metadata)),
            ),
        )
        self._store.conn.commit()
        return track

    def get_track(self, track_id: str) -> dict[str, Any] | None:
        """Get a track by ID from the persistent store."""
        self._store.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_c2_tracks (
                track_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'unknown',
                priority TEXT NOT NULL DEFAULT 'low',
                lat REAL NOT NULL DEFAULT 0.0,
                lon REAL NOT NULL DEFAULT 0.0,
                alt_m REAL NOT NULL DEFAULT 0.0,
                range_m REAL NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL DEFAULT '{}',
                last_updated TEXT NOT NULL,
                is_stale INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        row = self._store.conn.execute(
            "SELECT * FROM local_c2_tracks WHERE track_id = ?",
            (track_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        return d

    def list_tracks(
        self,
        *,
        asset_id: str | None = None,
        include_stale: bool = True,
    ) -> list[dict[str, Any]]:
        """List tracks, optionally filtered by asset and staleness."""
        self._store.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_c2_tracks (
                track_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'unknown',
                priority TEXT NOT NULL DEFAULT 'low',
                lat REAL NOT NULL DEFAULT 0.0,
                lon REAL NOT NULL DEFAULT 0.0,
                alt_m REAL NOT NULL DEFAULT 0.0,
                range_m REAL NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL DEFAULT '{}',
                last_updated TEXT NOT NULL,
                is_stale INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        query = "SELECT * FROM local_c2_tracks"
        conditions: list[str] = []
        params: list[Any] = []

        if asset_id is not None:
            conditions.append("asset_id = ?")
            params.append(asset_id)
        if not include_stale:
            conditions.append("is_stale = 0")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY last_updated"

        rows = self._store.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def mark_stale_tracks(self, *, now_iso: str = "") -> int:
        """Scan all tracks and mark stale ones.  Returns count of newly stale."""
        count = 0
        now = now_iso or datetime.now(UTC).isoformat()
        for track_id, track in self._tracks.items():
            if not track.get("is_stale") and self._policy.is_stale(
                track.get("last_updated", ""), now_iso=now
            ):
                track["is_stale"] = True
                self._tracks[track_id] = track
                count += 1
        return count

    @staticmethod
    def compute_range_m(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Haversine distance in metres between two WGS-84 points."""
        r = 6_371_000.0
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (
            math.sin(d_lat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(d_lon / 2) ** 2
        )
        return r * 2 * math.asin(math.sqrt(min(1.0, a)))
