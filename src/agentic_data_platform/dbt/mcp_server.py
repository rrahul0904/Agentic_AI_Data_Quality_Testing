"""MCP v2 server exposing governed ADE dbt context to AI hosts.

The server is intentionally read-only. It delegates to the same deterministic
functions used by ADE's CLI, FastAPI control plane and operator console.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from agentic_data_platform.dbt.nextgen import (
    agents_schema,
    chart_compile,
    context_bundle,
    context_search,
    explore_plan,
    explore_query_contract,
    lake_compute_plan,
    model_compute_plan,
    state_execution_contract,
    state_plan,
    wizard_plan,
)


mcp = MCPServer(
    "ADE dbt Context",
    instructions=(
        "Use ADE dbt context tools to ground analytics-engineering questions in dbt artifacts, "
        "semantic definitions, verified queries, version-controlled dashboard contracts and "
        "read-only lake-compute plans. These tools do not mutate warehouses."
    ),
)


def _defaults() -> dict[str, Any]:
    args: dict[str, Any] = {
        "project": os.getenv("ADE_MCP_PROJECT", "."),
    }
    manifest = os.getenv("ADE_MCP_MANIFEST")
    semantic = os.getenv("ADE_MCP_SEMANTIC_DATABASE")
    if manifest:
        args["manifest_path"] = manifest
    if semantic:
        args["semantic_database"] = semantic
    documents = [item for item in os.getenv("ADE_MCP_CONTEXT_DOCUMENTS", "").split(os.pathsep) if item]
    if documents:
        args["documents"] = documents
    return args


READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


@mcp.tool(title="Search governed dbt project context", annotations=READ_ONLY)
def dbt_context_search(query: str, limit: int = 20) -> dict[str, Any]:
    """Search dbt models, metrics, semantic resources and configured context documents."""
    return context_search({**_defaults(), "query": query, "limit": limit})


@mcp.tool(title="Build governed dbt context bundle", annotations=READ_ONLY)
def dbt_context_bundle() -> dict[str, Any]:
    """Return bounded structured and unstructured project context with an evidence fingerprint."""
    return context_bundle(_defaults())


@mcp.tool(title="Plan an analytics-engineering task", annotations=READ_ONLY)
def dbt_wizard_plan(question: str, limit: int = 12) -> dict[str, Any]:
    """Classify a dbt project question and recommend governed ADE tools using project evidence."""
    return wizard_plan({**_defaults(), "question": question, "limit": limit})


@mcp.tool(title="Plan governed conversational analytics", annotations=READ_ONLY)
def dbt_explore_plan(question: str, limit: int = 25) -> dict[str, Any]:
    """Resolve a business question to governed metrics, dimensions and verified queries."""
    args = _defaults()
    if not args.get("semantic_database"):
        return {
            "status": "CONFIGURATION_REQUIRED",
            "required": "ADE_MCP_SEMANTIC_DATABASE",
            "question": question,
        }
    return explore_plan({**args, "question": question, "limit": limit})


@mcp.tool(title="Compile governed Explore verified-query contract", annotations=READ_ONLY)
def dbt_explore_query_contract(
    question: str,
    verified_query_name: str = "",
) -> dict[str, Any]:
    """Resolve a question to sufficiently matched verified read-only SQL without executing it."""
    args = _defaults()
    if not args.get("semantic_database"):
        return {
            "status": "CONFIGURATION_REQUIRED",
            "required": "ADE_MCP_SEMANTIC_DATABASE",
            "question": question,
        }
    payload: dict[str, Any] = {**args, "question": question}
    if verified_query_name:
        payload["verified_query_name"] = verified_query_name
    return explore_query_contract(payload)


@mcp.tool(title="Plan state-aware dbt work", annotations=READ_ONLY)
def dbt_state_plan(
    previous_manifest_path: str,
    current_manifest_path: str = "",
) -> dict[str, Any]:
    """Classify changed dbt work as BUILD/SKIP with optional clone/defer evidence supplied by callers."""
    args = _defaults()
    if current_manifest_path:
        args["manifest_path"] = current_manifest_path
    args["previous_manifest_path"] = previous_manifest_path
    return state_plan(args)


@mcp.tool(title="Compile state-aware dbt execution contract", annotations=READ_ONLY)
def dbt_state_execution_contract(
    previous_manifest_path: str,
    current_manifest_path: str = "",
    state_dir: str = "",
) -> dict[str, Any]:
    """Compile deterministic dbt clone/build commands without executing them."""
    args = _defaults()
    if current_manifest_path:
        args["manifest_path"] = current_manifest_path
    args["previous_manifest_path"] = previous_manifest_path
    if state_dir:
        args["state_dir"] = state_dir
    return state_execution_contract(args)


@mcp.tool(title="Compile BI-as-code dashboard YAML", annotations=READ_ONLY)
def dbt_chart_compile(yaml_text: str) -> dict[str, Any]:
    """Validate and compile a dashboard YAML contract for governed downstream consumers."""
    return chart_compile({"yaml": yaml_text})


@mcp.tool(title="Plan per-model dbt compute routing", annotations=READ_ONLY)
def dbt_model_compute_plan(
    default_engine: str = "warehouse",
    model_engines: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Route individual dbt models to warehouse or lake compute and expose cross-engine boundaries."""
    return model_compute_plan({
        **_defaults(),
        "default_engine": default_engine,
        "model_engines": model_engines or {},
    })


@mcp.tool(title="Plan read-only lake compute", annotations=READ_ONLY)
def dbt_lake_compute_plan(
    source: str,
    source_type: str = "auto",
    sql: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Plan DuckDB execution over Parquet or Apache Iceberg without executing the query."""
    args: dict[str, Any] = {"source": source, "source_type": source_type, "limit": limit}
    if sql:
        args["sql"] = sql
    return lake_compute_plan(args)


@mcp.resource(
    "ade://dbt/agents-schema",
    name="ade_dbt_agents_schema",
    title="ADE dbt agent resource contract",
    description="Open agent/MCP resource contract for the dbt-next capability set.",
    mime_type="application/json",
)
def dbt_agents_schema_resource() -> dict[str, Any]:
    """Return the stable ADE dbt agent resource contract."""
    return agents_schema({})


def main() -> int:
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
