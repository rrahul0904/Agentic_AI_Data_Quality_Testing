from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentic_data_platform.models import ApprovalRecord, ExecutionEvidenceRecord, GeneratedArtifactRecord, MigrationPlanRecord, ProjectRecord, RunRecord, RunState, RunStepRecord, VerificationReport, utc_now
from agentic_data_platform.persistence.repositories import ControlPlaneRepository

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS environments (environment_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS connections (connection_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, environment_id TEXT NOT NULL, platform TEXT NOT NULL, name TEXT NOT NULL, credential_ref TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dataset_objects (object_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, connection_id TEXT NOT NULL, object_type TEXT NOT NULL, qualified_name TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipelines (pipeline_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, definition_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS migration_plans (migration_plan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, spec_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, environment_id TEXT NOT NULL, intent TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_steps (run_step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL, sequence INTEGER NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS generated_artifacts (artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, dialect TEXT, version INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verification_reports (report_id TEXT PRIMARY KEY, run_id TEXT, findings_json TEXT NOT NULL, passed INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, approved_by TEXT NOT NULL, scope TEXT NOT NULL, approved INTEGER NOT NULL, action TEXT NOT NULL DEFAULT 'execute', environment TEXT, expires_at TEXT, used_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS execution_evidence (evidence_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tool TEXT NOT NULL, operation TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_approvals_run_scope ON approvals(run_id, scope, approved);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON execution_evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_steps_run ON run_steps(run_id, sequence);
"""

class SQLiteControlPlaneRepository(ControlPlaneRepository):
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection: sqlite3.Connection | None = None

    def _conn(self) -> sqlite3.Connection:
        if self._connection is None:
            # FastAPI routes run in worker threads; SQLite still remains a test/local fallback.
            self._connection = sqlite3.connect(self.path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def initialize(self) -> None:
        self._conn().executescript(_SCHEMA)
        # Existing Wave 1 databases are upgraded in place without an external migration tool.
        existing = {row["name"] for row in self._conn().execute("PRAGMA table_info(approvals)")}
        for name, definition in {
            "action": "TEXT NOT NULL DEFAULT 'execute'",
            "environment": "TEXT",
            "expires_at": "TEXT",
            "used_at": "TEXT",
        }.items():
            if name not in existing:
                self._conn().execute(f"ALTER TABLE approvals ADD COLUMN {name} {definition}")
        self._conn().commit()

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self._conn().execute(sql, params)
        self._conn().commit()

    def save_project(self, record: ProjectRecord) -> None:
        self._execute("INSERT OR REPLACE INTO projects VALUES (?, ?, ?)", (record.project_id, record.name, record.created_at))

    def save_run(self, record: RunRecord) -> None:
        self._execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)", (record.run_id, record.project_id, record.environment_id, record.intent, record.state.value, record.created_at))

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._conn().execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return RunRecord(project_id=row["project_id"], environment_id=row["environment_id"], intent=row["intent"], state=RunState(row["state"]), run_id=row["run_id"], created_at=row["created_at"])

    def save_run_step(self, record: RunStepRecord) -> None:
        self._execute("INSERT OR REPLACE INTO run_steps VALUES (?, ?, ?, ?, ?, ?, ?)", (record.run_step_id, record.run_id, record.name, record.state, record.sequence, json.dumps(record.detail), record.created_at))

    def save_artifact(self, record: GeneratedArtifactRecord) -> None:
        self._execute("INSERT OR REPLACE INTO generated_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)", (record.artifact_id, record.run_id, record.kind, record.content, record.dialect, record.version, record.created_at))

    def save_migration_plan(self, record: MigrationPlanRecord) -> None:
        self._execute("INSERT OR REPLACE INTO migration_plans VALUES (?, ?, ?, ?, ?)", (record.migration_plan_id, record.project_id, json.dumps(record.spec), record.status, record.created_at))

    def save_verification_report(self, report: VerificationReport) -> None:
        findings = [asdict(item) for item in report.findings]
        self._execute("INSERT OR REPLACE INTO verification_reports VALUES (?, ?, ?, ?, ?)", (report.report_id, report.run_id, json.dumps(findings), int(report.passed), report.created_at))

    def save_approval(self, record: ApprovalRecord) -> None:
        environment = record.environment.value if record.environment else None
        self._execute(
            "INSERT OR REPLACE INTO approvals (approval_id, run_id, approved_by, scope, approved, action, environment, expires_at, used_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.approval_id, record.run_id, record.approved_by, record.scope, int(record.approved), record.action, environment, record.expires_at, record.used_at, record.created_at),
        )

    def has_approval(self, run_id: str, scope: str, *, action: str = "execute", environment: str | None = None) -> bool:
        params: list[Any] = [run_id, scope, action, utc_now()]
        sql = "SELECT 1 FROM approvals WHERE run_id = ? AND scope = ? AND action = ? AND approved = 1 AND (expires_at IS NULL OR expires_at > ?)"
        if environment is not None:
            sql += " AND (environment IS NULL OR environment = ?)"
            params.append(environment)
        sql += " ORDER BY created_at DESC LIMIT 1"
        row = self._conn().execute(sql, tuple(params)).fetchone()
        return row is not None

    def save_execution_evidence(self, record: ExecutionEvidenceRecord) -> None:
        self._execute("INSERT OR REPLACE INTO execution_evidence VALUES (?, ?, ?, ?, ?, ?)", (record.evidence_id, record.run_id, record.tool, record.operation, json.dumps(record.result), record.created_at))

    def list_records(self, table: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        allowed = {"projects", "migration_plans", "runs", "run_steps", "generated_artifacts", "verification_reports", "approvals", "execution_evidence"}
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        if run_id is not None and table not in {"projects", "migration_plans"}:
            rows = self._conn().execute(f"SELECT * FROM {table} WHERE run_id = ?", (run_id,)).fetchall()
        else:
            rows = self._conn().execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]
