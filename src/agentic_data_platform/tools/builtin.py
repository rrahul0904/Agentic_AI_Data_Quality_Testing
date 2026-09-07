"""Registration of deterministic platform tools shared by CLI, API and agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.models import Capability, Platform, Risk
from agentic_data_platform.migration.shiftforge_adapter import ShiftForgeAdapter
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.platform.discovery import PlatformDiscovery
from agentic_data_platform.platform.doctor import run_doctor
from agentic_data_platform.platform.graph import PlatformAssetGraph
from agentic_data_platform.quality.reconciliation import (
    reconcile_aggregate, reconcile_duplicates, reconcile_freshness, reconcile_nulls,
    reconcile_primary_keys, reconcile_row_count,
)
from agentic_data_platform.sql.intelligence import column_downstream, column_lineage, column_upstream, review_sql, sql_lineage
from agentic_data_platform.metadata.index import MetadataIndex
from .registry import ToolDefinition, ToolRegistry
from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph


def _target(args: dict[str, Any]) -> Path:
    return Path(args.get("project") or args.get("project_path") or args.get("target_dir") or ".").expanduser().resolve()


def _dbt(args: dict[str, Any]) -> DbtManifestGraph:
    target = Path(args.get("target_dir") or (_target(args) / "dbt" / "target")).expanduser().resolve()
    return DbtManifestGraph(DbtArtifacts.load(target))


def _depth(args: dict[str, Any]) -> int | None:
    return int(args["depth"]) if args.get("depth") is not None else None


def _dbt_handler(method: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        graph = _dbt(args)
        value = getattr(graph, method)(args.get("node") or args.get("reference"), _depth(args)) if method in {"upstream", "downstream", "lineage", "impact"} else getattr(graph, method)(args.get("node") or args.get("reference"))
        return value if isinstance(value, dict) else {"items": value}
    return handler


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    read = Risk.READ_ONLY
    local = frozenset({Platform.LOCAL, Platform.DBT, Platform.SNOWFLAKE, Platform.SPARK})

    def add(name: str, capability: Capability, handler: Callable[[dict[str, Any]], dict[str, Any]], description: str, *, platforms: frozenset[Platform] = local, schema: dict[str, Any] | None = None, risk: Risk = read) -> None:
        registry.register(ToolDefinition(
            name=name, capability=capability, risk=risk, supported_platforms=platforms, handler=handler,
            description=description, input_schema=schema or {"type": "object"}, output_schema={"type": "object"},
        ))

    add("platform_discover", Capability.DISCOVER, lambda a: PlatformDiscovery(_target(a)).discover(), "Discover data-platform components and deterministic counts.")
    add("platform_inventory", Capability.DISCOVER, lambda a: PlatformDiscovery(_target(a)).inventory(), "Inventory dbt, Airflow, sources, Snowflake static objects and integrations.")
    add("platform_health", Capability.VERIFY, lambda a: PlatformDiscovery(_target(a)).health(), "Report static platform health and honest external skips.")
    add("doctor", Capability.DISCOVER, lambda a: run_doctor(_target(a)), "Check local development dependencies and optional integrations.")

    for name, method, description in (
        ("dbt_manifest_summary", "summary", "Summarize dbt artifacts and resource counts."),
        ("dbt_node", "node", "Describe one dbt node."),
        ("dbt_upstream", "upstream", "Traverse dbt upstream dependencies."),
        ("dbt_downstream", "downstream", "Traverse dbt downstream dependencies."),
        ("dbt_lineage", "lineage", "Return deterministic dbt lineage."),
        ("dbt_impact", "impact", "Calculate dbt downstream impact and affected tests/marts."),
        ("dbt_tests_for_node", "tests_for_node", "List tests protecting a dbt node."),
        ("dbt_failed_tests", "failed_tests", "Return failed dbt test results."),
    ):
        if method == "summary":
            handler = lambda a: _dbt(a).summary()
        elif method == "failed_tests":
            handler = lambda a: {"items": _dbt(a).failed_tests()}
        else:
            handler = _dbt_handler(method)
        add(name, Capability.DBT if name.startswith("dbt_") else Capability.DISCOVER, handler, description)

    def airflow(a: dict[str, Any]) -> AirflowProject:
        return AirflowProject.scan(_target(a))
    add("airflow_inventory", Capability.DISCOVER, lambda a: airflow(a).summary(), "Inventory Airflow DAGs and static dependencies.")
    add("airflow_dag_details", Capability.DISCOVER, lambda a: airflow(a).details(a["dag_id"]), "Describe one Airflow DAG.")
    add("airflow_task_graph", Capability.DISCOVER, lambda a: airflow(a).task_graph(a["dag_id"]), "Return an Airflow DAG task graph.")
    add("airflow_dependencies", Capability.DISCOVER, lambda a: airflow(a).dependencies(a["dag_id"]), "Return Airflow DAG dependencies.")
    add("airflow_connections_used", Capability.DISCOVER, lambda a: {"connections": airflow(a).connections_used(a.get("dag_id"))}, "List Airflow connection IDs.")
    add("airflow_health", Capability.VERIFY, lambda a: airflow(a).health(), "Report static Airflow health.")

    add("reconcile_row_count", Capability.VERIFY, lambda a: reconcile_row_count(a["source_value"], a["target_value"], absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare source and target row counts.")
    add("reconcile_primary_keys", Capability.VERIFY, lambda a: reconcile_primary_keys(a["source_keys"], a["target_keys"]), "Compare source and target primary-key sets.")
    add("reconcile_duplicates", Capability.VERIFY, lambda a: reconcile_duplicates(a["source_duplicates"], a["target_duplicates"], absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare duplicate counts.")
    add("reconcile_nulls", Capability.VERIFY, lambda a: reconcile_nulls(a["source_nulls"], a["target_nulls"], absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare null counts.")
    add("reconcile_freshness", Capability.VERIFY, lambda a: reconcile_freshness(a["source_timestamp"], a["target_timestamp"], tolerance_seconds=a.get("tolerance_seconds", 0)), "Compare source and target freshness.")
    add("reconcile_aggregate", Capability.VERIFY, lambda a: reconcile_aggregate(a["source_value"], a["target_value"], aggregate=a.get("aggregate", "sum"), absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare aggregate values.")

    add("platform_graph", Capability.DISCOVER, lambda a: PlatformAssetGraph.build(_target(a)).snapshot(), "Build the cross-system asset graph.")
    add("platform_lineage", Capability.DISCOVER, lambda a: PlatformAssetGraph.build(_target(a)).lineage(a["node"], depth=_depth(a)), "Return cross-system asset lineage.")
    add("platform_impact", Capability.DISCOVER, lambda a: PlatformAssetGraph.build(_target(a)).impact(a["node"], depth=_depth(a)), "Calculate cross-system asset impact.")
    add("sql_review", Capability.VERIFY, lambda a: review_sql(a["sql"], a.get("dialect")), "Review SQL with deterministic AST safety and performance rules.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("sql_lineage", Capability.DISCOVER, lambda a: sql_lineage(a["sql"], a.get("dialect")), "Calculate first-version table and column SQL lineage.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("sql_column_lineage", Capability.DISCOVER, lambda a: column_lineage(a["sql"], a.get("dialect")), "Map projected columns to source columns.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("column_upstream", Capability.DISCOVER, lambda a: column_upstream(a["sql"], a["column"], a.get("dialect")), "Find SQL column upstream lineage.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("column_downstream", Capability.DISCOVER, lambda a: column_downstream(a["sql"], a["column"], a.get("dialect")), "Find SQL column downstream projections.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("metadata_search", Capability.DISCOVER, lambda a: {"assets": MetadataIndex(a.get("database", ":memory:")).search_assets(a.get("query", ""), kind=a.get("kind"))}, "Search the local schema-aware metadata index.", platforms=frozenset({Platform.LOCAL}))
    add("metadata_column_search", Capability.DISCOVER, lambda a: {"columns": MetadataIndex(a.get("database", ":memory:")).search_columns(a.get("query", ""), pii_only=a.get("pii_only", False))}, "Search indexed columns and PII flags.", platforms=frozenset({Platform.LOCAL}))

    shiftforge_root = _target({"project": Path(__file__).resolve().parents[3] / "shiftforge"})
    if (shiftforge_root / "src" / "shiftforge").is_dir():
        adapter = ShiftForgeAdapter(shiftforge_root)
        add("migration_scan", Capability.MIGRATE, lambda a: adapter.scan(a["project"]), "Scan a ShiftForge dbt project.", platforms=frozenset({Platform.LOCAL}))
        add("migration_inventory", Capability.MIGRATE, lambda a: adapter.inventory(a["project"]), "Return structured ShiftForge inventory.", platforms=frozenset({Platform.LOCAL}))
        add("migration_convert_model", Capability.MIGRATE, lambda a: adapter.convert_model(a["sql"], a.get("model_name", "model.sql"), a.get("hints")), "Convert one model in dry-run mode.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
        add("migration_convert_project", Capability.MIGRATE, lambda a: adapter.convert_project(a["project"], hints=a.get("hints")), "Convert a project in dry-run mode.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
        add("migration_validate", Capability.VERIFY, lambda a: adapter.validate(a["project"], a["converted"]), "Validate an isolated ShiftForge output tree.", platforms=frozenset({Platform.LOCAL}))
        add("migration_plan", Capability.PLAN, lambda a: {"inventory": adapter.inventory(a["project"]), "source": a.get("source", "bigquery"), "target": a.get("target", "redshift")}, "Create a structured migration plan without writing files.", platforms=frozenset({Platform.LOCAL}))
        add("migration_show_findings", Capability.MIGRATE, lambda a: adapter.findings(a["project"]), "Show structured ShiftForge conversion findings.", platforms=frozenset({Platform.LOCAL}))
        add("migration_show_blockers", Capability.MIGRATE, lambda a: adapter.blockers(a["project"]), "Show ShiftForge blockers requiring human review.", platforms=frozenset({Platform.LOCAL}))
        add("migration_compile", Capability.VERIFY, lambda a: adapter.validate(a["project"], a["converted"]), "Compile and validate an isolated migration result.", platforms=frozenset({Platform.LOCAL}))
        add("migration_test", Capability.VERIFY, lambda a: adapter.validate(a["project"], a["converted"]), "Run deterministic migration validation.", platforms=frozenset({Platform.LOCAL}))

    return registry
