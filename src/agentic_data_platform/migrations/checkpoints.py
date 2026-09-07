from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agentic_data_platform.migrations.models import MigrationCheckpoint


class CheckpointStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("CREATE TABLE IF NOT EXISTS migration_checkpoints (checkpoint_id TEXT PRIMARY KEY, wave_id TEXT NOT NULL, object_id TEXT NOT NULL, phase TEXT NOT NULL, partition_key TEXT, status TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(wave_id, object_id, phase, partition_key))")
        self._connection.commit()

    def save(self, checkpoint: MigrationCheckpoint) -> MigrationCheckpoint:
        self._connection.execute("INSERT OR REPLACE INTO migration_checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (checkpoint.checkpoint_id, checkpoint.wave_id, checkpoint.object_id, checkpoint.phase, checkpoint.partition, checkpoint.status, json.dumps(checkpoint.evidence), checkpoint.created_at))
        self._connection.commit()
        return checkpoint

    def completed(self, wave_id: str, object_id: str, phase: str, partition: str | None = None) -> bool:
        row = self._connection.execute("SELECT 1 FROM migration_checkpoints WHERE wave_id = ? AND object_id = ? AND phase = ? AND partition_key IS ? AND status = 'COMPLETE'", (wave_id, object_id, phase, partition)).fetchone()
        return row is not None

    def list(self, wave_id: str) -> list[MigrationCheckpoint]:
        rows = self._connection.execute("SELECT * FROM migration_checkpoints WHERE wave_id = ? ORDER BY created_at", (wave_id,)).fetchall()
        return [MigrationCheckpoint(row["wave_id"], row["object_id"], row["phase"], row["partition_key"], row["status"], json.loads(row["evidence_json"]), row["checkpoint_id"], row["created_at"]) for row in rows]
