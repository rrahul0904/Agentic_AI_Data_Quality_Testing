from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class Platform(str, Enum):
    SQLSERVER = "sqlserver"
    SNOWFLAKE = "snowflake"
    DATABRICKS = "databricks"
    BIGQUERY = "bigquery"
    DBT = "dbt"
    SPARK = "spark"
    LOCAL = "local"
    POSTGRES = "postgres"
    ORACLE = "oracle"
    DUCKDB = "duckdb"
    REDSHIFT = "redshift"
    MYSQL = "mysql"
    SQLITE = "sqlite"
    CLICKHOUSE = "clickhouse"
    TRINO = "trino"
    MONGODB = "mongodb"


class Risk(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class ActorMode(str, Enum):
    """Operator boundary used by every deterministic tool invocation."""

    ANALYST = "analyst"
    PLAN = "plan"
    BUILDER = "builder"
    ADMIN = "admin"


class Capability(str, Enum):
    DISCOVER = "discover"
    PLAN = "plan"
    GENERATE = "generate"
    VERIFY = "verify"
    EXECUTE = "execute"
    MIGRATE = "migrate"
    DBT = "dbt"


class RunState(str, Enum):
    CREATED = "created"
    DISCOVERING = "discovering"
    PLANNING = "planning"
    GENERATING = "generating"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    REPAIRING = "repairing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    operation: str
    environment: Environment
    risk: Risk
    args: dict[str, Any] = field(default_factory=dict)
    platform: Platform | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool = False
    reason: str = ""


@dataclass(frozen=True)
class VerificationFinding:
    check: str
    passed: bool
    severity: str = "error"
    detail: str = ""
    blocking: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationReport:
    findings: list[VerificationFinding] = field(default_factory=list)
    report_id: str = field(default_factory=lambda: new_id("vr"))
    run_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    @property
    def passed(self) -> bool:
        return all(item.passed or item.severity != "error" or not item.blocking for item in self.findings)

    def add(self, finding: VerificationFinding) -> None:
        self.findings.append(finding)


@dataclass(frozen=True)
class ProjectRecord:
    name: str
    project_id: str = field(default_factory=lambda: new_id("prj"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class EnvironmentRecord:
    project_id: str
    name: str
    kind: Environment
    environment_id: str = field(default_factory=lambda: new_id("env"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ConnectionRecord:
    project_id: str
    environment_id: str
    platform: Platform
    name: str
    credential_ref: str | None = None
    connection_id: str = field(default_factory=lambda: new_id("conn"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class DatasetObjectRecord:
    project_id: str
    connection_id: str
    object_type: str
    qualified_name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    object_id: str = field(default_factory=lambda: new_id("obj"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class PipelineRecord:
    project_id: str
    name: str
    definition: dict[str, Any] = field(default_factory=dict)
    pipeline_id: str = field(default_factory=lambda: new_id("pipe"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class MigrationPlanRecord:
    project_id: str
    spec: dict[str, Any]
    status: str = "draft"
    migration_plan_id: str = field(default_factory=lambda: new_id("mig"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class RunRecord:
    project_id: str
    environment_id: str
    intent: str
    state: RunState = RunState.CREATED
    run_id: str = field(default_factory=lambda: new_id("run"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class RunStepRecord:
    run_id: str
    name: str
    state: str
    sequence: int
    detail: dict[str, Any] = field(default_factory=dict)
    run_step_id: str = field(default_factory=lambda: new_id("step"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class GeneratedArtifactRecord:
    run_id: str
    kind: str
    content: str
    dialect: str | None = None
    version: int = 1
    artifact_id: str = field(default_factory=lambda: new_id("art"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ApprovalRecord:
    run_id: str
    approved_by: str
    scope: str
    approved: bool = True
    action: str = "execute"
    environment: Environment | None = None
    expires_at: str | None = None
    used_at: str | None = None
    approval_id: str = field(default_factory=lambda: new_id("apr"))
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ExecutionEvidenceRecord:
    run_id: str
    tool: str
    operation: str
    result: dict[str, Any]
    evidence_id: str = field(default_factory=lambda: new_id("ev"))
    created_at: str = field(default_factory=utc_now)
