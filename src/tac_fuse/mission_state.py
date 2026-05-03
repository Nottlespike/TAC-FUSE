"""Local-first SQLite state store for TAC-FUSE."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class MissionStateStore:
    """Persist operator state locally before any Foundry-style export."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        db_path: str | Path | None = None,
        operator: str = "demo_operator",
    ) -> None:
        self.path = str(db_path or path or ":memory:")
        self.operator = operator
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def _utc_now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS operator_tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS asset_states (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                timestamp_s REAL NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS restricted_entries (
                id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                entry_timestamp_s REAL NOT NULL,
                severity TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS route_conflicts (
                id TEXT PRIMARY KEY,
                conflict_id TEXT NOT NULL,
                asset_ids TEXT NOT NULL,
                timestamp_s REAL NOT NULL,
                severity TEXT NOT NULL,
                range_m REAL NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_queue (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                message TEXT NOT NULL,
                operator TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def create_task(self, data: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
        payload = {**dict(data or {}), **fields}
        now = self._utc_now()
        task = {
            "id": str(payload.get("id") or uuid.uuid4()),
            "title": str(payload.get("title") or "Untitled task"),
            "description": str(payload.get("description") or ""),
            "status": str(payload.get("status") or "pending"),
            "metadata": dict(payload.get("metadata") or {}),
            "created_at": str(payload.get("created_at") or now),
            "updated_at": str(payload.get("updated_at") or now),
        }
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO operator_tasks
                (id, title, description, status, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["id"],
                    task["title"],
                    task["description"],
                    task["status"],
                    json.dumps(task["metadata"], sort_keys=True),
                    task["created_at"],
                    task["updated_at"],
                ),
            )
            self._enqueue_sync("operator_task", task["id"], "create", task)
            self._audit("task_created", "operator_task", task["id"], f"Created {task['title']}")
        return task

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        current = self.get_task(task_id)
        if current is None:
            raise KeyError(task_id)
        updated = {**current, **fields, "updated_at": self._utc_now()}
        if "metadata" in fields:
            updated["metadata"] = dict(fields["metadata"] or {})
        with self._conn:
            self._conn.execute(
                """
                UPDATE operator_tasks
                SET title = ?, description = ?, status = ?, metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated["title"],
                    updated["description"],
                    updated["status"],
                    json.dumps(updated["metadata"], sort_keys=True),
                    updated["updated_at"],
                    task_id,
                ),
            )
            self._enqueue_sync("operator_task", task_id, "update", updated)
            self._audit("task_updated", "operator_task", task_id, f"Updated task {task_id}")
        return updated

    def insert_tracks(self, tracks: Iterable[Any]) -> int:
        track_payloads = [self._object_payload(track) for track in tracks]
        now = self._utc_now()
        with self._conn:
            for payload in track_payloads:
                self._conn.execute(
                    """
                    INSERT INTO asset_states
                    (id, asset_id, timestamp_s, payload, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        str(payload["asset_id"]),
                        float(payload.get("timestamp_s", payload.get("timestamp", 0.0))),
                        json.dumps(payload, sort_keys=True),
                        now,
                    ),
                )
            self._audit(
                "tracks_inserted",
                "asset_state",
                "frame",
                f"Inserted {len(track_payloads)} asset tracks",
            )
        return len(track_payloads)

    def create_alert(
        self,
        message: str,
        *,
        severity: str = "watch",
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        alert = {
            "id": str(uuid.uuid4()),
            "severity": severity,
            "message": message,
            "payload": dict(payload or {}),
            "created_at": self._utc_now(),
        }
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO alerts (id, severity, message, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    alert["id"],
                    alert["severity"],
                    alert["message"],
                    json.dumps(alert["payload"], sort_keys=True),
                    alert["created_at"],
                ),
            )
            self._enqueue_sync("alert", alert["id"], "create", alert)
            self._audit("alert_created", "alert", alert["id"], message)
        return alert

    def insert_restricted_entry(self, entry: Any) -> dict[str, Any]:
        payload = self._object_payload(entry)
        record = {
            "id": str(payload.get("entry_id") or payload.get("id") or uuid.uuid4()),
            "asset_id": str(payload["asset_id"]),
            "zone_id": str(payload["zone_id"]),
            "entry_timestamp_s": float(
                payload.get("entry_timestamp_s", payload.get("entry_timestamp", 0.0))
            ),
            "severity": str(payload.get("severity") or "watch"),
            "payload": payload,
            "created_at": self._utc_now(),
        }
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO restricted_entries
                (id, asset_id, zone_id, entry_timestamp_s, severity, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["asset_id"],
                    record["zone_id"],
                    record["entry_timestamp_s"],
                    record["severity"],
                    json.dumps(record["payload"], sort_keys=True),
                    record["created_at"],
                ),
            )
            if cursor.rowcount:
                self._enqueue_sync("restricted_entry", record["id"], "create", record)
                self._audit(
                    "restricted_entry_inserted",
                    "restricted_entry",
                    record["id"],
                    f"{record['asset_id']} entered {record['zone_id']}",
                )
        return record

    def insert_route_conflict(self, conflict: Any) -> dict[str, Any]:
        payload = self._object_payload(conflict)
        conflict_id = str(payload.get("conflict_id") or payload.get("id") or uuid.uuid4())
        record = {
            "id": conflict_id,
            "conflict_id": conflict_id,
            "asset_ids": [str(asset_id) for asset_id in payload["asset_ids"]],
            "timestamp_s": float(payload.get("timestamp_s", payload.get("timestamp", 0.0))),
            "severity": str(payload.get("severity") or "watch"),
            "range_m": float(payload.get("range_m", 0.0)),
            "payload": payload,
            "created_at": self._utc_now(),
        }
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO route_conflicts
                (id, conflict_id, asset_ids, timestamp_s, severity, range_m, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["conflict_id"],
                    json.dumps(record["asset_ids"], sort_keys=True),
                    record["timestamp_s"],
                    record["severity"],
                    record["range_m"],
                    json.dumps(record["payload"], sort_keys=True),
                    record["created_at"],
                ),
            )
            if cursor.rowcount:
                self._enqueue_sync("route_conflict", record["conflict_id"], "create", record)
                self._audit(
                    "route_conflict_inserted",
                    "route_conflict",
                    record["conflict_id"],
                    f"Route conflict {record['conflict_id']} recorded",
                )
        return record

    def put_dashboard_value(self, key: str, value: str) -> dict[str, str]:
        record = {"key": key, "value": value, "updated_at": self._utc_now()}
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                INSERT OR REPLACE INTO demo_state (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (record["key"], record["value"], record["updated_at"]),
            )
            self._audit(
                "dashboard_value_updated",
                "demo_state",
                record["key"],
                f"Dashboard value updated: {record['key']}",
            )
        return record

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM operator_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM operator_tasks ORDER BY created_at").fetchall()
        return [self._task_from_row(row) for row in rows]

    def count_tracks(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM asset_states").fetchone()
        return int(row["count"])

    def list_asset_states(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM asset_states ORDER BY timestamp_s, asset_id"
        ).fetchall()
        return [self._json_row(row) for row in rows]

    def list_alerts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM alerts ORDER BY created_at").fetchall()
        return [self._json_row(row) for row in rows]

    def list_restricted_entries(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM restricted_entries ORDER BY entry_timestamp_s, asset_id"
        ).fetchall()
        return [self._json_row(row) for row in rows]

    def list_route_conflicts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM route_conflicts ORDER BY timestamp_s, conflict_id"
        ).fetchall()
        return [self._conflict_from_row(row) for row in rows]

    def list_audit_events(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM audit_log ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def pending_sync_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM sync_queue WHERE status = 'pending'"
        ).fetchone()
        return int(row["count"])

    def list_sync_queue(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM sync_queue ORDER BY created_at").fetchall()
        return [self._sync_from_row(row) for row in rows]

    def _enqueue_sync(
        self,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: Mapping[str, Any],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sync_queue
            (id, entity_type, entity_id, operation, payload, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                str(uuid.uuid4()),
                entity_type,
                entity_id,
                operation,
                json.dumps(dict(payload), sort_keys=True),
                self._utc_now(),
            ),
        )

    def _audit(self, event_type: str, entity_type: str, entity_id: str, message: str) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_log
            (id, event_type, entity_type, entity_id, message, operator, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                event_type,
                entity_type,
                entity_id,
                message,
                self.operator,
                self._utc_now(),
            ),
        )

    @staticmethod
    def _object_payload(value: Any) -> dict[str, Any]:
        if hasattr(value, "to_dict"):
            return dict(value.to_dict())
        if isinstance(value, Mapping):
            return dict(value)
        raise TypeError(f"cannot serialize {type(value)!r}")

    @staticmethod
    def _json_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        if "payload" in payload:
            payload["payload"] = json.loads(payload["payload"])
        return payload

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["metadata"] = json.loads(payload["metadata"])
        return payload

    @staticmethod
    def _sync_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["payload"] = json.loads(payload["payload"])
        return payload

    @staticmethod
    def _conflict_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        payload["asset_ids"] = json.loads(payload["asset_ids"])
        payload["payload"] = json.loads(payload["payload"])
        return payload
