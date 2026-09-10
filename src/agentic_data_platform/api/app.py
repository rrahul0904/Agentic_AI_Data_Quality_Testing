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
from agentic_data_platform.certification import coco_certification_status
from agentic_data_platform.errors import safe_error
from agentic_data_platform.agents import InvestigationStore, SupervisorAgent
from agentic_data_platform.models import ActorMode, ApprovalRecord, Environment, InteractionMode, ProjectRecord, RunRecord, ToolRequest
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
    interaction_mode: InteractionMode = InteractionMode.AGENT
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
        interaction_mode: InteractionMode = InteractionMode.AGENT,
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
                    interaction_mode=interaction_mode,
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

    @app.get("/api/v1/certification/coco")
    def coco_certification() -> dict[str, Any]:
        return coco_certification_status(_program_root())

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
