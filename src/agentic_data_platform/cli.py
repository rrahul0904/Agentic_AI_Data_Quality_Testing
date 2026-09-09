from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agentic_data_platform.dbt.adapter import LocalDbtProjectAdapter
from agentic_data_platform.errors import safe_error
from agentic_data_platform.platform.discovery import render_discovery
from agentic_data_platform.migration.sqlserver_snowflake import plan_sqlserver_to_snowflake
from agentic_data_platform.models import ActorMode, ApprovalRecord, Environment, ToolRequest
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository
from agentic_data_platform.sql.engine import analyze_sql
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


DOMAIN_CLI_TOOLS: dict[str, dict[str, str]] = {
    "sql": {
        "analyze": "sql_analyze", "review": "sql_review", "autocomplete": "sql_autocomplete",
        "classify": "sql_classify", "diff": "sql_diff", "execute": "sql_execute",
        "explain": "sql_explain", "fix": "sql_fix", "format": "sql_format",
        "optimize": "sql_optimize", "rewrite": "sql_rewrite", "translate": "sql_translate",
        "fingerprint": "sql_fingerprint",
    },
    "lineage": {
        "sql": "sql_column_lineage", "column": "column_lineage",
        "upstream": "column_upstream", "downstream": "column_downstream",
        "impact": "column_impact", "diff": "column_lineage_diff",
        "graph": "project_column_graph", "path": "column_path",
    },
    "schema": {
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
        "ingest-yaml": "semantic_ingest_yaml", "list": "semantic_list", "show": "semantic_show",
        "search": "semantic_registry_search", "verified-search": "semantic_verified_search",
        "evaluate": "semantic_evaluate", "evaluate-batch": "semantic_evaluate_batch",
        "snowflake-sync": "semantic_snowflake_sync",
        "analyst-plan": "cortex_analyst_plan", "analyst-run": "cortex_analyst_run",
    },
    "warehouse": {
        "status": "warehouse_status", "add": "connection_add", "remove": "connection_remove",
        "list": "connection_list", "show": "connection_show", "test": "connection_test",
        "default": "connection_default", "discover": "connection_discover",
    },
    "diff": {
        "run": "data_diff", "plan": "data_diff_plan", "profile": "data_diff_profile",
        "join": "data_diff_join", "hash": "data_diff_hash", "cascade": "data_diff_cascade",
        "schema": "data_diff_schema",
    },
    "quality": {
        "summary": "quality_summary", "recent": "quality_recent",
        "reconciliation-history": "reconciliation_history",
        "asset-health": "asset_health_score", "pipeline-health": "pipeline_health_score",
    },
    "snowflake-admin": {
        "plan": "snowflake_mutation_plan",
        "execute": "snowflake_mutation_execute",
    },
    "snowflake-test": {
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
    "dbt-run": {
        "parse": "dbt_parse", "ls": "dbt_ls", "compile": "dbt_compile",
        "run": "dbt_run", "test": "dbt_test", "build": "dbt_build",
        "seed": "dbt_seed", "snapshot": "dbt_snapshot", "validate": "dbt_validate",
        "test-generate": "dbt_test_generate", "unit-test-generate": "dbt_unit_test_gen",
    },
    "dbt-managed": {
        "commands": "snowflake_managed_dbt_commands",
        "plan": "snowflake_managed_dbt_plan",
        "execute": "snowflake_managed_dbt_execute",
    },
    "review": {
        "dbt": "dbt_pr_review", "impact": "change_impact",
        "tests": "recommended_tests", "risk": "deployment_risk",
        "github": "github_pr_review", "gitlab": "gitlab_mr_review",
    },
    "connection": {
        "add": "connection_add", "remove": "connection_remove", "list": "connection_list",
        "show": "connection_show", "test": "connection_test", "default": "connection_default",
        "discover": "connection_discover",
    },
    "metadata": {
        "refresh": "schema_refresh", "index": "schema_index", "search": "schema_search",
        "inspect": "schema_inspect", "tags": "schema_tags", "status": "metadata_status",
        "autocomplete": "autocomplete",
    },
    "data-diff": {
        "run": "data_diff", "plan": "data_diff_plan", "profile": "data_diff_profile",
        "join": "data_diff_join", "hash": "data_diff_hash", "cascade": "data_diff_cascade",
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
        "pii-access": "pii_access_report",
    },
    "provider": {
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
    "skill": {
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
    "session": {
        "create": "session_create", "list": "session_list", "show": "session_show",
        "message-add": "session_message_add", "messages": "session_messages",
        "status": "session_status", "status-set": "session_status_set",
        "todo-add": "session_todo_add", "todo-update": "session_todo_update",
        "todos": "session_todos", "reminder-add": "session_reminder_add",
        "reminders": "session_reminders", "reminder-deliver": "session_reminder_deliver",
        "revert": "session_revert", "state": "session_state",
        "state-patch": "session_state_patch", "prompt": "session_prompt",
        "compact": "session_compact", "nudge": "session_nudge",
        "termination": "session_termination", "retry-plan": "session_retry_plan",
        "tool-result-cap": "session_tool_result_cap", "overflow": "session_overflow",
    },
    "memory": {
        "save": "memory_save", "list": "memory_list", "search": "memory_search",
        "remove": "memory_remove",
    },
    "trace": {
        "list": "trace_list", "show": "trace_show", "export": "trace_export",
        "replay": "trace_replay",
    },
    "job": {
        "submit": "job_submit", "list": "job_list", "show": "job_show",
        "cancel": "job_cancel",
    },
    "automation": {
        "create": "automation_create", "list": "automation_list", "show": "automation_show",
        "enable": "automation_enable", "approve": "automation_approve",
        "run-due": "automation_run_due", "delete": "automation_delete",
    },
    "plugin": {
        "validate": "plugin_bundle_validate", "install": "plugin_bundle_install",
        "list": "plugin_bundle_list", "show": "plugin_bundle_show",
        "activate": "plugin_bundle_activate", "remove": "plugin_bundle_remove",
    },
}


def _repo(path: str) -> SQLiteControlPlaneRepository:
    repo = SQLiteControlPlaneRepository(path)
    repo.initialize()
    return repo


def _default_project() -> str:
    cwd = Path.cwd()
    if (cwd / "hospitality-snowflake-data-platform").is_dir():
        return str(cwd / "hospitality-snowflake-data-platform")
    return str(cwd)


def _invoke(
    name: str,
    args: dict,
    *,
    actor_mode: ActorMode = ActorMode.ANALYST,
    environment: Environment = Environment.DEV,
    dry_run: bool = False,
    approved: bool = False,
) -> dict:
    registry = build_tool_registry()
    definition = registry.describe(name)
    request = ToolRequest(name, name, environment, definition.risk, args=args)
    return registry.invoke(
        ToolInvocation(
            request,
            run_id=f"cli-{name}",
            approved=approved,
            dry_run=dry_run,
            actor_mode=actor_mode,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-data-platform", description="Governed agentic data-engineering control plane")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    discover = sub.add_parser("discover")
    discover.add_argument("project", nargs="?", default=".")
    discover.add_argument("--dbt-project")
    discover.add_argument("--manifest")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("project", nargs="?", default=_default_project())
    tool = sub.add_parser("tool", help="invoke any registered deterministic tool with JSON args")
    tool.add_argument("name")
    tool.add_argument("--args", default="{}")
    dbt = sub.add_parser("dbt")
    dbt.add_argument("operation", choices=["summary", "node", "upstream", "downstream", "lineage", "impact", "tests", "failed-tests"])
    dbt.add_argument("node", nargs="?")
    dbt.add_argument("--project", default=_default_project())
    dbt.add_argument("--depth", type=int)
    airflow = sub.add_parser("airflow")
    airflow.add_argument("operation", choices=[
        "inventory", "dag", "tasks", "dependencies", "graph", "assets", "bundles",
        "connections", "pools", "capacity", "backfill-plan", "retry-analysis",
        "root-cause", "upgrade", "security", "xcom", "quality", "runtime", "doctor", "health",
    ])
    airflow.add_argument("dag_id", nargs="?")
    airflow.add_argument("--project", default=_default_project())
    airflow.add_argument("--args", default="{}", help="JSON arguments for advanced Airflow analysis")
    platform = sub.add_parser("platform")
    platform.add_argument("operation", choices=["discover", "inventory", "health", "graph", "lineage", "impact"])
    platform.add_argument("node", nargs="?")
    platform.add_argument("--project", default=_default_project())
    platform.add_argument("--depth", type=int)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("operation", choices=["row-count", "primary-keys", "aggregate", "nulls", "duplicates", "freshness"])
    reconcile.add_argument("--source-value", type=float)
    reconcile.add_argument("--target-value", type=float)
    reconcile.add_argument("--source-keys", default="[]")
    reconcile.add_argument("--target-keys", default="[]")
    reconcile.add_argument("--absolute-tolerance", type=float, default=0)
    reconcile.add_argument("--percentage-tolerance", type=float, default=0)
    reconcile.add_argument("--source-timestamp")
    reconcile.add_argument("--target-timestamp")
    reconcile.add_argument("--tolerance-seconds", type=float, default=0)
    for domain, operations in DOMAIN_CLI_TOOLS.items():
        domain_parser = sub.add_parser(domain)
        domain_parser.add_argument("operation", choices=sorted(operations))
        domain_parser.add_argument("--args", default="{}", help="JSON arguments passed to the deterministic tool")
        domain_parser.add_argument("--builder", action="store_true", help="invoke in Builder mode")
        domain_parser.add_argument("--admin", action="store_true", help="invoke in Admin mode through the same policy engine")
        domain_parser.add_argument("--environment", choices=[item.value for item in Environment], default=Environment.DEV.value)
        domain_parser.add_argument("--approved", action="store_true", help="explicitly approve tools that require approval")
        domain_parser.add_argument("--dry-run", action="store_true")

    plan = sub.add_parser("plan-migration")
    plan.add_argument("--source", required=True, choices=["sqlserver"])
    plan.add_argument("--target", required=True, choices=["snowflake"])
    plan.add_argument("--ddl", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--sql", required=True)
    approve = sub.add_parser("approve")
    approve.add_argument("--db", default="ade.db")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--by", required=True)
    approve.add_argument("--scope", default="production_mutation")
    execute = sub.add_parser("execute")
    execute.add_argument("--db", default="ade.db")
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--sql", required=True)
    execute.add_argument("--platform", required=True)
    execute.add_argument("--dry-run", action="store_true")
    return parser


def _reconcile(args: argparse.Namespace) -> dict:
    op = args.operation
    if op == "row-count":
        return _invoke("reconcile_row_count", {"source_value": args.source_value, "target_value": args.target_value, "absolute_tolerance": args.absolute_tolerance, "percentage_tolerance": args.percentage_tolerance})
    if op == "primary-keys":
        return _invoke("reconcile_primary_keys", {"source_keys": json.loads(args.source_keys), "target_keys": json.loads(args.target_keys)})
    if op == "aggregate":
        return _invoke("reconcile_aggregate", {"source_value": args.source_value, "target_value": args.target_value, "absolute_tolerance": args.absolute_tolerance, "percentage_tolerance": args.percentage_tolerance})
    if op == "nulls":
        return _invoke("reconcile_nulls", {"source_nulls": args.source_value, "target_nulls": args.target_value, "absolute_tolerance": args.absolute_tolerance, "percentage_tolerance": args.percentage_tolerance})
    if op == "duplicates":
        return _invoke("reconcile_duplicates", {"source_duplicates": args.source_value, "target_duplicates": args.target_value, "absolute_tolerance": args.absolute_tolerance, "percentage_tolerance": args.percentage_tolerance})
    return _invoke("reconcile_freshness", {"source_timestamp": args.source_timestamp, "target_timestamp": args.target_timestamp, "tolerance_seconds": args.tolerance_seconds})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "discover":
            if args.dbt_project:
                adapter = LocalDbtProjectAdapter(args.dbt_project)
                payload = {"project": adapter.project_metadata()}
                if args.manifest:
                    manifest = adapter.load_manifest(args.manifest)
                    payload.update({"models": adapter.list_models(manifest), "sources": adapter.list_sources(manifest), "tests": adapter.list_tests(manifest)})
            else:
                payload = _invoke("platform_discover", {"project": args.project or "."})
        elif args.command == "doctor":
            payload = _invoke("doctor", {"project": args.project})
        elif args.command == "tool":
            payload = _invoke(args.name, json.loads(args.args))
        elif args.command == "dbt":
            mapping = {"summary": "dbt_manifest_summary", "node": "dbt_node", "upstream": "dbt_upstream", "downstream": "dbt_downstream", "lineage": "dbt_lineage", "impact": "dbt_impact", "tests": "dbt_tests_for_node", "failed-tests": "dbt_failed_tests"}
            params = {"project": args.project}
            if args.node:
                params["node"] = args.node
            if args.depth is not None:
                params["depth"] = args.depth
            payload = _invoke(mapping[args.operation], params)
        elif args.command == "airflow":
            mapping = {
                "inventory": "airflow_inventory", "dag": "airflow_dag_details",
                "tasks": "airflow_task_graph", "dependencies": "airflow_dependencies",
                "graph": "airflow_graph", "assets": "airflow_asset_inventory",
                "bundles": "airflow_bundle_inventory", "connections": "airflow_connections_used",
                "pools": "airflow_pool_health", "capacity": "airflow_capacity_plan",
                "backfill-plan": "airflow_backfill_plan", "retry-analysis": "airflow_retry_analysis",
                "root-cause": "airflow_root_cause", "upgrade": "airflow_upgrade_analysis",
                "security": "airflow_secret_risk", "xcom": "airflow_xcom_analysis",
                "quality": "airflow_quality_scan", "runtime": "airflow_runtime_readiness",
                "doctor": "airflow_doctor", "health": "airflow_health",
            }
            params = {"project": args.project, **json.loads(args.args)}
            if args.dag_id:
                params["dag_id"] = args.dag_id
            payload = _invoke(mapping[args.operation], params)
        elif args.command == "platform":
            mapping = {"discover": "platform_discover", "inventory": "platform_inventory", "health": "platform_health", "graph": "platform_graph", "lineage": "platform_lineage", "impact": "platform_impact"}
            params = {"project": args.project}
            if args.node:
                params["node"] = args.node
            if args.depth is not None:
                params["depth"] = args.depth
            payload = _invoke(mapping[args.operation], params)
        elif args.command == "reconcile":
            payload = _reconcile(args)
        elif args.command in DOMAIN_CLI_TOOLS:
            tool_name = DOMAIN_CLI_TOOLS[args.command][args.operation]
            payload = _invoke(
                tool_name,
                json.loads(args.args),
                actor_mode=ActorMode.ADMIN if getattr(args, "admin", False) else ActorMode.BUILDER if args.builder else ActorMode.ANALYST,
                environment=Environment(args.environment),
                approved=bool(args.approved),
                dry_run=bool(args.dry_run),
            )
        elif args.command == "plan-migration":
            payload = asdict(plan_sqlserver_to_snowflake(Path(args.ddl).read_text()))
        elif args.command == "verify":
            payload = asdict(analyze_sql(Path(args.sql).read_text()))
        elif args.command == "approve":
            repo = _repo(args.db)
            record = ApprovalRecord(args.run_id, args.by, args.scope)
            repo.save_approval(record)
            payload = asdict(record)
        else:
            raise SystemExit("execution remains available only through a governed platform adapter")
        if args.command == "discover" and not args.json_output and isinstance(payload, dict) and "git" in payload:
            print(render_discovery(payload))
        else:
            print(json.dumps(payload, indent=2, default=str))
        return 0
    except (KeyError, ValueError, PermissionError, FileNotFoundError, json.JSONDecodeError) as exc:
        error = safe_error(exc)
        print(json.dumps({"status": "ERROR", "error": error["message"], **error}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
