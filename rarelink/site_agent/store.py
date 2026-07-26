"""SQLite-backed idempotent task/round state for one physical site."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from rarelink.site_agent.schemas import TaskRecord


class TaskStore:
    def __init__(self, path: Path) -> None:
        if path.is_symlink():
            raise ValueError("Site task state database must not be a symbolic link")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS site_tasks (
                    task_id TEXT NOT NULL,
                    round_id INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY (task_id, round_id)
                )
                """
            )
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def get(self, task_id: str, round_id: int) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM site_tasks WHERE task_id = ? AND round_id = ?",
                (task_id, round_id),
            ).fetchone()
        return TaskRecord.model_validate_json(row[0]) if row else None

    def put(self, record: TaskRecord) -> None:
        encoded = json.dumps(record.model_dump(mode="json"), separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO site_tasks (task_id, round_id, record_json)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id, round_id)
                DO UPDATE SET record_json = excluded.record_json
                """,
                (record.task_id, record.round_id, encoded),
            )

    def list(self) -> list[TaskRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM site_tasks ORDER BY task_id, round_id"
            ).fetchall()
        return [TaskRecord.model_validate_json(row[0]) for row in rows]
