"""Small compositional API surface for competitive capability extensions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agentic_data_platform.compute import ComputeJobSpec, PortableComputePlanner
from agentic_data_platform.knowledge import snowflake_parse_document_sql
from agentic_data_platform.retrieval import LocalProjectRetrievalBackend, RetrievalQuery


class RetrievalInput(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=10, ge=1, le=100)


class ComputePlanInput(BaseModel):
    backend: Literal["docker", "kubernetes", "snowflake-spcs"]
    name: str
    image: str
    command: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cpu: float = Field(default=1.0, ge=0.1, le=256)
    memory_gib: float = Field(default=2.0, ge=0.1, le=4096)
    gpu: int = Field(default=0, ge=0, le=64)
    replicas: int = Field(default=1, ge=1, le=1000)
    timeout_seconds: int = Field(default=3600, ge=1, le=604800)
    network_enabled: bool = False
    workspace: str | None = None
    namespace: str = "default"
    compute_pool: str | None = None
    query_warehouse: str | None = None


class SnowflakeDocumentPlanInput(BaseModel):
    stage: str
    relative_path: str
    mode: Literal["OCR", "LAYOUT"] = "LAYOUT"
    page_split: bool = True
    extract_images: bool = False


def _project_root() -> Path:
    configured = os.getenv("ADE_DEMO_PROJECT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3]


def _route(application: FastAPI, path: str, method: str) -> bool:
    return any(
        getattr(route, "path", None) == path
        and method in (getattr(route, "methods", set()) or set())
        for route in application.routes
    )


def attach_competitive_routes(application: FastAPI) -> FastAPI:
    if _route(application, "/api/v1/competitive/status", "GET"):
        return application

    @application.get("/api/v1/competitive/status", tags=["competitive"])
    def competitive_status() -> dict[str, object]:
        return {
            "status": "PASS",
            "surfaces": {
                "embedded_agent_sdk": True,
                "acp_stdio": True,
                "ssh_remote_workspace": True,
                "provider_neutral_retrieval": True,
                "portable_compute": ["docker", "kubernetes", "snowflake_spcs"],
                "document_intelligence": ["local", "provider", "snowflake_ai_parse_document"],
            },
            "truthfulness": {
                "live_external_certification_required": True,
                "superiority_requires_benchmark_evidence": True,
            },
        }

    @application.post("/api/v1/retrieval/search", tags=["retrieval"])
    def retrieval_search(payload: RetrievalInput) -> dict[str, object]:
        try:
            backend = LocalProjectRetrievalBackend(_project_root())
            hits = backend.search(RetrievalQuery(payload.query, limit=payload.limit))
            return {"status": "PASS", "backend": backend.name, "results": [hit.as_dict() for hit in hits]}
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/v1/compute/plan", tags=["compute"])
    def compute_plan(payload: ComputePlanInput) -> dict[str, object]:
        try:
            spec = ComputeJobSpec(
                name=payload.name,
                image=payload.image,
                command=tuple(payload.command),
                env=payload.env,
                cpu=payload.cpu,
                memory_gib=payload.memory_gib,
                gpu=payload.gpu,
                timeout_seconds=payload.timeout_seconds,
                network_enabled=payload.network_enabled,
                workspace=payload.workspace,
                replicas=payload.replicas,
            )
            planner = PortableComputePlanner()
            if payload.backend == "docker":
                plan = planner.docker(spec)
            elif payload.backend == "kubernetes":
                plan = planner.kubernetes(spec, namespace=payload.namespace)
            else:
                if not payload.compute_pool:
                    raise ValueError("compute_pool is required for snowflake-spcs")
                plan = planner.snowflake_spcs(
                    spec,
                    compute_pool=payload.compute_pool,
                    query_warehouse=payload.query_warehouse,
                )
            return {"status": "PLAN", **plan.as_dict()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/v1/document/snowflake-plan", tags=["document"])
    def document_snowflake_plan(payload: SnowflakeDocumentPlanInput) -> dict[str, object]:
        try:
            return {
                "status": "PLAN",
                "backend": "snowflake_ai_parse_document",
                "sql": snowflake_parse_document_sql(
                    payload.stage,
                    payload.relative_path,
                    mode=payload.mode,
                    page_split=payload.page_split,
                    extract_images=payload.extract_images,
                ),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return application


__all__ = ["attach_competitive_routes"]
