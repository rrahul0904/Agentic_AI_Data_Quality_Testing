from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agentic_data_platform.agents.planner import PlannerAgent
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


def _record_payload(record: Any) -> dict[str, Any]:
    value = asdict(record)
    for key, item in list(value.items()):
        if hasattr(item, "value"):
            value[key] = item.value
    return value


def create_app(repository: SQLiteControlPlaneRepository | None = None) -> FastAPI:
    # A local durable default makes the interactive API useful without extra setup.
    repo = repository or SQLiteControlPlaneRepository(os.getenv("ADE_DATABASE_PATH", "ade.db"))
    repo.initialize()
    registry = build_tool_registry()
    app = FastAPI(title="UMA — Unified Data Migration Accelerator", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("ADE_UI_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
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
            {"name": item.name, "description": item.description, "capability": item.capability.value,
             "risk": item.risk.value, "input_schema": item.input_schema, "output_schema": item.output_schema}
            for item in registry.definitions()
        ]

    @app.post("/tools/{tool_name}")
    def invoke_tool(tool_name: str, payload: ToolInput) -> dict[str, Any]:
        try:
            definition = registry.describe(tool_name)
            request = ToolRequest(
                tool=tool_name, operation=tool_name, environment=payload.environment, risk=definition.risk,
                args=payload.args,
            )
            return registry.invoke(ToolInvocation(request, run_id=f"api-{tool_name}", dry_run=payload.dry_run, actor_mode=payload.actor_mode))
        except (KeyError, ValueError, PermissionError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/approvals")
    def approve(payload: ApprovalInput) -> dict[str, Any]:
        record = ApprovalRecord(payload.run_id, payload.approved_by, payload.scope, action=payload.action, environment=payload.environment, expires_at=payload.expires_at)
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
