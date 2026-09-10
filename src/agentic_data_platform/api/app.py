from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agentic_data_platform.agents.planner import PlannerAgent
from agentic_data_platform.errors import safe_error
from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.models import ActorMode, ApprovalRecord, Environment, ProjectRecord, RunRecord, ToolRequest
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository
from agentic_data_platform.sql.parser import parse_sql
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RunInput(BaseModel):
    project_id: str
    environment_id: str
    intent: str


class ApprovalInput(BaseModel):
    run_id: str
    approved_by: str
    scope: str
    action: str = "execute"
    environment: Environment | None = None
    expires_at: str | None = None


class VerifyInput(BaseModel):
    sql: str
    dialect: str | None = None


class MigrationPlanInput(BaseModel):
    intent: str
    source: str
    target: str
    objects: list[str] = []


class ToolInput(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    actor_mode: ActorMode = ActorMode.ANALYST
    environment: Environment = Environment.DEV
    dry_run: bool = False
    approved: bool = False


class SqlWorkspaceInput(BaseModel):
    sql: str = Field(min_length=1)
    dialect: str | None = "snowflake"


class ReconcileRowCountInput(BaseModel):
    source_value: int
    target_value: int
    absolute_tolerance: float = Field(default=0, ge=0)
    percentage_tolerance: float = Field(default=0, ge=0)


class AgentQueryInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class InvestigationApprovalInput(BaseModel):
    approved_by: str = Field(min_length=1, max_length=200)


class InvestigationRejectInput(BaseModel):
    rejected_by: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="operator rejected remediation", min_length=1, max_length=1000)


class ProactiveAnomalyInput(BaseModel):
    signals: dict[str, Any]
    scenario_id: str = Field(default="airflow_green_data_bad", min_length=1, max_length=200)


class ArgsInput(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


class SessionCreateInput(BaseModel):
    title: str | None = None
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionMessageInput(BaseModel):
    role: str
    content: Any
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionTodoInput(BaseModel):
    text: str = Field(min_length=1)
    priority: int = 0


class SessionTodoUpdateInput(BaseModel):
    status: str
    progress: float | None = None
    evidence: list[Any] = Field(default_factory=list)
    verified: bool | None = None


class MemorySaveInput(BaseModel):
    content: str = Field(min_length=1)
    scope: str = "project"
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    expires_at: str | None = None


class TrainingTextInput(BaseModel):
    source: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_type: str = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillCreateInput(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    body: str = Field(min_length=1)
    scope: str = "project"
    always_apply: bool = False
    apply_paths: list[str] = Field(default_factory=list)


class SkillInstallInput(BaseModel):
    name: str | None = None
    source: str | None = None
    scope: str = "project"
    overwrite: bool = False


class JobSubmitInput(BaseModel):
    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


def _record_payload(record: Any) -> dict[str, Any]:
    value = asdict(record)
    for key, item in list(value.items()):
        if hasattr(item, "value"):
            value[key] = item.value
    return value


def _program_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _project_root() -> Path:
    configured = os.getenv("ADE_DEMO_PROJECT")
    return Path(configured).expanduser().resolve() if configured else _program_root() / "hospitality-snowflake-data-platform"


def _quality_database() -> Path:
    configured = os.getenv("ADE_QUALITY_DATABASE")
    return Path(configured).expanduser().resolve() if configured else _program_root() / ".ade" / "quality.db"


def _investigation_database() -> Path:
    configured = os.getenv("ADE_INVESTIGATION_DATABASE")
    return Path(configured).expanduser().resolve() if configured else _program_root() / ".ade" / "agentic-investigations.db"


def _shiftforge_fixture() -> Path:
    return _program_root() / "shiftforge" / "examples" / "revinate"


def create_app(repository: SQLiteControlPlaneRepository | None = None) -> FastAPI:
    repo = repository or SQLiteControlPlaneRepository(os.getenv("ADE_DATABASE_PATH", "ade.db"))
    repo.initialize()
    registry = build_tool_registry()
    investigation_store = InvestigationStore(_investigation_database())
    supervisor = SupervisorAgent(registry, investigation_store, _project_root())
    app = FastAPI(title="Agentic Data Engineering OS", version="0.5.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("ADE_UI_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["content-type"],
    )

    def invoke_governed(
        tool_name: str,
        args: dict[str, Any] | None = None,
        *,
        actor_mode: ActorMode = ActorMode.ANALYST,
        environment: Environment = Environment.DEV,
        dry_run: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        definition = registry.describe(tool_name)
        request = ToolRequest(
            tool=tool_name,
            operation=tool_name,
            environment=environment,
            risk=definition.risk,
            args=args or {},
        )
        try:
            return registry.invoke(
                ToolInvocation(
                    request,
                    run_id=f"api-v1-{tool_name}",
                    approved=approved,
                    dry_run=dry_run,
                    actor_mode=actor_mode,
                )
            )
        except PermissionError as exc:
            raise HTTPException(403, safe_error(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, safe_error(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, safe_error(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, safe_error(exc)) from exc

    def invoke_read(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return invoke_governed(tool_name, args, actor_mode=ActorMode.ANALYST)

    def demo_project_args() -> dict[str, Any]:
        return {"project": str(_project_root())}

    def quality_args(**extra: Any) -> dict[str, Any]:
        return {"database": str(_quality_database()), **extra}

    def migration_args() -> dict[str, Any]:
        return {"project": str(_shiftforge_fixture())}

    @app.get("/api/v1/overview")
    def operator_overview() -> dict[str, Any]:
        inventory = invoke_read("platform_inventory", demo_project_args())
        health = invoke_read("platform_health", demo_project_args())
        dbt_coverage = invoke_read("dbt_test_coverage", demo_project_args())
        quality = invoke_read("quality_summary", quality_args())
        migration = invoke_read("migration_show_blockers", migration_args())
        tools = registry.definitions()

        checks = health["checks"]
        penalties = {"FAIL": 20, "WARN": 7, "SKIP": 2}
        score = max(0, 100 - sum(penalties.get(item["status"], 0) for item in checks.values()))
        if quality["status_counts"].get("FAIL", 0):
            score = max(0, score - min(12, quality["status_counts"]["FAIL"] * 3))
        if migration.get("count", 0):
            score = max(0, score - min(10, migration["count"] * 2))

        findings: list[dict[str, Any]] = []
        for name, item in checks.items():
            if item["status"] in {"FAIL", "WARN", "SKIP"}:
                findings.append({
                    "severity": "critical" if item["status"] == "FAIL" else "info" if item["status"] == "SKIP" else "warning",
                    "source": "platform_health",
                    "title": name.replace("_", " "),
                    "detail": item["detail"],
                })
        for item in quality.get("recent_results", [])[:5]:
            if item["status"] != "PASS":
                findings.append({
                    "severity": "critical" if item["severity"] in {"ERROR", "CRITICAL"} else "warning",
                    "source": "quality_store",
                    "title": item["check_id"],
                    "detail": f'{item["asset"]}: {item["status"]}',
                })

        sources = inventory["sources"]
        return {
            "mode": "LOCAL_SIMULATION" if os.getenv("ADE_DEMO_MODE", "true").lower() != "false" else inventory["mode"],
            "project": inventory["hospitality_project"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "health_score": score,
            "health_status": health["status"],
            "counts": {
                "sources": sources["oracle_tables"] + sources["postgres_tables"] + sources["file_feeds"],
                "oracle_tables": sources["oracle_tables"],
                "postgres_tables": sources["postgres_tables"],
                "file_feeds": sources["file_feeds"],
                "airflow_dags": inventory["airflow"]["dag_count"],
                "dbt_models": inventory["dbt"]["models"],
                "dbt_tests": inventory["dbt"]["tests"],
                "dbt_snapshots": inventory["dbt"]["snapshots"],
                "tools": len(tools),
            },
            "dbt_coverage": dbt_coverage,
            "quality": quality,
            "migration": {"blockers": migration.get("count", 0), "engine": "ShiftForge"},
            "live_integrations": {
                "snowflake": inventory["snowflake"]["live_status"],
                "oracle": "SKIPPED - local Oracle simulation active",
            },
            "findings": findings[:10],
            "health_components": checks,
        }

    @app.get("/api/v1/platform/inventory")
    def platform_inventory() -> dict[str, Any]:
        return invoke_read("platform_inventory", demo_project_args())

    @app.get("/api/v1/platform/health")
    def platform_health() -> dict[str, Any]:
        return invoke_read("platform_health", demo_project_args())

    @app.get("/api/v1/assets")
    def assets(query: str = "", kind: str | None = None, limit: int = 250) -> dict[str, Any]:
        graph = invoke_read("platform_graph", demo_project_args())
        needle = query.casefold().strip()
        items = []
        for item in graph["nodes"]:
            if kind and item["kind"] != kind:
                continue
            if needle and needle not in item["name"].casefold() and needle not in item["kind"].casefold():
                continue
            items.append(item)
        bounded = max(1, min(limit, 1000))
        return {
            "total": len(items),
            "returned": min(len(items), bounded),
            "node_types": graph["node_types"],
            "edge_types": graph["edge_types"],
            "items": items[:bounded],
        }

    @app.get("/api/v1/lineage/{node}")
    def platform_lineage(node: str, depth: int = 6) -> dict[str, Any]:
        return invoke_read("platform_lineage", {**demo_project_args(), "node": node, "depth": depth})

    @app.get("/api/v1/impact/{node}")
    def platform_impact(node: str, depth: int = 8) -> dict[str, Any]:
        return invoke_read("platform_impact", {**demo_project_args(), "node": node, "depth": depth})

    @app.get("/api/v1/agents/roster")
    def agent_roster() -> dict[str, Any]:
        items = supervisor.roster()
        return {"status": "PASS", "count": len(items), "agents": items}

    @app.get("/api/v1/investigations/scenarios")
    def investigation_scenarios() -> dict[str, Any]:
        items = supervisor.scenarios()
        return {"status": "PASS", "count": len(items), "scenarios": items}

    @app.post("/api/v1/investigations/anomaly")
    def proactive_anomaly(payload: ProactiveAnomalyInput) -> dict[str, Any]:
        try:
            return supervisor.detect_and_investigate(
                payload.signals,
                scenario_id=payload.scenario_id,
            )
        except KeyError as exc:
            raise HTTPException(404, safe_error(exc)) from exc

    @app.get("/api/v1/investigations")
    def investigation_list(limit: int = 100) -> dict[str, Any]:
        items = investigation_store.list_incidents(limit)
        return {"status": "PASS", "count": len(items), "incidents": items}

    @app.post("/api/v1/investigations/{scenario_id}/start")
    def investigation_start(scenario_id: str) -> dict[str, Any]:
        try:
            report = supervisor.investigate(scenario_id)
            return supervisor.public_report(report.incident_id)
        except KeyError as exc:
            raise HTTPException(404, safe_error(exc)) from exc

    @app.get("/api/v1/investigations/{incident_id}")
    def investigation_detail(incident_id: str) -> dict[str, Any]:
        try:
            return supervisor.public_report(incident_id)
        except KeyError as exc:
            raise HTTPException(404, safe_error(exc)) from exc

    @app.post("/api/v1/investigations/{incident_id}/approve")
    def investigation_approve(incident_id: str, payload: InvestigationApprovalInput) -> dict[str, Any]:
        try:
            return supervisor.approve(incident_id, approved_by=payload.approved_by)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, safe_error(exc)) from exc

    @app.post("/api/v1/investigations/{incident_id}/execute")
    def investigation_execute(incident_id: str) -> dict[str, Any]:
        try:
            report = supervisor.execute_approved(incident_id)
            return supervisor.public_report(report.incident_id)
        except PermissionError as exc:
            raise HTTPException(403, safe_error(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, safe_error(exc)) from exc

    @app.post("/api/v1/investigations/{incident_id}/reject")
    def investigation_reject(incident_id: str, payload: InvestigationRejectInput) -> dict[str, Any]:
        try:
            return supervisor.reject(incident_id, rejected_by=payload.rejected_by, reason=payload.reason)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, safe_error(exc)) from exc

    @app.post("/api/v1/sql/review")
    def sql_review(payload: SqlWorkspaceInput) -> dict[str, Any]:
        return invoke_read("sql_review", {"sql": payload.sql, "dialect": payload.dialect})

    @app.post("/api/v1/sql/lineage")
    def sql_workspace_lineage(payload: SqlWorkspaceInput) -> dict[str, Any]:
        return invoke_read("sql_column_lineage", {"sql": payload.sql, "dialect": payload.dialect})

    @app.get("/api/v1/dbt/summary")
    def dbt_summary() -> dict[str, Any]:
        return invoke_read("dbt_manifest_summary", demo_project_args())

    @app.get("/api/v1/dbt/coverage")
    def dbt_coverage() -> dict[str, Any]:
        return invoke_read("dbt_test_coverage", demo_project_args())

    @app.get("/api/v1/dbt/documentation-gaps")
    def dbt_documentation_gaps() -> dict[str, Any]:
        return invoke_read("dbt_documentation_gaps", demo_project_args())

    @app.get("/api/v1/dbt/lineage/{node}")
    def dbt_lineage(node: str, depth: int = 6) -> dict[str, Any]:
        return invoke_read("dbt_lineage", {**demo_project_args(), "node": node, "depth": depth})

    @app.get("/api/v1/dbt/impact/{node}")
    def dbt_impact(node: str, depth: int = 8) -> dict[str, Any]:
        return invoke_read("dbt_impact", {**demo_project_args(), "node": node, "depth": depth})

    @app.get("/api/v1/airflow/inventory")
    def airflow_inventory() -> dict[str, Any]:
        summary = invoke_read("airflow_inventory", demo_project_args())
        details = [
            invoke_read("airflow_dag_details", {**demo_project_args(), "dag_id": dag_id})
            for dag_id in summary["dags"]
        ]
        return {**summary, "details": details}

    @app.get("/api/v1/airflow/health")
    def airflow_health() -> dict[str, Any]:
        return invoke_read("airflow_health", demo_project_args())

    @app.get("/api/v1/airflow/failures")
    def airflow_failures() -> dict[str, Any]:
        return invoke_read("airflow_failure_summary", demo_project_args())

    @app.get("/api/v1/airflow/static-analysis")
    def airflow_static_analysis() -> dict[str, Any]:
        return invoke_read("airflow_static_dag_intelligence", demo_project_args())

    @app.get("/api/v1/airflow/dags")
    def airflow_dags() -> dict[str, Any]:
        return invoke_read("airflow_inventory", demo_project_args())

    @app.get("/api/v1/airflow/dags/{dag_id}")
    def airflow_dag(dag_id: str) -> dict[str, Any]:
        return invoke_read("airflow_dag_details", {**demo_project_args(), "dag_id": dag_id})

    @app.get("/api/v1/airflow/dags/{dag_id}/tasks")
    def airflow_dag_tasks(dag_id: str) -> dict[str, Any]:
        return invoke_read("airflow_task_graph", {**demo_project_args(), "dag_id": dag_id})

    @app.get("/api/v1/airflow/dags/{dag_id}/runs")
    def airflow_dag_runs(dag_id: str, limit: int = 100) -> dict[str, Any]:
        return invoke_read("airflow_runtime_dag_runs", {**demo_project_args(), "dag_id": dag_id, "limit": limit})

    @app.get("/api/v1/airflow/tasks/{task_id}")
    def airflow_task(task_id: str) -> dict[str, Any]:
        graph = invoke_read("airflow_graph", demo_project_args())
        matches = [node for node in graph["nodes"] if node.get("kind") == "task" and node.get("name") == task_id]
        if not matches:
            raise HTTPException(404, f"Airflow task not found: {task_id}")
        return {"task_id": task_id, "matches": matches}

    @app.get("/api/v1/airflow/assets")
    def airflow_assets() -> dict[str, Any]:
        return invoke_read("airflow_asset_inventory", demo_project_args())

    @app.get("/api/v1/airflow/assets/{asset:path}")
    def airflow_asset(asset: str) -> dict[str, Any]:
        result = invoke_read("airflow_asset_inventory", demo_project_args())
        matches = [item for item in result["items"] if item["name"] == asset]
        if not matches:
            raise HTTPException(404, f"Airflow asset not found: {asset}")
        return matches[0]

    @app.get("/api/v1/airflow/connections")
    def airflow_connections() -> dict[str, Any]:
        return invoke_read("airflow_connection_analysis", demo_project_args())

    @app.get("/api/v1/airflow/pools")
    def airflow_pools() -> dict[str, Any]:
        return invoke_read("airflow_pool_health", demo_project_args())

    @app.get("/api/v1/airflow/import-errors")
    def airflow_import_errors() -> dict[str, Any]:
        return invoke_read("airflow_import_errors", demo_project_args())

    @app.post("/api/v1/airflow/root-cause")
    def airflow_root_cause(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read("airflow_pipeline_root_cause", {**demo_project_args(), **payload.args})

    @app.post("/api/v1/airflow/backfill/plan")
    def airflow_backfill_plan(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read("airflow_backfill_plan", {**demo_project_args(), **payload.args})

    @app.get("/api/v1/airflow/capacity")
    def airflow_capacity() -> dict[str, Any]:
        return invoke_read("airflow_capacity_plan", demo_project_args())

    @app.get("/api/v1/airflow/upgrade")
    def airflow_upgrade() -> dict[str, Any]:
        return invoke_read("airflow_upgrade_analysis", demo_project_args())

    @app.get("/api/v1/airflow/security")
    def airflow_security() -> dict[str, Any]:
        return invoke_read("airflow_secret_risk", demo_project_args())

    @app.get("/api/v1/airflow/xcom")
    def airflow_xcom() -> dict[str, Any]:
        return invoke_read("airflow_xcom_analysis", demo_project_args())

    @app.get("/api/v1/airflow/bundles")
    def airflow_bundles() -> dict[str, Any]:
        return invoke_read("airflow_bundle_inventory", demo_project_args())

    @app.get("/api/v1/quality/summary")
    def quality_summary() -> dict[str, Any]:
        return invoke_read("quality_summary", quality_args())

    @app.get("/api/v1/quality/recent")
    def quality_recent(limit: int = 50) -> dict[str, Any]:
        return invoke_read("quality_recent", quality_args(limit=limit))

    @app.get("/api/v1/reconciliation/history")
    def reconciliation_history(limit: int = 50) -> dict[str, Any]:
        return invoke_read("reconciliation_history", quality_args(limit=limit))

    @app.post("/api/v1/reconciliation/row-count")
    def reconciliation_row_count(payload: ReconcileRowCountInput) -> dict[str, Any]:
        return invoke_read("reconcile_row_count", payload.model_dump())

    @app.get("/api/v1/migration/inventory")
    def migration_inventory() -> dict[str, Any]:
        return invoke_read("migration_inventory", migration_args())

    @app.get("/api/v1/migration/findings")
    def migration_findings() -> dict[str, Any]:
        return invoke_read("migration_show_findings", migration_args())

    @app.get("/api/v1/migration/blockers")
    def migration_blockers() -> dict[str, Any]:
        return invoke_read("migration_show_blockers", migration_args())

    @app.get("/api/v1/warehouses")
    def warehouses() -> dict[str, Any]:
        return invoke_read("warehouse_status", {})

    @app.get("/api/v1/data-diff/demo")
    def data_diff_demo() -> dict[str, Any]:
        return invoke_read("data_diff_duckdb_demo", {})

    @app.get("/api/v1/dbt/advanced")
    def dbt_advanced() -> dict[str, Any]:
        args = demo_project_args()
        return {
            "incremental": invoke_read("dbt_incremental_analysis", args),
            "snapshots": invoke_read("dbt_snapshot_analysis", args),
            "macros": invoke_read("dbt_macro_analysis", args),
            "failed_models": invoke_read("dbt_failed_models", args),
            "source_freshness": invoke_read("dbt_source_freshness", args),
            "leaf_candidates": invoke_read("dbt_leaf_candidates", args),
            "compiled_sql_review": invoke_read("dbt_compiled_sql_review", {**args, "limit": 25}),
        }

    @app.get("/api/v1/airflow/operations")
    def airflow_operations() -> dict[str, Any]:
        args = demo_project_args()
        return {
            "retry": invoke_read("airflow_retry_analysis", args),
            "schedule": invoke_read("airflow_schedule_analysis", args),
            "backfill": invoke_read("airflow_backfill_analysis", args),
            "connections": invoke_read("airflow_connection_analysis", args),
            "health": invoke_read("airflow_pipeline_health", args),
            "runtime": invoke_read("airflow_runtime_readiness", args),
        }

    @app.get("/api/v1/airflow/failure-lab")
    def airflow_failure_lab() -> dict[str, Any]:
        return invoke_read("airflow_failure_lab", {})

    @app.get("/api/v1/root-cause/{asset}")
    def root_cause(asset: str) -> dict[str, Any]:
        return invoke_read("platform_root_cause", {
            **demo_project_args(),
            "database": str(_quality_database()),
            "asset": asset,
        })

    @app.get("/api/v1/health/pipeline")
    def pipeline_health_score() -> dict[str, Any]:
        return invoke_read("pipeline_health_score", {
            **demo_project_args(),
            "database": str(_quality_database()),
        })

    @app.post("/api/v1/remediation/sql")
    def remediation_sql(payload: SqlWorkspaceInput) -> dict[str, Any]:
        return invoke_read("propose_sql_repair", {"sql": payload.sql, "dialect": payload.dialect})

    @app.get("/api/v1/remediation/dbt-tests")
    def remediation_dbt_tests(limit: int = 25) -> dict[str, Any]:
        return invoke_read("propose_dbt_tests", {**demo_project_args(), "limit": limit})

    @app.post("/api/v1/agent/query")
    def agent_query(payload: AgentQueryInput) -> dict[str, Any]:
        question = payload.question.strip()
        lowered = question.casefold()
        tools_used: list[str] = []
        result: Any
        data_sources: list[str] = []

        def use(name: str, args: dict[str, Any]) -> dict[str, Any]:
            tools_used.append(name)
            return invoke_read(name, args)

        if "migration" in lowered and "blocker" in lowered:
            result = use("migration_show_blockers", migration_args())
            data_sources = ["ShiftForge conversion report"]
        elif "no tests" in lowered or "without tests" in lowered:
            result = use("dbt_test_coverage", demo_project_args())
            data_sources = ["dbt manifest.json"]
        elif "which dag" in lowered or ("dag" in lowered and "load" in lowered):
            inventory = use("airflow_inventory", demo_project_args())
            term = "reservation" if "reservation" in lowered else ""
            result = {
                "matches": [dag for dag in inventory["dags"] if term in dag.casefold()] if term else inventory["dags"],
                "count": len([dag for dag in inventory["dags"] if term in dag.casefold()]) if term else inventory["dag_count"],
            }
            data_sources = ["Airflow DAG source AST"]
        elif "reconciliation" in lowered:
            result = use("reconciliation_history", quality_args(limit=12))
            data_sources = ["SQLite quality evidence"]
        elif "depends on" in lowered:
            reference = question[lowered.index("depends on") + len("depends on"):].strip(" ?.")
            result = use("platform_impact", {**demo_project_args(), "node": reference, "depth": 8})
            data_sources = ["cross-system asset graph", "dbt manifest", "Airflow metadata"]
        elif "lineage" in lowered:
            marker = lowered.find(" for ")
            reference = question[marker + 5:].strip(" ?.") if marker >= 0 else "fact_reservation"
            result = use("platform_lineage", {**demo_project_args(), "node": reference, "depth": 8})
            data_sources = ["cross-system asset graph", "dbt manifest", "Airflow metadata"]
        elif "unhealthy" in lowered or "health" in lowered:
            asset = "fact_reservation" if "reservation" in lowered else None
            result = use("platform_root_cause", {
                **demo_project_args(),
                "database": str(_quality_database()),
                "asset": asset,
            })
            data_sources = ["platform health", "Airflow static evidence", "dbt run_results.json", "SQLite quality evidence"]
        else:
            result = {
                "supported_questions": [
                    "Why is fact_reservation unhealthy?",
                    "What depends on stg_oracle_reservation?",
                    "Show lineage for fact_reservation.",
                    "Which DAG loads reservations?",
                    "Why did reconciliation fail?",
                    "What dbt models have no tests?",
                    "Show migration blockers.",
                ]
            }

        return {
            "question": question,
            "result": result,
            "evidence": {
                "tools_used": tools_used,
                "data_sources": data_sources,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "DETERMINISTIC_TOOL_ROUTER",
            },
        }

    DOMAIN_TOOLS: dict[str, dict[str, str]] = {
        "connections": {
            "add": "connection_add", "remove": "connection_remove", "list": "connection_list",
            "show": "connection_show", "test": "connection_test", "default": "connection_default",
            "discover": "connection_discover",
        },
        "metadata": {
            "refresh": "schema_refresh", "index": "schema_index", "search": "schema_search",
            "inspect": "schema_inspect", "tags": "schema_tags", "status": "metadata_status",
            "autocomplete": "autocomplete",
        },
        "search": {
            "index-project": "semantic_index_project",
            "index-metadata": "semantic_index_metadata",
            "query": "semantic_search",
        },
        "semantic": {
            "ingest-yaml": "semantic_ingest_yaml", "ingest-dbt": "semantic_ingest_dbt", "ingest-lookml": "semantic_ingest_lookml", "list": "semantic_list", "show": "semantic_show",
            "search": "semantic_registry_search", "verified-search": "semantic_verified_search",
            "evaluate": "semantic_evaluate", "evaluate-batch": "semantic_evaluate_batch",
            "snowflake-sync": "semantic_snowflake_sync",
            "analyst-plan": "cortex_analyst_plan", "analyst-run": "cortex_analyst_run",
        },
        "cortex-agent": {
            "create-plan": "cortex_agent_create_plan", "create": "cortex_agent_create",
            "list": "cortex_agent_list", "show": "cortex_agent_show",
            "update": "cortex_agent_update", "delete": "cortex_agent_delete",
            "run-plan": "cortex_agent_run_plan", "run": "cortex_agent_run",
            "feedback": "cortex_agent_feedback",
            "thread-create": "cortex_thread_create", "thread-list": "cortex_thread_list",
            "thread-show": "cortex_thread_show", "thread-update": "cortex_thread_update",
            "thread-delete": "cortex_thread_delete",
        },
        "teams": {
            "list": "team_list", "show": "team_show", "create": "team_create",
            "edit": "team_edit", "members": "team_set_members", "delete": "team_delete",
            "plan": "team_plan", "run": "team_run", "runs": "team_runs",
            "run-show": "team_run_show",
        },
        "runner": {
            "submit": "hosted_runner_submit", "jobs": "hosted_runner_jobs", "job": "hosted_runner_job",
            "workspace-readiness": "hosted_runner_workspace_readiness",
            "cancel": "hosted_runner_cancel", "register": "hosted_runner_register",
            "runners": "hosted_runner_runners", "heartbeat": "hosted_runner_heartbeat",
            "run-once": "hosted_runner_run_once",
        },
        "notebook": {
            "inspect": "notebook_inspect", "create-plan": "notebook_create_plan",
            "create-apply": "notebook_create_apply", "local-run": "notebook_local_run",
            "patch-plan": "notebook_patch_plan", "patch-apply": "notebook_patch_apply",
            "snowflake-plan": "notebook_snowflake_plan", "snowflake-run": "notebook_snowflake_run",
        },
        "browser": {
            "plan": "browser_plan", "read": "browser_read", "act": "browser_act",
        },
        "app": {
            "plan": "app_build_plan", "validate": "app_build_validate",
            "apply": "app_build_apply", "deploy": "app_deploy",
            "generic-scaffold-plan": "generic_app_scaffold_plan",
            "generic-scaffold-apply": "generic_app_scaffold_apply",
            "generic-validate": "generic_app_validate",
            "generic-preview-plan": "generic_app_preview_plan",
            "generic-preview-run": "generic_app_preview_run",
            "generic-verify-url": "generic_app_verify_url",
            "generic-deployment-plan": "generic_app_deployment_plan",
            "generic-deployment-run": "generic_app_deployment_run",
            "generic-rollback-plan": "generic_app_rollback_plan",
            "generic-rollback-run": "generic_app_rollback_run",
        },
        "ml": {
            "models": "snowpark_model_list", "versions": "snowpark_model_versions",
            "log-plan": "snowpark_model_log_plan", "workflow-plan": "snowpark_ml_workflow_plan",
            "lifecycle-plan": "snowpark_model_lifecycle_plan",
            "lifecycle-execute": "snowpark_model_lifecycle_execute",
            "agentic-plan": "agentic_ml_plan", "agentic-run": "agentic_ml_run",
            "agentic-predict": "agentic_ml_predict", "agentic-artifacts": "agentic_ml_artifacts",
        },
        "ai-workflow": {
            "plan": "ai_workflow_plan", "run": "ai_workflow_run",
        },
        "ide": {
            "workspace-plan": "ide_workspace_plan", "workspace-apply": "ide_workspace_apply",
            "context": "ide_context", "open": "ide_open",
            "edit-plan": "ide_edit_plan", "edit-apply": "ide_edit_apply",
            "server-register": "ide_server_register", "servers": "ide_server_list",
            "server-remove": "ide_server_remove",
        },
        "advanced": {
            "mode": "mode_contract",
            "model-route": "model_route",
            "plan-create": "immutable_plan",
            "plan-verify": "immutable_plan_verify",
            "edit-plan": "workspace_edit_plan",
            "edit-apply": "workspace_edit_apply",
            "region-edit-plan": "workspace_region_edit_plan",
            "region-edit-apply": "workspace_region_edit_apply",
            "code-index": "code_index",
            "code-search": "code_search",
            "semantic-code-search": "semantic_code_search",
            "python-repl-plan": "python_repl_plan",
            "python-repl-run": "python_repl_run",
            "python-repl-state": "python_repl_state",
            "python-repl-reset": "python_repl_reset",
            "file-read": "workspace_file_read",
            "file-glob": "workspace_file_glob",
            "file-find": "workspace_file_find",
            "file-grep": "workspace_file_grep",
            "file-diff": "workspace_file_diff",
            "file-plan": "workspace_file_plan",
            "file-apply": "workspace_file_apply",
            "file-undo": "workspace_file_undo",
            "shell-plan": "shell_plan",
            "shell-run": "shell_run",
            "shell-status": "shell_status",
            "shell-kill": "shell_kill",
            "sandbox-shell-plan": "sandbox_shell_plan",
            "sandbox-shell-run": "sandbox_shell_run",
            "sandbox-shell-status": "sandbox_shell_status",
            "sandbox-shell-logs": "sandbox_shell_logs",
            "sandbox-shell-kill": "sandbox_shell_kill",
            "git-status": "git_status",
            "git-diff": "git_diff",
            "git-log": "git_log",
            "git-remotes": "git_remotes",
            "git-review-evidence": "git_review_evidence",
            "git-plan": "git_change_plan",
            "git-apply": "git_change_apply",
            "web-fetch": "web_fetch_audited",
            "web-search": "web_search_audited",
            "retrieval-search": "retrieval_search",
            "context-select": "context_select",
            "context-compact": "context_compact",
            "agent-validate": "custom_agent_validate",
            "agent-save": "custom_agent_save",
            "agent-list": "custom_agent_list",
            "agent-recovery-plan": "agent_recovery_plan",
            "agent-recovery-execute": "agent_recovery_execute",
            "object-search": "warehouse_object_search",
            "sql-playground": "sql_playground",
            "chart-build": "chart_build",
            "forecast": "forecast_series",
            "anomaly": "anomaly_compare",
            "document-extract": "document_extract",
            "document-snowflake-extract-plan": "document_snowflake_extract_plan",
            "document-snowflake-parse-plan": "document_snowflake_parse_plan",
            "document-compare": "document_compare",
            "sdk-contract": "embedded_agent_sdk_contract",
            "account-admin-plan": "account_admin_plan",
            "gpu-plan": "gpu_job_plan",
            "gpu-run": "gpu_job_run",
        },
        "data-diff": {
            "run": "data_diff", "plan": "data_diff_plan", "profile": "data_diff_profile",
            "join": "data_diff_join", "hash": "data_diff_hash", "cascade": "data_diff_cascade",
        },
        "snowflake-admin": {
            "plan": "snowflake_mutation_plan",
            "execute": "snowflake_mutation_execute",
        },
        "dbt-managed": {
            "commands": "snowflake_managed_dbt_commands",
            "plan": "snowflake_managed_dbt_plan",
            "execute": "snowflake_managed_dbt_execute",
        },
        "snowflake-testing": {
            "copy-analyze": "snowflake_copy_analyze",
            "failure-lab": "snowflake_failure_lab",
            "stages": "snowflake_stage_inventory",
            "stage-files": "snowflake_stage_files",
            "file-format": "snowflake_file_format",
            "pipes": "snowflake_pipe_inventory",
            "pipe-status": "snowflake_pipe_status",
            "pipe-validate": "snowflake_pipe_validate",
            "streams": "snowflake_stream_inventory",
            "stream-status": "snowflake_stream_status",
            "stream-backlog": "snowflake_stream_backlog",
            "copy-history": "snowflake_copy_history",
            "copy-validate": "snowflake_copy_validate",
            "schema-drift": "snowflake_schema_drift",
            "latency": "snowflake_ingestion_latency",
            "quality": "snowflake_table_quality",
            "reconcile": "snowflake_reconcile_load",
            "health": "snowflake_pipeline_health",
            "rca": "snowflake_pipeline_rca",
        },
        "finops": {
            "history": "finops_query_history", "expensive": "finops_expensive_queries",
            "errors": "finops_query_errors", "patterns": "finops_query_patterns",
            "cost": "finops_cost_summary", "usage": "finops_warehouse_usage",
            "advisor": "finops_warehouse_advisor", "idle": "finops_idle_resources",
            "report": "finops_report",
        },
        "governance": {
            "pii-scan": "pii_scan", "pii-lineage": "pii_lineage",
            "pii-exposure": "pii_exposure", "pii-policy": "pii_policy_check",
            "pii-downstream": "pii_downstream_assets", "rbac-audit": "rbac_audit",
            "rbac-object-access": "rbac_object_access", "rbac-risk": "rbac_risk",
            "permission-plan": "permission_plan", "permission-execute": "permission_execute",
            "pii-access": "pii_access_report",
        },
        "providers": {
            "list": "provider_list", "auth": "provider_auth", "auth-status": "provider_auth_status",
            "family": "provider_family", "models": "provider_models",
            "search": "provider_model_search", "model-status": "provider_model_status",
            "snapshot": "provider_model_snapshot", "transform": "provider_transform",
            "output-budget": "provider_output_budget",
        },
        "mcp": {
            "list": "mcp_list", "add": "mcp_add", "remove": "mcp_remove",
            "enable": "mcp_enable", "disable": "mcp_disable", "discover": "mcp_discover",
            "catalog": "mcp_catalog", "install": "mcp_install",
            "auth-set-env": "mcp_auth_set_env", "auth-status": "mcp_auth_status",
            "status": "mcp_status", "tools": "mcp_tools", "resources": "mcp_resources",
            "call": "mcp_call", "oauth-begin": "mcp_oauth_begin",
            "oauth-callback": "mcp_oauth_callback",
        },
        "skills": {
            "catalog": "skill_catalog", "install": "skill_install",
            "install-source": "skill_install_source", "create": "skill_create",
            "test": "skill_test", "install-all": "skill_install_all",
            "list": "skill_list", "show": "skill_show", "enable": "skill_enable",
            "disable": "skill_disable", "remove": "skill_remove",
            "auto-load": "skill_auto_load", "plan": "skill_plan", "execute": "skill_execute",
        },
        "training": {
            "ingest": "training_ingest", "ingest-text": "training_ingest_text",
            "search": "training_search", "context": "training_context",
            "status": "training_status", "clear": "training_clear",
        },
        "sessions": {
            "create": "session_create", "list": "session_list", "show": "session_show",
            "message-add": "session_message_add", "messages": "session_messages",
            "history": "session_history",
            "checkpoint-create": "session_checkpoint_create",
            "checkpoint-list": "session_checkpoint_list",
            "checkpoint-show": "session_checkpoint_show",
            "checkpoint-diff": "session_checkpoint_diff",
            "checkpoint-review": "session_checkpoint_review",
            "checkpoint-delete": "session_checkpoint_delete",
            "status": "session_status", "status-set": "session_status_set",
            "todo-add": "session_todo_add", "todo-update": "session_todo_update",
            "todo-complete": "session_todo_complete", "todo-reopen": "session_todo_reopen",
            "todo-remove": "session_todo_remove", "todo-reorder": "session_todo_reorder",
            "todo-dependencies": "session_todo_dependencies", "todos-from-plan": "session_todos_from_plan",
            "todos": "session_todos", "reminder-add": "session_reminder_add",
            "reminders": "session_reminders", "reminder-deliver": "session_reminder_deliver",
            "revert": "session_revert", "state": "session_state",
            "state-patch": "session_state_patch", "prompt": "session_prompt",
            "compact": "session_compact", "nudge": "session_nudge",
            "termination": "session_termination", "retry-plan": "session_retry_plan",
            "tool-result-cap": "session_tool_result_cap", "overflow": "session_overflow",
        },
        "rules": {
            "list": "rule_list", "resolve": "rule_resolve", "show": "rule_show",
            "save": "rule_save", "enable": "rule_enable", "remove": "rule_remove",
        },
        "memory": {
            "save": "memory_save", "list": "memory_list", "search": "memory_search",
            "settings": "memory_settings", "personalization": "memory_personalization",
            "configure": "memory_configure", "update": "memory_update",
            "reset": "memory_reset", "remove": "memory_remove",
        },
        "traces": {
            "list": "trace_list", "show": "trace_show", "export": "trace_export",
            "replay": "trace_replay",
        },
        "jobs": {
            "submit": "job_submit", "list": "job_list", "show": "job_show",
            "cancel": "job_cancel",
        },
        "automations": {
            "create": "automation_create", "list": "automation_list", "show": "automation_show",
            "enable": "automation_enable", "approve": "automation_approve",
            "run-due": "automation_run_due", "delete": "automation_delete",
        },
        "plugins": {
            "validate": "plugin_bundle_validate", "install": "plugin_bundle_install",
            "list": "plugin_bundle_list", "show": "plugin_bundle_show",
            "activate": "plugin_bundle_activate", "remove": "plugin_bundle_remove",
        },
    }

    @app.get("/api/v1/domains")
    def domain_surface() -> dict[str, Any]:
        return {
            domain: {
                operation: {
                    "tool": tool_name,
                    "risk": registry.describe(tool_name).risk.value,
                    "capability": registry.describe(tool_name).capability.value,
                }
                for operation, tool_name in operations.items()
            }
            for domain, operations in DOMAIN_TOOLS.items()
        }

    # --- Phase 2 stable runtime API -------------------------------------------------

    def runtime_args(**extra: Any) -> dict[str, Any]:
        return {**demo_project_args(), **extra}

    @app.get("/api/v1/sessions")
    def session_list(limit: int = 100) -> dict[str, Any]:
        return invoke_read("session_list", runtime_args(limit=limit))

    @app.post("/api/v1/sessions")
    def session_create(payload: SessionCreateInput) -> dict[str, Any]:
        return invoke_governed(
            "session_create",
            runtime_args(
                title=payload.title,
                provider=payload.provider,
                model=payload.model,
                metadata=payload.metadata,
            ),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/sessions/{session_id}")
    def session_show(session_id: str) -> dict[str, Any]:
        return invoke_read("session_show", runtime_args(session_id=session_id))

    @app.get("/api/v1/sessions/{session_id}/messages")
    def session_messages(session_id: str, limit: int | None = None) -> dict[str, Any]:
        return invoke_read(
            "session_messages",
            runtime_args(session_id=session_id, limit=limit),
        )

    @app.post("/api/v1/sessions/{session_id}/messages")
    def session_message_add(session_id: str, payload: SessionMessageInput) -> dict[str, Any]:
        return invoke_governed(
            "session_message_add",
            runtime_args(
                session_id=session_id,
                role=payload.role,
                content=payload.content,
                error=payload.error,
                metadata=payload.metadata,
            ),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/sessions/{session_id}/history")
    def session_history(session_id: str, limit: int | None = None) -> dict[str, Any]:
        return invoke_read(
            "session_history",
            runtime_args(session_id=session_id, limit=limit),
        )

    @app.get("/api/v1/sessions/{session_id}/checkpoints")
    def session_checkpoint_list(session_id: str, limit: int = 100) -> dict[str, Any]:
        return invoke_read(
            "session_checkpoint_list",
            runtime_args(session_id=session_id, limit=limit),
        )

    @app.post("/api/v1/sessions/{session_id}/checkpoints")
    def session_checkpoint_create(session_id: str, payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "session_checkpoint_create",
            runtime_args(
                session_id=session_id,
                label=payload.args.get("label"),
                metadata=payload.args.get("metadata") or {},
            ),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/sessions/{session_id}/checkpoint-review")
    def session_checkpoint_review(session_id: str) -> dict[str, Any]:
        return invoke_read(
            "session_checkpoint_review",
            runtime_args(session_id=session_id),
        )

    @app.get("/api/v1/session-checkpoints/{checkpoint_id}")
    def session_checkpoint_show(checkpoint_id: str) -> dict[str, Any]:
        return invoke_read(
            "session_checkpoint_show",
            runtime_args(checkpoint_id=checkpoint_id),
        )

    @app.delete("/api/v1/session-checkpoints/{checkpoint_id}")
    def session_checkpoint_delete(checkpoint_id: str) -> dict[str, Any]:
        return invoke_governed(
            "session_checkpoint_delete",
            runtime_args(checkpoint_id=checkpoint_id),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/session-checkpoint-diff")
    def session_checkpoint_diff(
        from_checkpoint_id: str,
        to_checkpoint_id: str,
    ) -> dict[str, Any]:
        return invoke_read(
            "session_checkpoint_diff",
            runtime_args(
                from_checkpoint_id=from_checkpoint_id,
                to_checkpoint_id=to_checkpoint_id,
            ),
        )

    @app.get("/api/v1/sessions/{session_id}/todos")
    def session_todos(session_id: str) -> dict[str, Any]:
        return invoke_read("session_todos", runtime_args(session_id=session_id))

    @app.post("/api/v1/sessions/{session_id}/todos")
    def session_todo_add(session_id: str, payload: SessionTodoInput) -> dict[str, Any]:
        return invoke_governed(
            "session_todo_add",
            runtime_args(
                session_id=session_id,
                text=payload.text,
                priority=payload.priority,
            ),
            actor_mode=ActorMode.BUILDER,
        )

    @app.patch("/api/v1/sessions/todos/{todo_id}")
    def session_todo_update(todo_id: str, payload: SessionTodoUpdateInput) -> dict[str, Any]:
        return invoke_governed(
            "session_todo_update",
            runtime_args(
                todo_id=todo_id,
                status=payload.status,
                progress=payload.progress,
                evidence=payload.evidence,
                verified=payload.verified,
            ),
            actor_mode=ActorMode.BUILDER,
        )

    @app.post("/api/v1/sessions/{session_id}/compact")
    def session_compact(session_id: str, payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "session_compact",
            runtime_args(session_id=session_id, **payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/sessions/{session_id}/termination")
    def session_termination(session_id: str) -> dict[str, Any]:
        return invoke_read(
            "session_termination",
            runtime_args(session_id=session_id),
        )

    @app.get("/api/v1/memory")
    def memory_list(query: str = "", project_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        tool = "memory_search" if query else "memory_list"
        return invoke_read(
            tool,
            runtime_args(query=query, project_id=project_id, limit=limit),
        )

    @app.post("/api/v1/memory")
    def memory_save(payload: MemorySaveInput) -> dict[str, Any]:
        return invoke_governed(
            "memory_save",
            runtime_args(**payload.model_dump()),
            actor_mode=ActorMode.BUILDER,
        )

    @app.delete("/api/v1/memory/{memory_id}")
    def memory_remove(memory_id: str) -> dict[str, Any]:
        return invoke_governed(
            "memory_remove",
            runtime_args(memory_id=memory_id),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/training/status")
    def training_status() -> dict[str, Any]:
        return invoke_read("training_status", runtime_args())

    @app.get("/api/v1/training/search")
    def training_search(query: str, limit: int = 10) -> dict[str, Any]:
        return invoke_read(
            "training_search",
            runtime_args(query=query, limit=limit),
        )

    @app.post("/api/v1/training/ingest-text")
    def training_ingest_text(payload: TrainingTextInput) -> dict[str, Any]:
        return invoke_governed(
            "training_ingest_text",
            runtime_args(**payload.model_dump()),
            actor_mode=ActorMode.BUILDER,
        )

    @app.post("/api/v1/training/ingest-project")
    def training_ingest_project(payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "training_ingest",
            runtime_args(**payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.delete("/api/v1/training")
    def training_clear() -> dict[str, Any]:
        return invoke_governed(
            "training_clear",
            runtime_args(),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/skills/catalog")
    def skill_catalog() -> dict[str, Any]:
        return invoke_read("skill_catalog", runtime_args())

    @app.get("/api/v1/skills")
    def skill_list() -> dict[str, Any]:
        return invoke_read("skill_list", runtime_args())

    @app.post("/api/v1/skills")
    def skill_create(payload: SkillCreateInput) -> dict[str, Any]:
        return invoke_governed(
            "skill_create",
            runtime_args(**payload.model_dump()),
            actor_mode=ActorMode.BUILDER,
        )

    @app.post("/api/v1/skills/install")
    def skill_install(payload: SkillInstallInput) -> dict[str, Any]:
        return invoke_governed(
            "skill_install",
            runtime_args(**payload.model_dump(exclude_none=True)),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/skills/{name}")
    def skill_show(name: str) -> dict[str, Any]:
        return invoke_read("skill_show", runtime_args(name=name))

    @app.get("/api/v1/skills/{name}/test")
    def skill_test(name: str) -> dict[str, Any]:
        return invoke_read("skill_test", runtime_args(name=name))

    @app.post("/api/v1/skills/{name}/enable")
    def skill_enable(name: str) -> dict[str, Any]:
        return invoke_governed(
            "skill_enable",
            runtime_args(name=name),
            actor_mode=ActorMode.BUILDER,
        )

    @app.post("/api/v1/skills/{name}/disable")
    def skill_disable(name: str) -> dict[str, Any]:
        return invoke_governed(
            "skill_disable",
            runtime_args(name=name),
            actor_mode=ActorMode.BUILDER,
        )

    @app.delete("/api/v1/skills/{name}")
    def skill_remove(name: str) -> dict[str, Any]:
        return invoke_governed(
            "skill_remove",
            runtime_args(name=name),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/runtime-sessions")
    def runtime_session_list(limit: int = 100) -> dict[str, Any]:
        return invoke_read("runtime_session_list", runtime_args(limit=limit))

    @app.get("/api/v1/runtime-sessions/{session_id}/replay")
    def runtime_session_replay(session_id: str) -> dict[str, Any]:
        return invoke_read("runtime_session_replay", runtime_args(session_id=session_id))

    @app.get("/api/v1/traces")
    def trace_list(limit: int = 100) -> dict[str, Any]:
        return invoke_read("trace_list", runtime_args(limit=limit))

    @app.get("/api/v1/traces/{trace_id}")
    def trace_show(trace_id: str) -> dict[str, Any]:
        return invoke_read("trace_show", runtime_args(trace_id=trace_id))

    @app.get("/api/v1/traces/{trace_id}/export")
    def trace_export(trace_id: str, format: str = "json") -> dict[str, Any]:
        return invoke_read(
            "trace_export",
            runtime_args(trace_id=trace_id, format=format),
        )

    @app.get("/api/v1/traces/{trace_id}/replay")
    def trace_replay(trace_id: str) -> dict[str, Any]:
        return invoke_read("trace_replay", runtime_args(trace_id=trace_id))

    @app.get("/api/v1/jobs")
    def job_list(limit: int = 100) -> dict[str, Any]:
        return invoke_read("job_list", runtime_args(limit=limit))

    @app.post("/api/v1/jobs")
    def job_submit(payload: JobSubmitInput) -> dict[str, Any]:
        return invoke_governed(
            "job_submit",
            runtime_args(tool=payload.tool, args=payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/jobs/{job_id}")
    def job_show(job_id: str) -> dict[str, Any]:
        return invoke_read("job_show", runtime_args(job_id=job_id))

    @app.delete("/api/v1/jobs/{job_id}")
    def job_cancel(job_id: str) -> dict[str, Any]:
        return invoke_governed(
            "job_cancel",
            runtime_args(job_id=job_id),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/providers")
    def provider_list() -> dict[str, Any]:
        return invoke_read("provider_list", {})

    @app.get("/api/v1/providers/auth")
    def provider_auth() -> dict[str, Any]:
        return invoke_read("provider_auth", {})

    @app.get("/api/v1/models")
    def provider_models(
        provider: str | None = None,
        status: str | None = None,
        catalog_path: str | None = None,
    ) -> dict[str, Any]:
        return invoke_read(
            "provider_models",
            {
                "provider": provider,
                "status": status,
                "catalog_path": catalog_path,
            },
        )

    @app.get("/api/v1/connections")
    def connection_list() -> dict[str, Any]:
        return invoke_read("connection_list", runtime_args())

    @app.post("/api/v1/connections")
    def connection_add(payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "connection_add",
            runtime_args(**payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/connections/discover")
    def connection_discover() -> dict[str, Any]:
        return invoke_read("connection_discover", runtime_args())

    @app.post("/api/v1/connections/{name}/test")
    def connection_test(name: str) -> dict[str, Any]:
        return invoke_read("connection_test", runtime_args(name=name))

    @app.delete("/api/v1/connections/{name}")
    def connection_remove(name: str) -> dict[str, Any]:
        return invoke_governed(
            "connection_remove",
            runtime_args(name=name),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/metadata/status")
    def metadata_status(connection: str | None = None) -> dict[str, Any]:
        return invoke_read(
            "metadata_status",
            runtime_args(connection=connection),
        )

    @app.get("/api/v1/metadata/search")
    def metadata_search(query: str = "", connection: str | None = None, limit: int = 50) -> dict[str, Any]:
        return invoke_read(
            "schema_search",
            runtime_args(query=query, connection=connection, limit=limit),
        )

    @app.post("/api/v1/metadata/refresh")
    def metadata_refresh(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "schema_refresh",
            runtime_args(**payload.args),
        )

    @app.post("/api/v1/data-diff")
    def production_data_diff(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "data_diff",
            runtime_args(**payload.args),
        )

    @app.get("/api/v1/finops/report")
    def finops_report(
        connection: str | None = None,
        days: int = 7,
        limit: int = 1000,
    ) -> dict[str, Any]:
        return invoke_read(
            "finops_report",
            runtime_args(connection=connection, days=days, limit=limit),
        )

    @app.post("/api/v1/pii/scan")
    def pii_scan(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read("pii_scan", runtime_args(**payload.args))

    @app.post("/api/v1/pii/policy")
    def pii_policy(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "pii_policy_check",
            runtime_args(**payload.args),
        )

    @app.get("/api/v1/rbac/audit")
    def rbac_audit(connection: str | None = None) -> dict[str, Any]:
        return invoke_read(
            "rbac_audit",
            runtime_args(connection=connection),
        )

    @app.get("/api/v1/mcp")
    def mcp_list() -> dict[str, Any]:
        return invoke_read("mcp_list", runtime_args())

    @app.get("/api/v1/mcp/catalog")
    def mcp_catalog() -> dict[str, Any]:
        return invoke_read("mcp_catalog", runtime_args())

    @app.get("/api/v1/mcp/discover")
    def mcp_discover() -> dict[str, Any]:
        return invoke_read("mcp_discover", runtime_args())

    @app.post("/api/v1/mcp/install")
    def mcp_install(payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "mcp_install",
            runtime_args(**payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.get("/api/v1/mcp/{name}/status")
    def mcp_status(name: str) -> dict[str, Any]:
        return invoke_read("mcp_status", runtime_args(name=name))

    @app.get("/api/v1/mcp/{name}/tools")
    def mcp_tools(name: str) -> dict[str, Any]:
        return invoke_read("mcp_tools", runtime_args(name=name))

    @app.get("/api/v1/mcp/{name}/resources")
    def mcp_resources(name: str) -> dict[str, Any]:
        return invoke_read("mcp_resources", runtime_args(name=name))

    @app.post("/api/v1/review/dbt")
    def dbt_pr_review(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "dbt_pr_review",
            runtime_args(**payload.args),
        )

    @app.post("/api/v1/review/impact")
    def review_impact(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "change_impact",
            runtime_args(**payload.args),
        )

    @app.post("/api/v1/review/recommended-tests")
    def review_recommended_tests(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "recommended_tests",
            runtime_args(**payload.args),
        )

    @app.post("/api/v1/review/deployment-risk")
    def review_deployment_risk(payload: ArgsInput) -> dict[str, Any]:
        return invoke_read(
            "deployment_risk",
            runtime_args(**payload.args),
        )

    @app.post("/api/v1/review/github")
    def review_github(payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "github_pr_review",
            runtime_args(**payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.post("/api/v1/review/gitlab")
    def review_gitlab(payload: ArgsInput) -> dict[str, Any]:
        return invoke_governed(
            "gitlab_mr_review",
            runtime_args(**payload.args),
            actor_mode=ActorMode.BUILDER,
        )

    @app.post("/api/v1/dbt/execute/{operation}")
    def dbt_execute(operation: str, payload: ArgsInput) -> dict[str, Any]:
        allowed = {
            "parse": ("dbt_parse", ActorMode.ANALYST),
            "ls": ("dbt_ls", ActorMode.ANALYST),
            "compile": ("dbt_compile", ActorMode.ANALYST),
            "test": ("dbt_test", ActorMode.ANALYST),
            "run": ("dbt_run", ActorMode.BUILDER),
            "build": ("dbt_build", ActorMode.BUILDER),
            "seed": ("dbt_seed", ActorMode.BUILDER),
            "snapshot": ("dbt_snapshot", ActorMode.BUILDER),
        }
        if operation not in allowed:
            raise HTTPException(404, "unsupported dbt operation")
        tool_name, mode = allowed[operation]
        return invoke_governed(
            tool_name,
            runtime_args(**payload.args),
            actor_mode=mode,
        )

    @app.post("/api/v1/{domain}/{operation}")
    def invoke_domain(domain: str, operation: str, payload: ToolInput) -> dict[str, Any]:
        operations = DOMAIN_TOOLS.get(domain)
        if operations is None:
            raise HTTPException(404, f"unknown API domain: {domain}")
        tool_name = operations.get(operation)
        if tool_name is None:
            raise HTTPException(404, f"unknown {domain} operation: {operation}")
        return invoke_governed(
            tool_name,
            payload.args,
            actor_mode=payload.actor_mode,
            environment=payload.environment,
            dry_run=payload.dry_run,
            approved=payload.approved,
        )

    @app.post("/projects")
    def create_project(payload: ProjectInput) -> dict[str, Any]:
        record = ProjectRecord(payload.name)
        repo.save_project(record)
        return _record_payload(record)

    @app.get("/projects")
    def list_projects() -> list[dict[str, Any]]:
        return repo.list_records("projects")

    @app.post("/runs")
    def create_run(payload: RunInput) -> dict[str, Any]:
        record = RunRecord(payload.project_id, payload.environment_id, payload.intent)
        repo.save_run(record)
        return _record_payload(record)

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return _record_payload(run)

    @app.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        return repo.list_records("runs")

    @app.post("/discover")
    def discover() -> dict[str, str]:
        return {"status": "accepted", "detail": "discovery must be executed through a registered read-only connector"}

    @app.post("/migrations/plan")
    def plan_migration(payload: MigrationPlanInput) -> dict[str, Any]:
        plan = PlannerAgent().propose_migration(payload.intent, payload.source, payload.target, tuple(payload.objects))
        return _record_payload(plan)

    @app.post("/migrations/{migration_id}/execute")
    def execute_migration(migration_id: str) -> dict[str, str]:
        return {"migration_id": migration_id, "status": "approval_required", "detail": "execution is only available through ToolRegistry"}

    @app.post("/verify")
    def verify(payload: VerifyInput) -> dict[str, Any]:
        ast = parse_sql(payload.sql, payload.dialect)
        return {"parseable": ast.parseable, "statement_type": ast.statement_type, "tables": ast.tables, "errors": ast.errors}

    @app.get("/tools")
    def list_tools() -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "description": item.description,
                "capability": item.capability.value,
                "risk": item.risk.value,
                "input_schema": item.input_schema,
                "output_schema": item.output_schema,
            }
            for item in registry.definitions()
        ]

    @app.get("/api/v1/tools")
    def list_v1_tools() -> list[dict[str, Any]]:
        return list_tools()

    @app.post("/tools/{tool_name}")
    def invoke_tool(tool_name: str, payload: ToolInput) -> dict[str, Any]:
        return invoke_governed(
            tool_name,
            payload.args,
            actor_mode=payload.actor_mode,
            environment=payload.environment,
            dry_run=payload.dry_run,
            approved=payload.approved,
        )

    @app.post("/approvals")
    def approve(payload: ApprovalInput) -> dict[str, Any]:
        record = ApprovalRecord(
            payload.run_id,
            payload.approved_by,
            payload.scope,
            action=payload.action,
            environment=payload.environment,
            expires_at=payload.expires_at,
        )
        repo.save_approval(record)
        return _record_payload(record)

    @app.get("/approvals/{approval_id}")
    def get_approval(approval_id: str) -> dict[str, Any]:
        for record in repo.list_records("approvals"):
            if record["approval_id"] == approval_id:
                return record
        raise HTTPException(404, "approval not found")

    @app.get("/approvals")
    def list_approvals() -> list[dict[str, Any]]:
        return repo.list_records("approvals")

    @app.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> dict[str, Any]:
        for record in repo.list_records("generated_artifacts"):
            if record["artifact_id"] == artifact_id:
                return record
        raise HTTPException(404, "artifact not found")

    @app.get("/evidence/{evidence_id}")
    def get_evidence(evidence_id: str) -> dict[str, Any]:
        for record in repo.list_records("execution_evidence"):
            if record["evidence_id"] == evidence_id:
                return record
        raise HTTPException(404, "evidence not found")

    return app


app = create_app()
