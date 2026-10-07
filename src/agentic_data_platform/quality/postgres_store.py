"""PostgreSQL-backed quality evidence persistence.

This adapter preserves the public SQLite quality-store contract so hosted ADE
runtimes can keep quality runs, check results, and reconciliation evidence in a
durable shared database without changing deterministic quality tooling.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from agentic_data_platform.models import new_id, utc_now
from agentic_data_platform.quality.store import QualityResult


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


class PostgresQualityStore:
    """Durable PostgreSQL implementation of the quality evidence-store contract."""

    def __init__(self, dsn: str) -> None:
        if not dsn.startswith(("postgres://", "postgresql://")):
            raise ValueError("PostgresQualityStore requires a postgres:// or postgresql:// DSN")
        self.dsn = dsn
        self._connection: Any | None = None
        self._lock = threading.Lock()

    def _conn(self) -> Any:
        if self._connection is None:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - optional cloud dependency
                raise RuntimeError(
                    "PostgreSQL quality persistence requires psycopg; install the project with the cloud extra"
                ) from exc
            self._connection = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)
        return self._connection

    def initialize(self) -> None:
        with self._lock:
            with self._conn().cursor() as cursor:
                for statement in _SCHEMA.split(";"):
                    sql = statement.strip()
                    if sql:
                        cursor.execute(sql)

    def _execute(self, sql: str, params: tuple[Any, ...]) -> int:
        with self._lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)
                return int(cursor.rowcount)

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def start_run(self, name: str, *, details: dict[str, Any] | None = None, run_id: str | None = None) -> str:
        identifier = run_id or new_id("quality_run")
        self._execute(
            """
            INSERT INTO quality_runs (run_id, name, status, started_at, completed_at, details_json)
            VALUES (%s, %s, 'RUNNING', %s, NULL, %s)
            """,
            (identifier, name, utc_now(), json.dumps(details or {}, sort_keys=True)),
        )
        return identifier

    def complete_run(self, run_id: str, status: str) -> None:
        if status not in {"PASS", "FAIL", "ERROR"}:
            raise ValueError("quality run status must be PASS, FAIL, or ERROR")
        rowcount = self._execute(
            "UPDATE quality_runs SET status = %s, completed_at = %s WHERE run_id = %s",
            (status, utc_now(), run_id),
        )
        if rowcount != 1:
            raise KeyError(f"quality run not found: {run_id}")

    def save_result(self, result: QualityResult) -> str:
        self._execute(
            """
            INSERT INTO quality_results (
              result_id, check_id, run_id, system, layer, asset, check_type, severity,
              status, observed_value_json, expected_value_json, batch_id, timestamp, details_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.result_id,
                result.check_id,
                result.run_id,
                result.system,
                result.layer,
                result.asset,
                result.check_type,
                result.severity,
                result.status,
                json.dumps(result.observed_value),
                json.dumps(result.expected_value),
                result.batch_id,
                result.timestamp,
                json.dumps(result.details, sort_keys=True),
            ),
        )
        return result.result_id

    def save_reconciliation(self, run_id: str, result: dict[str, Any]) -> str:
        identifier = new_id("recon")
        self._execute(
            """
            INSERT INTO reconciliation_results (result_id, run_id, metric, status, result_json, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (identifier, run_id, result["metric"], result["status"], json.dumps(result, sort_keys=True), utc_now()),
        )
        return identifier

    def list_results(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM quality_results WHERE run_id = %s ORDER BY timestamp, result_id",
            (run_id,),
        )
        return [self._decode_quality(row) for row in rows]

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM quality_runs ORDER BY started_at DESC LIMIT %s",
            (max(1, min(limit, 200)),),
        )
        return [{**row, "details": json.loads(row["details_json"] or "{}")} for row in rows]

    def recent_results(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM quality_results ORDER BY timestamp DESC, result_id DESC LIMIT %s",
            (max(1, min(limit, 500)),),
        )
        return [self._decode_quality(row) for row in rows]

    def recent_reconciliations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM reconciliation_results ORDER BY timestamp DESC, result_id DESC LIMIT %s",
            (max(1, min(limit, 500)),),
        )
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
            row = self._fetchone(f"SELECT COUNT(*) AS count FROM {table}")
            return int(row["count"]) if row is not None else 0

        status_rows = self._fetchall("SELECT status, COUNT(*) AS count FROM quality_results GROUP BY status")
        reconciliation_rows = self._fetchall(
            "SELECT status, COUNT(*) AS count FROM reconciliation_results GROUP BY status"
        )
        return {
            "database": "postgresql",
            "run_count": count("quality_runs"),
            "result_count": count("quality_results"),
            "reconciliation_count": count("reconciliation_results"),
            "status_counts": {row["status"]: row["count"] for row in status_rows},
            "reconciliation_status_counts": {row["status"]: row["count"] for row in reconciliation_rows},
            "recent_results": self.recent_results(12),
            "recent_reconciliations": self.recent_reconciliations(12),
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._fetchone("SELECT * FROM quality_runs WHERE run_id = %s", (run_id,))

    @staticmethod
    def _decode_quality(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "observed_value": json.loads(row["observed_value_json"]) if row["observed_value_json"] else None,
            "expected_value": json.loads(row["expected_value_json"]) if row["expected_value_json"] else None,
            "details": json.loads(row["details_json"] or "{}"),
        }

    @staticmethod
    def as_snowflake_payload(result: QualityResult) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(result)
