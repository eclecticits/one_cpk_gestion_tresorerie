from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from onec_attendance_agent.models.events import NormalizedPunch

RETRY_DELAYS_SECONDS = (60, 120, 300, 600, 1800)


class SQLitePunchQueue:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS local_punch_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    external_reference TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    synced_at TEXT,
                    UNIQUE(device_id, external_reference)
                )
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(local_punch_queue)").fetchall()}
            if "next_attempt_at" not in columns:
                db.execute("ALTER TABLE local_punch_queue ADD COLUMN next_attempt_at TEXT")

    def enqueue(self, punch: NormalizedPunch) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO local_punch_queue
                    (device_id, external_reference, payload_json, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (punch.device_id, punch.external_reference, json.dumps(punch.to_payload()), datetime.now(timezone.utc).isoformat()),
            )

    def pending(self, limit: int = 100) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, device_id, external_reference, payload_json, retry_count
                FROM local_punch_queue
                WHERE status='pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY id
                LIMIT ?
                """,
                (datetime.now(timezone.utc).isoformat(), limit),
            ).fetchall()
        return [
            {"id": row[0], "device_id": row[1], "external_reference": row[2], "payload": json.loads(row[3]), "retry_count": row[4]}
            for row in rows
        ]

    def mark_synced(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._connect() as db:
            db.executemany(
                "UPDATE local_punch_queue SET status='synced', synced_at=? WHERE id=?",
                [(datetime.now(timezone.utc).isoformat(), row_id) for row_id in ids],
            )

    def mark_error(self, row_id: int, error: str) -> None:
        with self._connect() as db:
            current_retry = int(db.execute("SELECT retry_count FROM local_punch_queue WHERE id=?", (row_id,)).fetchone()[0])
        delay = RETRY_DELAYS_SECONDS[min(current_retry, len(RETRY_DELAYS_SECONDS) - 1)]
        next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        with self._connect() as db:
            db.execute(
                "UPDATE local_punch_queue SET retry_count=retry_count+1, last_error=?, next_attempt_at=? WHERE id=?",
                (error[:500], next_attempt_at.isoformat(), row_id),
            )

    def pending_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM local_punch_queue WHERE status='pending'").fetchone()[0])
