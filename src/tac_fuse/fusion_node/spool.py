"""Durable offline storage for the laptop fusion node.

Provides:
- Append-only local event log for contributor events
- Fused-state snapshots at deterministic intervals
- Sync watermark and receipt tracking
- Idempotency keys for reconnect upload
- Corruption-tolerant JSONL read path with checksums
- Redacted inspection output for operator debugging
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _checksum_hex(payload: object) -> str:
    """Deterministic SHA-256 hex digest of a JSON-serialisable payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


def _redact(payload: dict[str, Any], *, drop_keys: set[str] | None = None) -> dict[str, Any]:
    """Return a copy of *payload* with sensitive keys redacted."""
    drop = drop_keys or {"raw_binary", "gps_coordinates", "operator_token"}
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in drop:
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = _redact(v, drop_keys=drop)
        elif isinstance(v, list):
            out[k] = [_redact(item, drop_keys=drop) if isinstance(item, dict) else item for item in v]
        else:
            out[k] = v
    return out


class FusionSpool:
    """Durable offline store for contributor events and fused state."""

    def __init__(
        self,
        *,
        sqlite_path: str | Path | None = None,
        jsonl_path: str | Path | None = None,
        db_path: str | Path | None = None,
        snapshot_interval: int = 5,
        node_id: str = "laptop-fusion-node",
    ) -> None:
        self.sqlite_path = str(sqlite_path or db_path or ":memory:")
        self.jsonl_path = str(jsonl_path or f"{self.sqlite_path}.jsonl")
        self.snapshot_interval = snapshot_interval
        self.node_id = node_id
        self._conn = sqlite3.connect(self.sqlite_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                seq INTEGER NOT NULL,
                contributor TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                idempotency_key TEXT UNIQUE NOT NULL,
                timestamp TEXT NOT NULL,
                checksum TEXT NOT NULL,
                node_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                seq INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS watermarks (
                contributor TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'local',
                watermark_seq INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (contributor, source)
            );
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT 'upstream-api',
                synced_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'synced'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_key
            ON receipts(idempotency_key, target);
            """
        )
        self._conn.commit()

    def _next_seq(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) AS mx FROM events").fetchone()
        return int(row["mx"]) + 1

    def _append_jsonl_line(self, record: dict[str, Any]) -> None:
        path = Path(self.jsonl_path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    # -- public API ---------------------------------------------------------

    def append_event(
        self,
        *,
        contributor: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append a contributor event (idempotent via *idempotency_key*)."""
        key = idempotency_key or str(uuid.uuid4())
        ts = timestamp or _utc_now()
        payload_dict = dict(payload or {})
        checksum = _checksum_hex({
            "contributor": contributor,
            "event_type": event_type,
            "payload": payload_dict,
        })
        seq = self._next_seq()

        record = {
            "id": str(uuid.uuid4()),
            "seq": seq,
            "contributor": contributor,
            "event_type": event_type,
            "payload": payload_dict,
            "idempotency_key": key,
            "timestamp": ts,
            "checksum": checksum,
            "node_id": self.node_id,
        }

        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO events
                (id, seq, contributor, event_type, payload, idempotency_key, timestamp, checksum, node_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"], record["seq"], record["contributor"],
                    record["event_type"],
                    json.dumps(record["payload"], sort_keys=True),
                    record["idempotency_key"], record["timestamp"],
                    record["checksum"], record["node_id"],
                ),
            )
        self._append_jsonl_line(record)

        if record["seq"] % self.snapshot_interval == 0:
            self._take_snapshot()

        return record

    def get_snapshot(self, seq: int | None = None, *, latest: bool = True) -> dict[str, Any] | None:
        """Return a fused-state snapshot."""
        if seq is not None:
            row = self._conn.execute("SELECT * FROM snapshots WHERE seq = ?", (seq,)).fetchone()
        elif latest:
            row = self._conn.execute("SELECT * FROM snapshots ORDER BY seq DESC LIMIT 1").fetchone()
        else:
            row = self._conn.execute("SELECT * FROM snapshots ORDER BY seq ASC LIMIT 1").fetchone()

        if row is None:
            return None
        return {"seq": int(row["seq"]), "state": json.loads(row["state"]), "created_at": row["created_at"]}

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Return all snapshots ordered by sequence."""
        rows = self._conn.execute("SELECT * FROM snapshots ORDER BY seq").fetchall()
        return [
            {"seq": int(r["seq"]), "state": json.loads(r["state"]), "created_at": r["created_at"]}
            for r in rows
        ]

    def set_watermark(self, contributor: str, watermark_seq: int, *, source: str = "local") -> dict[str, Any]:
        """Record a sync watermark for a contributor."""
        ts = _utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO watermarks (contributor, watermark_seq, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(contributor, source) DO UPDATE
                SET watermark_seq = ?, updated_at = ?
                """,
                (contributor, watermark_seq, source, ts, watermark_seq, ts),
            )
        return {"contributor": contributor, "watermark_seq": watermark_seq, "source": source, "updated_at": ts}

    def get_watermark(self, contributor: str, *, source: str = "local") -> int | None:
        """Return the watermark sequence number for a contributor."""
        row = self._conn.execute(
            "SELECT watermark_seq FROM watermarks WHERE contributor = ? AND source = ?",
            (contributor, source),
        ).fetchone()
        return int(row["watermark_seq"]) if row else None

    def add_receipt(
        self,
        *,
        idempotency_key: str,
        synced_at: str | None = None,
        target: str = "upstream-api",
        status: str = "synced",
    ) -> dict[str, Any]:
        """Record an upload receipt for a synced event."""
        ts = synced_at or _utc_now()
        receipt = {
            "id": str(uuid.uuid4()),
            "idempotency_key": idempotency_key,
            "target": target,
            "synced_at": ts,
            "status": status,
        }
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO receipts (id, idempotency_key, target, synced_at, status) VALUES (?, ?, ?, ?, ?)",
                (receipt["id"], receipt["idempotency_key"], receipt["target"], receipt["synced_at"], receipt["status"]),
            )
        return receipt

    def list_synced_keys(self, *, target: str | None = None) -> list[str]:
        """Return idempotency keys that have been synced."""
        if target:
            rows = self._conn.execute(
                "SELECT DISTINCT idempotency_key FROM receipts WHERE target = ? ORDER BY synced_at",
                (target,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT DISTINCT idempotency_key FROM receipts ORDER BY synced_at"
            ).fetchall()
        return [r["idempotency_key"] for r in rows]

    def pending_events(self, *, target: str = "upstream-api") -> list[dict[str, Any]]:
        """Return events that have no sync receipt for *target*."""
        synced = set(self.list_synced_keys(target=target))
        rows = self._conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        pending: list[dict[str, Any]] = []
        for row in rows:
            key = row["idempotency_key"]
            if key not in synced:
                pending.append({
                    "id": row["id"], "seq": int(row["seq"]),
                    "contributor": row["contributor"], "event_type": row["event_type"],
                    "payload": json.loads(row["payload"]),
                    "idempotency_key": key, "timestamp": row["timestamp"],
                    "checksum": row["checksum"],
                })
        return pending

    def _take_snapshot(self) -> dict[str, Any]:
        """Create a fused-state snapshot of all events up to current seq."""
        rows = self._conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        state: dict[str, Any] = {
            "node_id": self.node_id,
            "events": [
                {"seq": int(r["seq"]), "contributor": r["contributor"],
                 "event_type": r["event_type"], "timestamp": r["timestamp"]}
                for r in rows
            ],
            "event_count": len(rows),
        }
        ts = _utc_now()
        last_seq = int(rows[-1]["seq"]) if rows else 0
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO snapshots (seq, state, created_at) VALUES (?, ?, ?)",
                (last_seq, json.dumps(state, sort_keys=True), ts),
            )
        return {"seq": last_seq, "state": state, "created_at": ts}

    # -- JSONL corruption-tolerant read -------------------------------------

    def read_jsonl_healthy(self) -> list[dict[str, Any]]:
        """Read all valid events from the JSONL side-car, skipping corrupt records."""
        path = Path(self.jsonl_path)
        if not path.exists():
            return []
        healthy: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("JSONL line %d: corrupt JSON, skipping", lineno)
                    continue
                inner = {"contributor": record.get("contributor", ""), "event_type": record.get("event_type", ""), "payload": record.get("payload", {})}
                if record.get("checksum") != _checksum_hex(inner):
                    logger.warning("JSONL line %d: checksum mismatch, skipping", lineno)
                    continue
                healthy.append(record)
        return healthy

    def jsonl_stats(self) -> dict[str, Any]:
        """Return stats about JSONL integrity."""
        path = Path(self.jsonl_path)
        if not path.exists():
            return {"jsonl_exists": False, "total_lines": 0, "healthy": 0, "corrupt": 0}
        total = healthy = corrupt = 0
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    corrupt += 1
                    continue
                inner = {"contributor": record.get("contributor", ""), "event_type": record.get("event_type", ""), "payload": record.get("payload", {})}
                if record.get("checksum") == _checksum_hex(inner):
                    healthy += 1
                else:
                    corrupt += 1
        return {"jsonl_exists": True, "total_lines": total, "healthy": healthy, "corrupt": corrupt}

    # -- Redacted inspection ------------------------------------------------

    def inspect_redacted(self, *, limit: int | None = None) -> dict[str, Any]:
        """Return a redacted view suitable for operator debugging."""
        rows = self._conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            raw_payload = json.loads(row["payload"])
            payload = _redact(raw_payload)
            expected_cs = _checksum_hex({
                "contributor": row["contributor"], "event_type": row["event_type"], "payload": raw_payload,
            })
            events.append({
                "seq": int(row["seq"]), "contributor": row["contributor"],
                "event_type": row["event_type"], "payload": payload,
                "idempotency_key": row["idempotency_key"], "timestamp": row["timestamp"],
                "checksum_ok": row["checksum"] == expected_cs,
            })
            if limit and len(events) >= limit:
                break

        latest_snap = self.get_snapshot(latest=True)
        watermarks = [dict(w) for w in self._conn.execute("SELECT * FROM watermarks ORDER BY contributor").fetchall()]
        synced_keys = set(self.list_synced_keys())

        return {
            "node_id": self.node_id,
            "event_count": len(rows),
            "events": events,
            "latest_snapshot_seq": latest_snap["seq"] if latest_snap else None,
            "watermarks": watermarks,
            "pending_count": len(rows) - len(synced_keys),
            "jsonl_stats": self.jsonl_stats(),
        }

    # -- Replay for idempotency / resync ------------------------------------

    def replay_events(
        self,
        *,
        from_seq: int = 1,
        contributor: str | None = None,
        to_spool: "FusionSpool | None" = None,
    ) -> list[dict[str, Any]]:
        """Replay events for migration or idempotent re-ingest."""
        q = "SELECT * FROM events WHERE seq >= ?"
        params: list[Any] = [from_seq]
        if contributor:
            q += " AND contributor = ?"
            params.append(contributor)
        q += " ORDER BY seq"

        rows = self._conn.execute(q, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            record = {
                "id": row["id"], "seq": int(row["seq"]),
                "contributor": row["contributor"], "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "idempotency_key": row["idempotency_key"], "timestamp": row["timestamp"],
                "checksum": row["checksum"],
            }
            if to_spool:
                to_spool.append_event(
                    contributor=record["contributor"],
                    event_type=record["event_type"],
                    payload=record["payload"],
                    idempotency_key=record["idempotency_key"],
                    timestamp=record["timestamp"],
                )
            results.append(record)
        return results
