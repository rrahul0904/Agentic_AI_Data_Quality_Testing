from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agentic_data_platform.dbt.adapter import LocalDbtProjectAdapter
from agentic_data_platform.migration.sqlserver_snowflake import plan_sqlserver_to_snowflake
from agentic_data_platform.models import ActorMode, ApprovalRecord, Environment, ToolRequest
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository
from agentic_data_platform.sql.engine import analyze_sql
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def _repo(path: str) -> SQLiteControlPlaneRepository:
    repo = SQLiteControlPlaneRepository(path)
    repo.initialize()
    return repo


def _default_project() -> str:
    cwd = Path.cwd()
    if (cwd / "hospitality-snowflake-data-platform").is_dir():
        return str(cwd / "hospitality-snowflake-data-platform")
    return str(cwd)


def _invoke(name: str, args: dict, *, actor_mode: ActorMode = ActorMode.ANALYST, dry_run: bool = False) -> dict:
    registry = build_tool_registry()
    definition = registry.describe(name)
    request = ToolRequest(name, name, Environment.DEV, definition.risk, args=args)
    return registry.invoke(ToolInvocation(request, run_id=f"cli-{name}", dry_run=dry_run, actor_mode=actor_mode))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-data-platform", description="Governed agentic data-engineering control plane")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    discover = sub.add_parser("discover")
    discover.add_argument("project", nargs="?", default=None)
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
    airflow.add_argument("operation", choices=["inventory", "details", "task-graph", "dependencies", "connections", "health"])
    airflow.add_argument("dag_id", nargs="?")
    airflow.add_argument("--project", default=_default_project())
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
            if args.project:
                payload = _invoke("platform_discover", {"project": args.project})
            else:
                if not args.dbt_project:
                    raise SystemExit("discover requires a project path or --dbt-project")
                adapter = LocalDbtProjectAdapter(args.dbt_project)
                payload = {"project": adapter.project_metadata()}
                if args.manifest:
                    manifest = adapter.load_manifest(args.manifest)
                    payload.update({"models": adapter.list_models(manifest), "sources": adapter.list_sources(manifest), "tests": adapter.list_tests(manifest)})
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
            mapping = {"inventory": "airflow_inventory", "details": "airflow_dag_details", "task-graph": "airflow_task_graph", "dependencies": "airflow_dependencies", "connections": "airflow_connections_used", "health": "airflow_health"}
            params = {"project": args.project}
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
        print(json.dumps(payload, indent=2, default=str))
        return 0
    except (KeyError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
