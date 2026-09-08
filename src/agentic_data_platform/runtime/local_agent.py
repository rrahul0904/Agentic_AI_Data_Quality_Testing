"""Persistent, low-cost project-aware agent runtime."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentic_data_platform.knowledge import extract_document
from agentic_data_platform.models import ActorMode
from agentic_data_platform.providers import ProviderRegistry
from agentic_data_platform.runtime.agent import AgentRuntime
from agentic_data_platform.runtime.context import ContextManager
from agentic_data_platform.runtime.context_sources import ContextSourceManager
from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.tools.registry import ToolRegistry
from agentic_data_platform.tracing import TraceStore
from agentic_data_platform.training.store import TrainingStore


DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.6-luna"
_PROJECT_PATTERNS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/**/*.md",
    "specs/**/*.md",
    "models/**/*.sql",
    "models/**/*.yml",
    "models/**/*.yaml",
    "dbt/**/*.sql",
    "dbt/**/*.yml",
    "dbt/**/*.yaml",
    "dbt_project.yml",
    "airflow/dags/**/*.py",
    "dags/**/*.py",
)


def _root(project_root: str | Path) -> Path:
    root = Path(project_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"project root not found: {root}")
    return root


def training_store(project_root: str | Path) -> TrainingStore:
    root = _root(project_root)
    return TrainingStore(root / ".ade" / "training.db")


def runtime_store(project_root: str | Path) -> RuntimeStore:
    root = _root(project_root)
    return RuntimeStore(root / ".ade" / "runtime.db")


def trace_store(project_root: str | Path) -> TraceStore:
    root = _root(project_root)
    return TraceStore(root / ".ade" / "traces.db")


def agent_config(
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    provider_name = provider or os.getenv("ADE_AGENT_PROVIDER") or os.getenv("ADE_LIVE_AGENT_PROVIDER") or DEFAULT_PROVIDER
    model_name = model or os.getenv("ADE_AGENT_MODEL") or os.getenv("ADE_LIVE_AGENT_MODEL") or DEFAULT_MODEL
    return {
        "provider": provider_name,
        "model": model_name,
        "max_steps": max(2, min(int(os.getenv("ADE_AGENT_MAX_STEPS", "8")), 20)),
        "context_tokens": max(8000, min(int(os.getenv("ADE_AGENT_CONTEXT_TOKENS", "32000")), 200000)),
        "reserve_tokens": max(2000, min(int(os.getenv("ADE_AGENT_RESERVE_TOKENS", "4000")), 32000)),
        "max_output_tokens": max(256, min(int(os.getenv("ADE_AGENT_MAX_OUTPUT_TOKENS", "1600")), 16000)),
        "reasoning_effort": os.getenv("ADE_OPENAI_REASONING_EFFORT", "low"),
    }


def provider_configured(provider_name: str | None = None) -> bool:
    name = provider_name or agent_config()["provider"]
    registry = ProviderRegistry()
    specs = {item["name"]: item for item in registry.specs()}
    spec = specs.get(name)
    return bool(spec and spec.get("configured"))


def index_project_knowledge(project_root: str | Path) -> dict[str, Any]:
    root = _root(project_root)
    return training_store(root).ingest_project(
        root,
        patterns=_PROJECT_PATTERNS,
        max_files=int(os.getenv("ADE_KNOWLEDGE_MAX_FILES", "3000")),
        max_bytes_per_file=int(os.getenv("ADE_KNOWLEDGE_MAX_FILE_BYTES", "2000000")),
    )


def ingest_document(
    project_root: str | Path,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
) -> dict[str, Any]:
    root = _root(project_root)
    extracted = extract_document(
        filename,
        content,
        content_type=content_type,
        max_bytes=int(os.getenv("ADE_KNOWLEDGE_UPLOAD_MAX_BYTES", "20000000")),
    )
    result = training_store(root).ingest_text(
        extracted.source,
        extracted.text,
        source_type=extracted.source_type,
        metadata=extracted.metadata,
    )
    return {
        **result,
        "source_type": extracted.source_type,
        "metadata": extracted.metadata,
    }


def knowledge_status(project_root: str | Path) -> dict[str, Any]:
    return training_store(project_root).status()


def knowledge_search(project_root: str | Path, query: str, *, limit: int = 10) -> dict[str, Any]:
    return {"results": training_store(project_root).search(query, limit=limit)}


def _read_only_registry(registry: ToolRegistry) -> ToolRegistry:
    safe = ToolRegistry()
    for definition in registry.definitions():
        if definition.enabled and definition.risk.value != "mutating":
            safe.register(definition)
    return safe


def _system_prompt(project_root: Path) -> str:
    return f"""You are ADE, an evidence-driven data engineering investigation agent.

Project root: {project_root}

Rules:
1. Deterministic tools establish facts. Never invent row counts, lineage, DAG state, dbt results, SQL results, or warehouse state.
2. Indexed project documents are contextual evidence, not proof of runtime state. When they matter, name the source document/chunk.
3. Prefer a small number of high-value tool calls. Stop when evidence is sufficient.
4. For incidents, localize the first divergence before proposing a root cause.
5. Distinguish measured facts, static code evidence, documented requirements, and your interpretation.
6. Never execute a mutating action. You may propose remediation, but human approval remains required.
7. If required evidence is unavailable, say what is missing instead of guessing.
"""


def run_project_agent(
    registry: ToolRegistry,
    project_root: str | Path,
    question: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    auto_index: bool = True,
) -> dict[str, Any]:
    root = _root(project_root)
    config = agent_config(provider=provider, model=model)
    provider_name = str(config["provider"])
    if not provider_configured(provider_name):
        return {
            "status": "BLOCKED_EXTERNAL",
            "question": question,
            "provider": provider_name,
            "model": config["model"],
            "error": f"provider {provider_name!r} is not configured",
        }

    indexed = index_project_knowledge(root) if auto_index else {"status": "SKIP", "reason": "auto_index_disabled"}
    corpus = training_store(root)
    sources = ContextSourceManager(
        training_store=corpus,
        max_training=max(1, min(int(os.getenv("ADE_AGENT_CONTEXT_CHUNKS", "6")), 20)),
    )
    store = runtime_store(root)
    traces = trace_store(root)
    provider_impl = ProviderRegistry().create(provider_name)
    session_id = store.create_session(
        project_id=str(root),
        title=question[:120],
        provider=provider_name,
        model=str(config["model"]),
    )
    store.add_message(session_id, "system", _system_prompt(root))

    context_tokens = int(config["context_tokens"])
    reserve_tokens = int(config["reserve_tokens"])
    if reserve_tokens >= context_tokens:
        reserve_tokens = max(2000, context_tokens // 4)

    runtime = AgentRuntime(
        _read_only_registry(registry),
        store,
        traces,
        context=ContextManager(max_tokens=context_tokens, reserve_tokens=reserve_tokens),
        context_sources=sources,
        max_steps=int(config["max_steps"]),
        repeated_tool_limit=2,
        max_output_tokens=int(config["max_output_tokens"]),
        provider_metadata={"reasoning_effort": config["reasoning_effort"]},
    )
    result = runtime.run(
        session_id,
        question,
        provider_impl,
        str(config["model"]),
        actor_mode=ActorMode.ANALYST,
        project_root=root,
    )
    calls = store.tool_calls(session_id)
    selected = result.get("context_sources") or {}
    return {
        "status": "PASS",
        "question": question,
        "result": result.get("response"),
        "session_id": session_id,
        "trace_id": result.get("trace_id"),
        "provider": provider_name,
        "model": config["model"],
        "steps": result.get("steps"),
        "evidence": {
            "mode": "LLM_GOVERNED_TOOL_RUNTIME",
            "tools_used": [item["tool"] for item in calls],
            "tool_statuses": [{"tool": item["tool"], "status": item["status"]} for item in calls],
            "context_sources": selected,
            "project_index": {
                "indexed": indexed.get("indexed", 0),
                "unchanged": indexed.get("unchanged", 0),
                "skipped": indexed.get("skipped", 0),
            },
        },
    }
