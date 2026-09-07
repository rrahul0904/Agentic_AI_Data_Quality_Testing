"""SQLite-backed local quality evidence store with Snowflake-compatible fields."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentic_data_platform.models import new_id, utc_now


_SCHEMA = """
CREATE TABLE IF NOT EXISTS quality_runs (
  run_id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
  completed_at TEXT, details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_results (
  result_id TEXT PRIMARY KEY, check_id TEXT NOT NULL, run_id TEXT NOT NULL, system TEXT NOT NULL,
  layer TEXT NOT NULL, asset TEXT NOT NULL, check_type TEXT NOT NULL, severity TEXT NOT NULL,
  status TEXT NOT NULL, observed_value_json TEXT, expected_value_json TEXT, batch_id TEXT,
  timestamp TEXT NOT NULL, details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_results (
  result_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, metric TEXT NOT NULL, status TEXT NOT NULL,
  result_json TEXT NOT NULL, timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
  pipeline_run_id TEXT PRIMARY KEY, pipeline TEXT NOT NULL, batch_id TEXT, status TEXT NOT NULL,
  started_at TEXT NOT NULL, completed_at TEXT, details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_results_run ON quality_results(run_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_run ON reconciliation_results(run_id);
"""


@dataclass(frozen=True)
class QualityResult:
    check_id: str
    run_id: str
    system: str
    layer: str
    asset: str
    check_type: str
    severity: str
    status: str
    observed_value: Any = None
    expected_value: Any = None
    batch_id: str | None = None
    timestamp: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)
    result_id: str = field(default_factory=lambda: new_id("dq"))


class SQLiteQualityStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def start_run(self, name: str, *, details: dict[str, Any] | None = None, run_id: str | None = None) -> str:
        identifier = run_id or new_id("quality_run")
        self._connection.execute(
            "INSERT INTO quality_runs VALUES (?, ?, 'RUNNING', ?, NULL, ?)",
            (identifier, name, utc_now(), json.dumps(details or {}, sort_keys=True)),
        )
        self._connection.commit()
        return identifier

    def complete_run(self, run_id: str, status: str) -> None:
        if status not in {"PASS", "FAIL", "ERROR"}:
            raise ValueError("quality run status must be PASS, FAIL, or ERROR")
        cursor = self._connection.execute(
            "UPDATE quality_runs SET status = ?, completed_at = ? WHERE run_id = ?",
            (status, utc_now(), run_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"quality run not found: {run_id}")
        self._connection.commit()

    def save_result(self, result: QualityResult) -> str:
        self._connection.execute(
            "INSERT INTO quality_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.result_id, result.check_id, result.run_id, result.system, result.layer, result.asset,
                result.check_type, result.severity, result.status, json.dumps(result.observed_value),
                json.dumps(result.expected_value), result.batch_id, result.timestamp,
                json.dumps(result.details, sort_keys=True),
            ),
        )
        self._connection.commit()
        return result.result_id

    def save_reconciliation(self, run_id: str, result: dict[str, Any]) -> str:
        identifier = new_id("recon")
        self._connection.execute(
            "INSERT INTO reconciliation_results VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, run_id, result["metric"], result["status"], json.dumps(result, sort_keys=True), utc_now()),
        )
        self._connection.commit()
        return identifier

    def list_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM quality_results WHERE run_id = ? ORDER BY timestamp, result_id", (run_id,)
        ).fetchall()
        return [self._decode_quality(row) for row in rows]

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM quality_runs ORDER BY started_at DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
        return [
            {
                **dict(row),
                "details": json.loads(row["details_json"] or "{}"),
            }
            for row in rows
        ]

    def recent_results(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM quality_results ORDER BY timestamp DESC, result_id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [self._decode_quality(row) for row in rows]

    def recent_reconciliations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM reconciliation_results ORDER BY timestamp DESC, result_id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [
            {
                "result_id": row["result_id"],
                "run_id": row["run_id"],
                "metric": row["metric"],
                "status": row["status"],
                "timestamp": row["timestamp"],
                "result": json.loads(row["result_json"]),
            }
            for row in rows
        ]

    def summary(self) -> dict[str, Any]:
        def count(table: str) -> int:
            row = self._connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            return int(row["count"])

        status_rows = self._connection.execute(
            "SELECT status, COUNT(*) AS count FROM quality_results GROUP BY status"
        ).fetchall()
        reconciliation_rows = self._connection.execute(
            "SELECT status, COUNT(*) AS count FROM reconciliation_results GROUP BY status"
        ).fetchall()
        return {
            "database": self.path,
            "run_count": count("quality_runs"),
            "result_count": count("quality_results"),
            "reconciliation_count": count("reconciliation_results"),
            "status_counts": {row["status"]: row["count"] for row in status_rows},
            "reconciliation_status_counts": {row["status"]: row["count"] for row in reconciliation_rows},
            "recent_results": self.recent_results(12),
            "recent_reconciliations": self.recent_reconciliations(12),
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM quality_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _decode_quality(row: sqlite3.Row) -> dict[str, Any]:
        return {
            **dict(row),
            "observed_value": json.loads(row["observed_value_json"]) if row["observed_value_json"] else None,
            "expected_value": json.loads(row["expected_value_json"]) if row["expected_value_json"] else None,
            "details": json.loads(row["details_json"] or "{}"),
        }

    @staticmethod
    def as_snowflake_payload(result: QualityResult) -> dict[str, Any]:
        """Return a redaction-safe mapping suitable for AUDIT.DATA_QUALITY_RESULTS."""

        return asdict(result)
