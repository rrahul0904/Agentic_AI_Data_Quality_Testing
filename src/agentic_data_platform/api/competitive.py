"""Small compositional API surface for competitive capability extensions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agentic_data_platform.compute import ComputeJobSpec, PortableComputePlanner
from agentic_data_platform.knowledge import DocumentIntelligencePipeline, snowflake_parse_document_sql
from agentic_data_platform.retrieval import (
    ADESearchIndex,
    LocalProjectRetrievalBackend,
    RetrievalQuery,
    SearchChunk,
)


class RetrievalInput(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=10, ge=1, le=100)


class SearchIndexInput(BaseModel):
    source: str = Field(min_length=1, max_length=4096)
    content: str = Field(min_length=1, max_length=1_000_000)
    chunk_id: str | None = Field(default=None, max_length=512)
    metadata: dict[str, Any] = Field(default_factory=dict)
    index_name: str = Field(default="default", min_length=1, max_length=128)


class SearchQueryInput(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    limit: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] | None = None
    index_name: str = Field(default="default", min_length=1, max_length=128)
    explain: bool = True
    lexical_weight: float = Field(default=0.45, ge=0)
    vector_weight: float = Field(default=0.45, ge=0)
    rerank_weight: float = Field(default=0.10, ge=0)


class SearchSourceInput(BaseModel):
    source: str = Field(min_length=1, max_length=4096)
    index_name: str = Field(default="default", min_length=1, max_length=128)


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


def _search_index(index_name: str = "default") -> ADESearchIndex:
    return ADESearchIndex(_project_root() / ".ade" / "search.db", index_name=index_name)


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
                "ade_search": ["sqlite_fts5", "pluggable_embeddings", "hybrid", "filters", "explain"],
                "cortex_search_adapter": True,
                "portable_compute": ["docker", "kubernetes", "snowflake_spcs"],
                "document_intelligence": ["local", "ocr_provider", "provider", "snowflake_ai_parse_document"],
            },
            "truthfulness": {
                "default_vector_lane": "deterministic lexical hash projection, not a learned embedding model",
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

    @application.post("/api/v1/search/index", tags=["search"])
    def search_index(payload: SearchIndexInput) -> dict[str, object]:
        try:
            chunk_id = payload.chunk_id or hashlib.sha256(
                f"{payload.source}\0{payload.content}".encode("utf-8")
            ).hexdigest()
            index = _search_index(payload.index_name)
            mutation = index.upsert(
                SearchChunk(
                    chunk_id=chunk_id,
                    source=payload.source,
                    content=payload.content,
                    metadata=payload.metadata,
                )
            )
            return {
                "status": "PASS",
                "mutation": mutation.status,
                "chunk_id": mutation.chunk_id,
                "content_hash": mutation.content_hash,
                "index": index.stats(),
            }
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/v1/search/query", tags=["search"])
    def search_query(payload: SearchQueryInput) -> dict[str, object]:
        try:
            index = _search_index(payload.index_name)
            hits = index.search(
                RetrievalQuery(payload.query, limit=payload.limit, filters=payload.filters),
                lexical_weight=payload.lexical_weight,
                vector_weight=payload.vector_weight,
                rerank_weight=payload.rerank_weight,
                explain=payload.explain,
            )
            return {
                "status": "PASS",
                "backend": index.backend_name,
                "index_name": payload.index_name,
                "results": [hit.as_dict() for hit in hits],
            }
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.get("/api/v1/search/stats", tags=["search"])
    def search_stats(index_name: str = "default") -> dict[str, object]:
        try:
            return {"status": "PASS", **_search_index(index_name).stats()}
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/v1/search/delete-source", tags=["search"])
    def search_delete_source(payload: SearchSourceInput) -> dict[str, object]:
        try:
            index = _search_index(payload.index_name)
            removed = index.delete_source(payload.source)
            return {"status": "PASS", "removed": removed, "index": index.stats()}
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/v1/document/process", tags=["document"])
    async def document_process(
        file: UploadFile = File(...),
        index_name: str = Form("documents"),
        index_document: bool = Form(True),
        metadata_json: str = Form("{}"),
    ) -> dict[str, object]:
        max_bytes = 20_000_000
        content = await file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"document exceeds max_bytes={max_bytes}")
        try:
            metadata = json.loads(metadata_json)
            if not isinstance(metadata, dict):
                raise ValueError("metadata_json must decode to an object")
            index = _search_index(index_name) if index_document else None
            pipeline = DocumentIntelligencePipeline(index)
            result = pipeline.process(
                file.filename or "document",
                content,
                content_type=file.content_type,
                max_bytes=max_bytes,
                index_metadata=metadata,
            )
            return {"status": "PASS", "document": result.as_dict()}
        except (json.JSONDecodeError, OSError, ValueError, RuntimeError) as exc:
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
