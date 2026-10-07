from __future__ import annotations

import json
import threading
from dataclasses import asdict
from typing import Any

from agentic_data_platform.models import (
    ApprovalRecord,
    ExecutionEvidenceRecord,
    GeneratedArtifactRecord,
    MigrationPlanRecord,
    ProjectRecord,
    RunRecord,
    RunState,
    RunStepRecord,
    VerificationReport,
    utc_now,
)
from agentic_data_platform.persistence.repositories import ControlPlaneRepository


_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS environments (
  environment_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connections (
  connection_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  name TEXT NOT NULL,
  credential_ref TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_objects (
  object_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  object_type TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pipelines (
  pipeline_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS migration_plans (
  migration_plan_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  environment_id TEXT NOT NULL,
  intent TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_steps (
  run_step_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  name TEXT NOT NULL,
  state TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generated_artifacts (
  artifact_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  dialect TEXT,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_reports (
  report_id TEXT PRIMARY KEY,
  run_id TEXT,
  findings_json TEXT NOT NULL,
  passed INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  scope TEXT NOT NULL,
  approved INTEGER NOT NULL,
  action TEXT NOT NULL DEFAULT 'execute',
  environment TEXT,
  expires_at TEXT,
  used_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_evidence (
  evidence_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  operation TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_run_scope ON approvals(run_id, scope, approved);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON execution_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_steps_run ON run_steps(run_id, sequence);
"""


class PostgresControlPlaneRepository(ControlPlaneRepository):
    """PostgreSQL-backed control plane preserving the SQLite repository contract.

    psycopg is imported lazily so local/demo installs that only use SQLite do not
    need the warehouse/cloud extras installed.
    """

    def __init__(self, dsn: str) -> None:
        if not dsn.startswith(("postgres://", "postgresql://")):
            raise ValueError("PostgresControlPlaneRepository requires a postgres:// or postgresql:// DSN")
        self.dsn = dsn
        self._connection: Any | None = None
        self._lock = threading.Lock()

    def _conn(self) -> Any:
        if self._connection is None:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - depends on optional installation
                raise RuntimeError(
                    "PostgreSQL persistence requires psycopg; install the project with the 'cloud' or 'warehouses' extra"
                ) from exc
            self._connection = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)
        return self._connection

    def initialize(self) -> None:
        with self._lock:
            conn = self._conn()
            with conn.cursor() as cursor:
                for statement in _SCHEMA.split(";"):
                    sql = statement.strip()
                    if sql:
                        cursor.execute(sql)

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._lock:
            with self._conn().cursor() as cursor:
                cursor.execute(sql, params)

    def _fetchone(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
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

    def save_project(self, record: ProjectRecord) -> None:
        self._execute(
            """
            INSERT INTO projects (project_id, name, created_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (project_id) DO UPDATE
            SET name = EXCLUDED.name, created_at = EXCLUDED.created_at
            """,
            (record.project_id, record.name, record.created_at),
        )

    def save_run(self, record: RunRecord) -> None:
        self._execute(
            """
            INSERT INTO runs (run_id, project_id, environment_id, intent, state, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE
            SET project_id = EXCLUDED.project_id,
                environment_id = EXCLUDED.environment_id,
                intent = EXCLUDED.intent,
                state = EXCLUDED.state,
                created_at = EXCLUDED.created_at
            """,
            (
                record.run_id,
                record.project_id,
                record.environment_id,
                record.intent,
                record.state.value,
                record.created_at,
            ),
        )

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._fetchone("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        if row is None:
            return None
        return RunRecord(
            project_id=row["project_id"],
            environment_id=row["environment_id"],
            intent=row["intent"],
            state=RunState(row["state"]),
            run_id=row["run_id"],
            created_at=row["created_at"],
        )

    def save_run_step(self, record: RunStepRecord) -> None:
        self._execute(
            """
            INSERT INTO run_steps (run_step_id, run_id, name, state, sequence, detail_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_step_id) DO UPDATE
            SET run_id = EXCLUDED.run_id,
                name = EXCLUDED.name,
                state = EXCLUDED.state,
                sequence = EXCLUDED.sequence,
                detail_json = EXCLUDED.detail_json,
                created_at = EXCLUDED.created_at
            """,
            (
                record.run_step_id,
                record.run_id,
                record.name,
                record.state,
                record.sequence,
                json.dumps(record.detail),
                record.created_at,
            ),
        )

    def save_artifact(self, record: GeneratedArtifactRecord) -> None:
        self._execute(
            """
            INSERT INTO generated_artifacts (artifact_id, run_id, kind, content, dialect, version, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (artifact_id) DO UPDATE
            SET run_id = EXCLUDED.run_id,
                kind = EXCLUDED.kind,
                content = EXCLUDED.content,
                dialect = EXCLUDED.dialect,
                version = EXCLUDED.version,
                created_at = EXCLUDED.created_at
            """,
            (
                record.artifact_id,
                record.run_id,
                record.kind,
                record.content,
                record.dialect,
                record.version,
                record.created_at,
            ),
        )

    def save_migration_plan(self, record: MigrationPlanRecord) -> None:
        self._execute(
            """
            INSERT INTO migration_plans (migration_plan_id, project_id, spec_json, status, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (migration_plan_id) DO UPDATE
            SET project_id = EXCLUDED.project_id,
                spec_json = EXCLUDED.spec_json,
                status = EXCLUDED.status,
                created_at = EXCLUDED.created_at
            """,
            (
                record.migration_plan_id,
                record.project_id,
                json.dumps(record.spec),
                record.status,
                record.created_at,
            ),
        )

    def save_verification_report(self, report: VerificationReport) -> None:
        findings = [asdict(item) for item in report.findings]
        self._execute(
            """
            INSERT INTO verification_reports (report_id, run_id, findings_json, passed, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (report_id) DO UPDATE
            SET run_id = EXCLUDED.run_id,
                findings_json = EXCLUDED.findings_json,
                passed = EXCLUDED.passed,
                created_at = EXCLUDED.created_at
            """,
            (report.report_id, report.run_id, json.dumps(findings), int(report.passed), report.created_at),
        )

    def save_approval(self, record: ApprovalRecord) -> None:
        environment = record.environment.value if record.environment else None
        self._execute(
            """
            INSERT INTO approvals (
              approval_id, run_id, approved_by, scope, approved,
              action, environment, expires_at, used_at, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (approval_id) DO UPDATE
            SET run_id = EXCLUDED.run_id,
                approved_by = EXCLUDED.approved_by,
                scope = EXCLUDED.scope,
                approved = EXCLUDED.approved,
                action = EXCLUDED.action,
                environment = EXCLUDED.environment,
                expires_at = EXCLUDED.expires_at,
                used_at = EXCLUDED.used_at,
                created_at = EXCLUDED.created_at
            """,
            (
                record.approval_id,
                record.run_id,
                record.approved_by,
                record.scope,
                int(record.approved),
                record.action,
                environment,
                record.expires_at,
                record.used_at,
                record.created_at,
            ),
        )

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return self._fetchone("SELECT * FROM approvals WHERE approval_id = %s", (approval_id,))

    def consume_approval(self, approval_id: str) -> None:
        self._execute(
            "UPDATE approvals SET used_at = %s WHERE approval_id = %s AND used_at IS NULL",
            (utc_now(), approval_id),
        )

    def has_approval(
        self,
        run_id: str,
        scope: str,
        *,
        action: str = "execute",
        environment: str | None = None,
    ) -> bool:
        params: list[Any] = [run_id, scope, action, utc_now()]
        sql = (
            "SELECT 1 FROM approvals "
            "WHERE run_id = %s AND scope = %s AND action = %s "
            "AND approved = 1 AND used_at IS NULL "
            "AND (expires_at IS NULL OR expires_at > %s)"
        )
        if environment is not None:
            sql += " AND (environment IS NULL OR environment = %s)"
            params.append(environment)
        sql += " ORDER BY created_at DESC LIMIT 1"
        return self._fetchone(sql, tuple(params)) is not None

    def save_execution_evidence(self, record: ExecutionEvidenceRecord) -> None:
        self._execute(
            """
            INSERT INTO execution_evidence (evidence_id, run_id, tool, operation, result_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (evidence_id) DO UPDATE
            SET run_id = EXCLUDED.run_id,
                tool = EXCLUDED.tool,
                operation = EXCLUDED.operation,
                result_json = EXCLUDED.result_json,
                created_at = EXCLUDED.created_at
            """,
            (
                record.evidence_id,
                record.run_id,
                record.tool,
                record.operation,
                json.dumps(record.result),
                record.created_at,
            ),
        )

    def list_records(self, table: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        allowed = {
            "projects",
            "migration_plans",
            "runs",
            "run_steps",
            "generated_artifacts",
            "verification_reports",
            "approvals",
            "execution_evidence",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        if run_id is not None and table not in {"projects", "migration_plans"}:
            return self._fetchall(f"SELECT * FROM {table} WHERE run_id = %s", (run_id,))
        return self._fetchall(f"SELECT * FROM {table}")
