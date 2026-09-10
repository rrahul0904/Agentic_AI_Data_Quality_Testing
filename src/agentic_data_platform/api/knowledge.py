"""Project knowledge and governed project-agent API composition."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agentic_data_platform.errors import safe_error
from agentic_data_platform.runtime.local_agent import (
    index_project_knowledge,
    ingest_document,
    knowledge_search,
    knowledge_status,
    provider_configured,
    run_project_agent,
    training_store,
)
from agentic_data_platform.security.redaction import redact_string
from agentic_data_platform.tools.builtin import build_tool_registry


_AGENT_PATH = "/api/v1/agent/query"
_KNOWLEDGE_PREFIX = "/api/v1/knowledge"


class ProjectAgentQueryInput(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    provider: str | None = None
    model: str | None = None
    mode: str = Field(default="auto", pattern="^(auto|live|deterministic)$")


class KnowledgeTextInput(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    source_type: str = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


def _program_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _project_root() -> Path:
    configured = os.getenv("ADE_DEMO_PROJECT")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else _program_root() / "hospitality-snowflake-data-platform"
    )


def _route(application: FastAPI, path: str, method: str):
    for route in application.routes:
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", None) == path and method in methods:
            return route
    return None


def _remove_route(application: FastAPI, path: str, method: str) -> Callable[..., Any] | None:
    retained = []
    endpoint = None
    for route in application.routes:
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", None) == path and method in methods:
            endpoint = endpoint or getattr(route, "endpoint", None)
            continue
        retained.append(route)
    application.router.routes = retained
    return endpoint


def _effective_mode(requested: str) -> str:
    configured = os.getenv("ADE_AGENT_MODE", "auto").strip().casefold()
    if requested == "auto" and configured in {"live", "deterministic"}:
        return configured
    return requested


def _blocked_external(payload: ProjectAgentQueryInput) -> dict[str, Any]:
    return {
        "status": "BLOCKED_EXTERNAL",
        "question": payload.question.strip(),
        "provider": payload.provider or os.getenv("ADE_AGENT_PROVIDER", "openai"),
        "model": payload.model or os.getenv("ADE_AGENT_MODEL", "gpt-5.6-luna"),
        "error": "LLM provider is not configured; configure provider credentials outside the repository",
        "evidence": {
            "tools_used": [],
            "data_sources": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "BLOCKED_EXTERNAL",
        },
    }


def attach_knowledge_routes(application: FastAPI) -> FastAPI:
    """Attach knowledge routes and upgrade the agent query endpoint exactly once."""

    if _route(application, f"{_KNOWLEDGE_PREFIX}/status", "GET") is not None:
        return application

    legacy_agent = _remove_route(application, _AGENT_PATH, "POST")

    @application.post(_AGENT_PATH, tags=["agent"], name="project_aware_agent_query")
    def project_agent_query(payload: ProjectAgentQueryInput) -> dict[str, Any]:
        question = payload.question.strip()
        mode = _effective_mode(payload.mode)
        if mode in {"auto", "live"}:
            if provider_configured(payload.provider):
                try:
                    return run_project_agent(
                        build_tool_registry(),
                        _project_root(),
                        question,
                        provider=payload.provider,
                        model=payload.model,
                    )
                except (KeyError, ValueError, FileNotFoundError) as exc:
                    raise HTTPException(400, safe_error(exc)) from exc
                except Exception as exc:
                    raise HTTPException(502, safe_error(exc)) from exc
            if mode == "live":
                return _blocked_external(payload)
        if legacy_agent is None:
            raise HTTPException(500, "deterministic agent route is unavailable")
        return legacy_agent(SimpleNamespace(question=question))

    @application.get(f"{_KNOWLEDGE_PREFIX}/status", tags=["knowledge"])
    def project_knowledge_status() -> dict[str, Any]:
        return knowledge_status(_project_root())

    @application.get(f"{_KNOWLEDGE_PREFIX}/search", tags=["knowledge"])
    def project_knowledge_search(query: str, limit: int = 10) -> dict[str, Any]:
        return knowledge_search(_project_root(), query, limit=max(1, min(limit, 100)))

    @application.post(f"{_KNOWLEDGE_PREFIX}/index-project", tags=["knowledge"])
    def project_knowledge_index() -> dict[str, Any]:
        return index_project_knowledge(_project_root())

    @application.post(f"{_KNOWLEDGE_PREFIX}/ingest-text", tags=["knowledge"])
    def project_knowledge_ingest_text(payload: KnowledgeTextInput) -> dict[str, Any]:
        safe_text = redact_string(payload.text)
        metadata = dict(payload.metadata)
        metadata["secrets_redacted"] = safe_text != payload.text
        return training_store(_project_root()).ingest_text(
            payload.source,
            safe_text,
            source_type=payload.source_type,
            metadata=metadata,
        )

    @application.post(f"{_KNOWLEDGE_PREFIX}/upload", tags=["knowledge"])
    async def project_knowledge_upload(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            content = await file.read()
            return ingest_document(
                _project_root(),
                file.filename or "document",
                content,
                content_type=file.content_type,
            )
        except ValueError as exc:
            raise HTTPException(400, safe_error(exc)) from exc

    return application


__all__ = ["ProjectAgentQueryInput", "attach_knowledge_routes"]
