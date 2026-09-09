#!/usr/bin/env python3
"""Manual live certification for advanced ADE Snowflake/Cortex capabilities."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable
import urllib.request

from agentic_data_platform.ai import SnowflakeAIWorkflowRunner
from agentic_data_platform.apps import SnowflakeAppBuilder
from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args
from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.cortex import CortexAgentClient
from agentic_data_platform.ml import SnowflakeModelRegistryAdapter
from agentic_data_platform.notebooks import NotebookAgent
from agentic_data_platform.semantic import CortexAnalystAdapter, SemanticRegistry, SnowflakeSemanticAdapter


READ_ONLY_COMPONENTS = {"semantic", "analyst", "cortex-agent", "model-registry", "ai-workflow"}
MUTATING_COMPONENTS = {"cortex-agent-run", "notebook", "streamlit", "app-runtime"}
ALL_COMPONENTS = READ_ONLY_COMPONENTS | MUTATING_COMPONENTS


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"BLOCKED_EXTERNAL: required environment variable is missing: {name}")
    return value


def approved() -> bool:
    return os.getenv("ADE_ADVANCED_LIVE_MUTATION_APPROVED", "false").casefold() == "true"


def snowflake_connector() -> SnowflakeConnector:
    connector = connector_from_args({"platform": "snowflake"})
    if not isinstance(connector, SnowflakeConnector):
        raise RuntimeError("BLOCKED_EXTERNAL: Snowflake connector is unavailable")
    return connector


def certify_semantic() -> dict[str, Any]:
    connector = snowflake_connector()
    adapter = SnowflakeSemanticAdapter(connector)
    view = required("ADE_LIVE_SEMANTIC_VIEW")
    rows = adapter.describe(view)
    with tempfile.TemporaryDirectory(prefix="ade-semantic-live-") as directory:
        registry = SemanticRegistry(Path(directory) / "semantic.db")
        resource = registry.ingest_describe_rows(view, rows)
    return {
        "status": "PASS",
        "semantic_view": view,
        "describe_row_count": len(rows),
        "counts": resource["counts"],
    }


def semantic_views() -> list[str]:
    raw = os.getenv("ADE_LIVE_SEMANTIC_VIEWS") or os.getenv("ADE_LIVE_SEMANTIC_VIEW") or ""
    views = [item.strip() for item in raw.split(",") if item.strip()]
    if not views:
        raise RuntimeError("BLOCKED_EXTERNAL: configure ADE_LIVE_SEMANTIC_VIEW or ADE_LIVE_SEMANTIC_VIEWS")
    return views


def certify_analyst() -> dict[str, Any]:
    question = os.getenv("ADE_LIVE_ANALYST_QUESTION") or "What business metrics are available?"
    result = CortexAnalystAdapter().run(question, semantic_views())
    if result.get("status") != "PASS":
        raise RuntimeError(f"Cortex Analyst live request failed: {result}")
    return {"status": "PASS", "question": question, "semantic_views": semantic_views(), "response": result.get("response")}


def cortex_client() -> CortexAgentClient:
    return CortexAgentClient()


def agent_identity() -> tuple[str, str, str]:
    return (
        required("ADE_LIVE_CORTEX_AGENT_DATABASE"),
        required("ADE_LIVE_CORTEX_AGENT_SCHEMA"),
        required("ADE_LIVE_CORTEX_AGENT_NAME"),
    )


def certify_cortex_agent() -> dict[str, Any]:
    database, schema, name = agent_identity()
    result = cortex_client().describe(database, schema, name)
    if result.get("status") != "PASS":
        raise RuntimeError(f"Cortex Agent describe failed: {result}")
    return {"status": "PASS", "database": database, "schema": schema, "name": name, "response": result.get("response")}


def certify_cortex_agent_run() -> dict[str, Any]:
    if not approved():
        raise RuntimeError("BLOCKED_EXTERNAL: Cortex Agent run requires ADE_ADVANCED_LIVE_MUTATION_APPROVED=true")
    database, schema, name = agent_identity()
    question = required("ADE_LIVE_CORTEX_AGENT_QUESTION")
    thread_id = os.getenv("ADE_LIVE_CORTEX_THREAD_ID")
    result = cortex_client().run(
        database, schema, name, question,
        thread_id=thread_id,
        background=bool(thread_id and os.getenv("ADE_LIVE_CORTEX_BACKGROUND", "false").casefold() == "true"),
    )
    if result.get("status") != "PASS":
        raise RuntimeError(f"Cortex Agent live run failed: {result}")
    return {"status": "PASS", "question": question, "response": result.get("response")}


def certify_model_registry() -> dict[str, Any]:
    connector = snowflake_connector()
    adapter = SnowflakeModelRegistryAdapter(connector)
    database = os.getenv("ADE_LIVE_MODEL_DATABASE") or os.getenv("ADE_SNOWFLAKE_DATABASE")
    schema = os.getenv("ADE_LIVE_MODEL_SCHEMA") or os.getenv("ADE_SNOWFLAKE_SCHEMA")
    models = adapter.models(database=database, schema=schema)
    result: dict[str, Any] = {"status": "PASS", "model_count": len(models), "models": models[:20]}
    model_name = os.getenv("ADE_LIVE_MODEL_NAME")
    if model_name:
        versions = adapter.versions(model_name)
        result["model_name"] = model_name
        result["versions"] = versions[:50]
        result["version_count"] = len(versions)
    return result


def certify_ai_workflow() -> dict[str, Any]:
    connector = snowflake_connector()
    workflow = {
        "name": "ade_live_sentiment",
        "source_sql": "SELECT \'The room was clean and the service was excellent\' AS REVIEW",
        "steps": [
            {
                "operation": "classify",
                "input": "REVIEW",
                "categories": ["positive", "negative", "neutral"],
                "alias": "SENTIMENT",
            }
        ],
    }
    result = SnowflakeAIWorkflowRunner(connector).run(workflow)
    if result.get("status") != "PASS":
        raise RuntimeError(f"Snowflake AI workflow failed: {result}")
    return result


def certify_notebook() -> dict[str, Any]:
    if not approved():
        raise RuntimeError("BLOCKED_EXTERNAL: notebook execution requires ADE_ADVANCED_LIVE_MUTATION_APPROVED=true")
    result = NotebookAgent.run_snowflake(
        "execute",
        identifier=required("ADE_LIVE_NOTEBOOK_IDENTIFIER"),
        cwd=os.getenv("ADE_LIVE_NOTEBOOK_CWD") or ".",
        project_definition=os.getenv("ADE_LIVE_NOTEBOOK_PROJECT"),
        connection=os.getenv("ADE_LIVE_SNOWFLAKE_CLI_CONNECTION"),
        timeout_seconds=int(os.getenv("ADE_LIVE_NOTEBOOK_TIMEOUT_SECONDS", "900")),
    )
    if result.get("status") != "PASS":
        raise RuntimeError(f"Snowflake notebook live execution failed: {result}")
    return result


def app_plan(kind: str, root: Path) -> dict[str, Any]:
    builder = SnowflakeAppBuilder(root)
    if kind == "streamlit":
        return builder.plan(
            kind="streamlit",
            app_name=os.getenv("ADE_LIVE_STREAMLIT_NAME") or "ade_live_streamlit",
            directory="app",
            database=required("ADE_SNOWFLAKE_DATABASE"),
            schema=required("ADE_SNOWFLAKE_SCHEMA"),
            query_warehouse=required("ADE_SNOWFLAKE_WAREHOUSE"),
            title="ADE Live Streamlit Certification",
            compute_pool=os.getenv("ADE_LIVE_STREAMLIT_COMPUTE_POOL"),
            streamlit_runtime=os.getenv("ADE_LIVE_STREAMLIT_RUNTIME") or "warehouse",
        )
    return builder.plan(
        kind="app-runtime",
        app_name=os.getenv("ADE_LIVE_APP_RUNTIME_NAME") or "ade_live_app_runtime",
        directory="app",
        database=required("ADE_SNOWFLAKE_DATABASE"),
        schema=required("ADE_SNOWFLAKE_SCHEMA"),
        query_warehouse=required("ADE_SNOWFLAKE_WAREHOUSE"),
        title="ADE Live App Runtime Certification",
    )


def certify_app(kind: str) -> dict[str, Any]:
    if not approved():
        raise RuntimeError(f"BLOCKED_EXTERNAL: {kind} deployment requires ADE_ADVANCED_LIVE_MUTATION_APPROVED=true")
    with tempfile.TemporaryDirectory(prefix=f"ade-{kind}-live-") as directory:
        root = Path(directory)
        builder = SnowflakeAppBuilder(root)
        plan = app_plan(kind, root)
        applied = builder.apply(plan, approval_fingerprint=plan["approval_fingerprint"])
        if applied.get("status") != "PASS":
            raise RuntimeError(f"{kind} fixture generation failed: {applied}")
        deployed = builder.deploy(
            plan,
            connection=os.getenv("ADE_LIVE_SNOWFLAKE_CLI_CONNECTION"),
            target=os.getenv("ADE_LIVE_APP_RUNTIME_TARGET") if kind == "app-runtime" else None,
            timeout_seconds=int(os.getenv("ADE_LIVE_APP_TIMEOUT_SECONDS", "1800")),
        )
        if deployed.get("status") != "PASS":
            raise RuntimeError(f"{kind} deployment failed: {deployed}")
        result: dict[str, Any] = {"status": "PASS", "plan": {k: v for k, v in plan.items() if k != "files"}, "deploy": deployed}
        if kind == "app-runtime" and os.getenv("ADE_LIVE_APP_RUNTIME_URL"):
            url = os.environ["ADE_LIVE_APP_RUNTIME_URL"].rstrip("/") + "/healthz"
            with urllib.request.urlopen(url, timeout=60) as response:
                body = response.read().decode("utf-8")
            result["health"] = {"url": url, "status_code": response.status, "body": body[:2000]}
            if response.status != 200:
                raise RuntimeError(f"App Runtime health probe failed: HTTP {response.status}")
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--components",
        default=os.getenv("ADE_ADVANCED_LIVE_COMPONENTS", "semantic,model-registry,ai-workflow"),
        help="Comma-separated advanced live components.",
    )
    parser.add_argument("--output", default=os.getenv("ADE_ADVANCED_LIVE_OUTPUT", "artifacts/advanced-live-certification.json"))
    args = parser.parse_args()
    components = [item.strip() for item in args.components.split(",") if item.strip()]
    unknown = sorted(set(components) - ALL_COMPONENTS)
    if unknown:
        raise SystemExit(f"unsupported advanced live components: {unknown}")

    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "semantic": certify_semantic,
        "analyst": certify_analyst,
        "cortex-agent": certify_cortex_agent,
        "cortex-agent-run": certify_cortex_agent_run,
        "model-registry": certify_model_registry,
        "ai-workflow": certify_ai_workflow,
        "notebook": certify_notebook,
        "streamlit": lambda: certify_app("streamlit"),
        "app-runtime": lambda: certify_app("app-runtime"),
    }
    report: dict[str, Any] = {
        "mode": "LIVE_ADVANCED_CAPABILITY_CERTIFICATION",
        "requested_components": components,
        "mutation_approved": approved(),
        "components": {},
    }
    failed = False
    for component in components:
        try:
            report["components"][component] = handlers[component]()
        except (ExternalConnectionUnavailable, RuntimeError, OSError, ValueError) as exc:
            text = str(exc)
            blocked = "BLOCKED_EXTERNAL" in text
            report["components"][component] = {
                "status": "BLOCKED_EXTERNAL" if blocked else "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
            failed = True

    report["status"] = "FAIL" if failed else "PASS"
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
