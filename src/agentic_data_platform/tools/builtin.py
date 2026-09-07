"""Registration of deterministic platform tools shared by CLI, API and agents."""

from __future__ import annotations

import importlib.util
import os
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
from agentic_data_platform.quality.data_diff import (
    aggregate_diff as data_diff_aggregate_impl,
    data_diff_report as data_diff_report_impl,
    duckdb_demo_diff,
    hash_diff as data_diff_hash_impl,
    key_diff as data_diff_keys_impl,
    row_count_diff as data_diff_row_count_impl,
    row_diff as data_diff_rows_impl,
    schema_diff as data_diff_schema_impl,
)
from agentic_data_platform.dbt.advanced import (
    compiled_sql_review as dbt_compiled_sql_review_impl,
    failed_models as dbt_failed_models_impl,
    incremental_analysis as dbt_incremental_analysis_impl,
    leaf_model_candidates as dbt_leaf_candidates_impl,
    macro_analysis as dbt_macro_analysis_impl,
    snapshot_analysis as dbt_snapshot_analysis_impl,
    source_freshness_configuration as dbt_source_freshness_impl,
    state_compare as dbt_state_compare_impl,
)
from agentic_data_platform.platform.airflow_ops import (
    backfill_analysis as airflow_backfill_analysis_impl,
    connection_analysis as airflow_connection_analysis_impl,
    failure_lab as airflow_failure_lab_impl,
    pipeline_health as airflow_pipeline_health_impl,
    retry_analysis as airflow_retry_analysis_impl,
    root_cause_from_error as airflow_root_cause_impl,
    runtime_readiness as airflow_runtime_readiness_impl,
    schedule_analysis as airflow_schedule_analysis_impl,
)
from agentic_data_platform.platform.root_cause import (
    asset_health as asset_health_impl,
    overall_pipeline_health as overall_pipeline_health_impl,
    platform_root_cause as platform_root_cause_impl,
)
from agentic_data_platform.remediation.proposals import (
    propose_airflow_retry as propose_airflow_retry_impl,
    propose_dbt_tests as propose_dbt_tests_impl,
    propose_quality_rule as propose_quality_rule_impl,
    propose_sql_repair as propose_sql_repair_impl,
)
from agentic_data_platform.quality.store import SQLiteQualityStore
from agentic_data_platform.sql.intelligence import (
    column_downstream, column_lineage, column_upstream, review_sql, sql_lineage,
)
from agentic_data_platform.sql.parity import (
    analyze_sql as sql_analyze_impl,
    autocomplete_sql as sql_autocomplete_impl,
    classify_sql as sql_classify_impl,
    diff_sql as sql_diff_impl,
    execute_sql as sql_execute_impl,
    explain_sql as sql_explain_impl,
    fingerprint_sql as sql_fingerprint_impl,
    fix_sql as sql_fix_impl,
    format_sql as sql_format_impl,
    optimize_sql as sql_optimize_impl,
    rewrite_sql as sql_rewrite_impl,
    translate_sql as sql_translate_impl,
)
from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args
from agentic_data_platform.metadata.index import MetadataIndex
from agentic_data_platform.metadata.service import MetadataService
from agentic_data_platform.connections.store import ConnectionStore
from agentic_data_platform.lineage.dbt import DbtColumnGraph
from agentic_data_platform.lineage.engine import (
    analyze_column_lineage as production_column_lineage,
    column_downstream as production_column_downstream,
    column_upstream as production_column_upstream,
)
from .registry import ToolDefinition, ToolRegistry
from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph


def _target(args: dict[str, Any]) -> Path:
    return Path(args.get("project") or args.get("project_path") or args.get("target_dir") or ".").expanduser().resolve()


def _dbt(args: dict[str, Any]) -> DbtManifestGraph:
    target = Path(args.get("target_dir") or (_target(args) / "dbt" / "target")).expanduser().resolve()
    return DbtManifestGraph(DbtArtifacts.load(target))


def _depth(args: dict[str, Any]) -> int | None:
    return int(args["depth"]) if args.get("depth") is not None else None


def _column_graph(args: dict[str, Any], key: str = "target_dir") -> DbtColumnGraph:
    raw = args.get(key)
    if raw:
        target = Path(raw).expanduser().resolve()
    else:
        target = (_target(args) / "dbt" / "target").resolve()
    return DbtColumnGraph.load(target, dialect=args.get("dialect", "snowflake"))


def _dbt_handler(method: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        graph = _dbt(args)
        value = (
            getattr(graph, method)(args.get("node") or args.get("reference"), _depth(args))
            if method in {"upstream", "downstream", "lineage", "impact"}
            else getattr(graph, method)(args.get("node") or args.get("reference"))
        )
        return value if isinstance(value, dict) else {"items": value}
    return handler


def _quality(args: dict[str, Any]) -> SQLiteQualityStore:
    store = SQLiteQualityStore(args.get("database", ":memory:"))
    store.initialize()
    return store


def _connection_store(args: dict[str, Any]) -> ConnectionStore:
    path = args.get("connection_database") or (_target(args) / ".ade" / "connections.db")
    return ConnectionStore(path)


def _metadata_service(args: dict[str, Any]) -> MetadataService:
    path = args.get("metadata_database") or (_target(args) / ".ade" / "metadata.db")
    return MetadataService(path)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _warehouse_status(_: dict[str, Any]) -> dict[str, Any]:
    definitions = [
        ("Snowflake", "snowflake", True, _module_available("snowflake"), all(os.getenv(k) for k in ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD")), False),
        ("BigQuery", "bigquery", True, _module_available("google.cloud"), bool(os.getenv("ADE_BIGQUERY_PROJECT")), False),
        ("Databricks", "databricks", True, _module_available("databricks"), all(os.getenv(k) for k in ("ADE_DATABRICKS_HOST", "ADE_DATABRICKS_TOKEN", "ADE_DATABRICKS_HTTP_PATH")), False),
        ("PostgreSQL", "postgres", True, _module_available("psycopg"), bool(os.getenv("ADE_POSTGRES_DSN")), False),
        ("Redshift", "redshift", True, _module_available("psycopg"), bool(os.getenv("ADE_REDSHIFT_DSN")), False),
        ("Oracle", "oracle", True, _module_available("oracledb"), all(os.getenv(k) for k in ("ADE_ORACLE_USER", "ADE_ORACLE_PASSWORD", "ADE_ORACLE_DSN")), False),
        ("MySQL", "mysql", True, _module_available("pymysql"), all(os.getenv(k) for k in ("ADE_MYSQL_HOST", "ADE_MYSQL_USER", "ADE_MYSQL_PASSWORD", "ADE_MYSQL_DATABASE")), False),
        ("SQL Server / Fabric", "sqlserver", True, _module_available("pyodbc"), bool(os.getenv("ADE_SQLSERVER_CONNECTION_STRING")), False),
        ("DuckDB", "duckdb", True, _module_available("duckdb"), True, True),
        ("SQLite", "sqlite", True, True, True, True),
        ("ClickHouse", "clickhouse", True, _module_available("clickhouse_connect"), bool(os.getenv("ADE_CLICKHOUSE_HOST")), False),
        ("Trino", "trino", True, _module_available("trino"), all(os.getenv(k) for k in ("ADE_TRINO_HOST", "ADE_TRINO_USER", "ADE_TRINO_CATALOG")), False),
    ]
    adapters = []
    for name, platform, adapter, driver, configured, simulation in definitions:
        live = bool(adapter and driver and configured)
        adapters.append({
            "name": name,
            "platform": platform,
            "adapter_available": adapter,
            "driver_installed": driver,
            "credentials_configured": configured,
            "live_connectivity": "AVAILABLE_TO_CHECK" if live else "SKIP_EXTERNAL",
            "simulation_available": simulation,
            "status": "PASS" if live or simulation else "UNCONFIGURED" if adapter else "UNSUPPORTED",
        })
    return {"adapters": adapters, "mode": "LOCAL_SIMULATION"}

def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    read = Risk.READ_ONLY
    local = frozenset({Platform.LOCAL, Platform.DBT, Platform.SNOWFLAKE, Platform.SPARK})

    def add(
        name: str,
        capability: Capability,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        description: str,
        *,
        platforms: frozenset[Platform] = local,
        schema: dict[str, Any] | None = None,
        risk: Risk = read,
    ) -> None:
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

    def dbt_test_coverage(a: dict[str, Any]) -> dict[str, Any]:
        graph = _dbt(a)
        models = sorted(
            (node_id, node) for node_id, node in graph.nodes.items() if node.get("resource_type") == "model"
        )
        tested, untested = [], []
        for node_id, node in models:
            target = tested if graph.tests_for_node(node_id) else untested
            target.append(node.get("name") or node_id)
        total = len(models)
        return {
            "models": total,
            "tested_models": tested,
            "untested_models": untested,
            "tested_count": len(tested),
            "untested_count": len(untested),
            "coverage_pct": round((len(tested) / total * 100), 2) if total else 0.0,
        }

    def dbt_documentation_gaps(a: dict[str, Any]) -> dict[str, Any]:
        graph = _dbt(a)
        missing_models: list[str] = []
        missing_columns: list[dict[str, Any]] = []
        for node_id, node in graph.nodes.items():
            if node.get("resource_type") != "model":
                continue
            model = node.get("name") or node_id
            if not str(node.get("description") or "").strip():
                missing_models.append(model)
            for column, metadata in (node.get("columns") or {}).items():
                if not str((metadata or {}).get("description") or "").strip():
                    missing_columns.append({"model": model, "column": column})
        return {
            "missing_model_descriptions": sorted(missing_models),
            "missing_column_descriptions": sorted(missing_columns, key=lambda item: (item["model"], item["column"])),
            "model_gap_count": len(missing_models),
            "column_gap_count": len(missing_columns),
        }

    add("dbt_test_coverage", Capability.DBT, dbt_test_coverage, "Calculate deterministic dbt model test coverage.")
    add("dbt_documentation_gaps", Capability.DBT, dbt_documentation_gaps, "Find dbt model and column documentation gaps.")

    def airflow(a: dict[str, Any]) -> AirflowProject:
        return AirflowProject.scan(_target(a))

    add("airflow_inventory", Capability.DISCOVER, lambda a: airflow(a).summary(), "Inventory Airflow DAGs and static dependencies.")
    add("airflow_dag_details", Capability.DISCOVER, lambda a: airflow(a).details(a["dag_id"]), "Describe one Airflow DAG.")
    add("airflow_task_graph", Capability.DISCOVER, lambda a: airflow(a).task_graph(a["dag_id"]), "Return an Airflow DAG task graph.")
    add("airflow_dependencies", Capability.DISCOVER, lambda a: airflow(a).dependencies(a["dag_id"]), "Return Airflow DAG dependencies.")
    add("airflow_connections_used", Capability.DISCOVER, lambda a: {"connections": airflow(a).connections_used(a.get("dag_id"))}, "List Airflow connection IDs.")
    add("airflow_health", Capability.VERIFY, lambda a: airflow(a).health(), "Report static Airflow health.")
    add("airflow_failure_summary", Capability.VERIFY, lambda a: airflow(a).failure_summary(), "Return honest static/runtime Airflow failure evidence.")

    add("reconcile_row_count", Capability.VERIFY, lambda a: reconcile_row_count(a["source_value"], a["target_value"], absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare source and target row counts.")
    add("reconcile_primary_keys", Capability.VERIFY, lambda a: reconcile_primary_keys(a["source_keys"], a["target_keys"]), "Compare source and target primary-key sets.")
    add("reconcile_duplicates", Capability.VERIFY, lambda a: reconcile_duplicates(a["source_duplicates"], a["target_duplicates"], absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare duplicate counts.")
    add("reconcile_nulls", Capability.VERIFY, lambda a: reconcile_nulls(a["source_nulls"], a["target_nulls"], absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare null counts.")
    add("reconcile_freshness", Capability.VERIFY, lambda a: reconcile_freshness(a["source_timestamp"], a["target_timestamp"], tolerance_seconds=a.get("tolerance_seconds", 0)), "Compare source and target freshness.")
    add("reconcile_aggregate", Capability.VERIFY, lambda a: reconcile_aggregate(a["source_value"], a["target_value"], aggregate=a.get("aggregate", "sum"), absolute_tolerance=a.get("absolute_tolerance", 0), percentage_tolerance=a.get("percentage_tolerance", 0)), "Compare aggregate values.")

    add("quality_summary", Capability.VERIFY, lambda a: _quality(a).summary(), "Summarize persisted local quality and reconciliation evidence.", platforms=frozenset({Platform.LOCAL}))
    add("quality_recent", Capability.VERIFY, lambda a: {"items": _quality(a).recent_results(int(a.get("limit", 50)))}, "Return recent local data-quality evidence.", platforms=frozenset({Platform.LOCAL}))
    add("reconciliation_history", Capability.VERIFY, lambda a: {"items": _quality(a).recent_reconciliations(int(a.get("limit", 50)))}, "Return persisted source-target reconciliation evidence.", platforms=frozenset({Platform.LOCAL}))

    add("platform_graph", Capability.DISCOVER, lambda a: PlatformAssetGraph.build(_target(a)).snapshot(), "Build the cross-system asset graph.")
    add("platform_lineage", Capability.DISCOVER, lambda a: PlatformAssetGraph.build(_target(a)).lineage(a["node"], depth=_depth(a)), "Return cross-system asset lineage.")
    add("platform_impact", Capability.DISCOVER, lambda a: PlatformAssetGraph.build(_target(a)).impact(a["node"], depth=_depth(a)), "Calculate cross-system asset impact.")
    sql_platforms = frozenset({
        Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK,
        Platform.DATABRICKS, Platform.POSTGRES, Platform.ORACLE, Platform.DUCKDB, Platform.SQLSERVER,
        Platform.MYSQL, Platform.SQLITE, Platform.CLICKHOUSE, Platform.TRINO,
    })

    def sql_execute_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            connector = connector_from_args(a)
        except ExternalConnectionUnavailable as exc:
            return {"status": "SKIP_EXTERNAL", "platform": a.get("platform", "duckdb"), "reason": str(exc)}
        return sql_execute_impl(
            connector,
            a["sql"],
            a.get("dialect") or a.get("platform"),
            row_limit=int(a.get("row_limit", 1000)),
        )

    def sql_explain_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            connector = connector_from_args(a)
        except ExternalConnectionUnavailable as exc:
            return {"status": "SKIP_EXTERNAL", "platform": a.get("platform", "duckdb"), "reason": str(exc)}
        return sql_explain_impl(connector, a["sql"], a.get("dialect") or a.get("platform"))

    add("sql_analyze", Capability.VERIFY, lambda a: sql_analyze_impl(a["sql"], a.get("dialect"), a.get("schema_context")), "Analyze SQL with deterministic AST rules and structural fingerprint.", platforms=sql_platforms)
    add("sql_autocomplete", Capability.DISCOVER, lambda a: sql_autocomplete_impl(a.get("sql", ""), a.get("prefix", ""), a.get("schema_context"), limit=int(a.get("limit", 50))), "Return schema-aware SQL completion candidates.", platforms=sql_platforms)
    add("sql_classify", Capability.VERIFY, lambda a: sql_classify_impl(a["sql"], a.get("dialect")), "Classify multi-statement SQL as read/write and hard-deny destructive statements.", platforms=sql_platforms)
    add("sql_diff", Capability.VERIFY, lambda a: sql_diff_impl(a["original"], a["modified"], a.get("dialect"), int(a.get("context_lines", 3))), "Compare SQL structurally after AST canonicalization and emit unified diff.", platforms=sql_platforms)
    add("sql_execute", Capability.EXECUTE, sql_execute_handler, "Execute bounded read-only SQL through a configured connector.", platforms=sql_platforms)
    add("sql_explain", Capability.VERIFY, sql_explain_handler, "Run warehouse-native dry-run or EXPLAIN for read-only SQL.", platforms=sql_platforms)
    add("sql_fix", Capability.GENERATE, lambda a: sql_fix_impl(a["sql"], a.get("dialect"), a.get("schema_context")), "Apply deterministic safe SQL fixes without modifying files.", platforms=sql_platforms)
    add("sql_format", Capability.GENERATE, lambda a: sql_format_impl(a["sql"], a.get("dialect"), int(a.get("indent", 2))), "Format SQL deterministically with SQLGlot.", platforms=sql_platforms)
    add("sql_optimize", Capability.GENERATE, lambda a: sql_optimize_impl(a["sql"], a.get("dialect"), a.get("schema_context")), "Optimize SQL deterministically and return evidence-backed suggestions.", platforms=sql_platforms)
    add("sql_rewrite", Capability.GENERATE, lambda a: sql_rewrite_impl(a["sql"], a.get("dialect"), a.get("schema_context")), "Rewrite supported SQL anti-patterns with deterministic AST transforms.", platforms=sql_platforms)
    add("sql_translate", Capability.GENERATE, lambda a: sql_translate_impl(a["sql"], a["source_dialect"], a["target_dialect"]), "Translate SQL across major dialects with semantic-risk warnings.", platforms=sql_platforms)
    add("sql_fingerprint", Capability.VERIFY, lambda a: sql_fingerprint_impl(a["sql"], a.get("dialect")), "Return PII-safe structural SQL fingerprint.", platforms=sql_platforms)

    def column_lineage_handler(a: dict[str, Any]) -> dict[str, Any]:
        if a.get("sql"):
            return production_column_lineage(
                a["sql"],
                dialect=a.get("dialect"),
                schema=a.get("schema") or a.get("schema_context"),
                sources=a.get("sources"),
            )
        graph = _column_graph(a)
        if a.get("asset") and a.get("column"):
            return {
                "column": graph.resolve_column(a["asset"], a["column"]),
                "upstream": graph.upstream(a["asset"], a["column"], _depth(a))["upstream"],
                "downstream": graph.downstream(a["asset"], a["column"], _depth(a))["downstream"],
            }
        return graph.graph()

    def column_upstream_handler(a: dict[str, Any]) -> dict[str, Any]:
        if a.get("sql"):
            result = production_column_lineage(
                a["sql"],
                dialect=a.get("dialect"),
                schema=a.get("schema") or a.get("schema_context"),
                sources=a.get("sources"),
            )
            return production_column_upstream(result, a["column"])
        return _column_graph(a).upstream(a["asset"], a["column"], _depth(a))

    def column_downstream_handler(a: dict[str, Any]) -> dict[str, Any]:
        if a.get("sql"):
            result = production_column_lineage(
                a["sql"],
                dialect=a.get("dialect"),
                schema=a.get("schema") or a.get("schema_context"),
                sources=a.get("sources"),
            )
            return production_column_downstream(result, a["column"], a.get("table"))
        return _column_graph(a).downstream(a["asset"], a["column"], _depth(a))

    def column_diff_handler(a: dict[str, Any]) -> dict[str, Any]:
        current = _column_graph(a)
        previous = _column_graph(a, "previous_target_dir")
        return previous.diff(current)

    add("sql_review", Capability.VERIFY, lambda a: review_sql(a["sql"], a.get("dialect")), "Review SQL with deterministic AST safety and performance rules.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("sql_lineage", Capability.DISCOVER, lambda a: {**sql_lineage(a["sql"], a.get("dialect")), "production": production_column_lineage(a["sql"], dialect=a.get("dialect"), schema=a.get("schema") or a.get("schema_context"), sources=a.get("sources"))}, "Calculate table and production column SQL lineage.", platforms=sql_platforms)
    add("sql_column_lineage", Capability.DISCOVER, lambda a: production_column_lineage(a["sql"], dialect=a.get("dialect"), schema=a.get("schema") or a.get("schema_context"), sources=a.get("sources")), "Resolve scope-aware projected columns to source columns with ambiguity evidence.", platforms=sql_platforms)
    add("column_lineage", Capability.DISCOVER, column_lineage_handler, "Resolve SQL or dbt project-wide column lineage.", platforms=sql_platforms)
    add("column_upstream", Capability.DISCOVER, column_upstream_handler, "Traverse SQL or dbt project column upstream lineage.", platforms=sql_platforms)
    add("column_downstream", Capability.DISCOVER, column_downstream_handler, "Traverse SQL or dbt project column downstream lineage.", platforms=sql_platforms)
    add("column_impact", Capability.DISCOVER, lambda a: _column_graph(a).impact(a["asset"], a["column"], _depth(a)), "Calculate dbt downstream impact for a changed column.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("column_lineage_diff", Capability.VERIFY, column_diff_handler, "Compare project column-lineage edges across dbt artifact states.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("project_column_graph", Capability.DISCOVER, lambda a: _column_graph(a).graph(), "Build the dbt project-wide column graph from compiled SQL and catalog metadata.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("column_path", Capability.DISCOVER, lambda a: _column_graph(a).path(a["source_asset"], a["source_column"], a["target_asset"], a["target_column"]), "Find a concrete multi-hop project column path.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    def connection_test_handler(a: dict[str, Any]) -> dict[str, Any]:
        store = _connection_store(a)
        profile = store.resolve_config(a["name"])
        try:
            connector = connector_from_args({"platform": profile["platform"], "config": profile["config"]})
        except ExternalConnectionUnavailable as exc:
            return {"name": a["name"], "platform": profile["platform"], "status": "SKIP_EXTERNAL", "reason": str(exc)}
        return {"name": a["name"], **connector.health()}

    def schema_refresh_handler(a: dict[str, Any]) -> dict[str, Any]:
        store = _connection_store(a)
        profile = store.resolve_config(a["connection"])
        try:
            connector = connector_from_args({"platform": profile["platform"], "config": profile["config"]})
        except ExternalConnectionUnavailable as exc:
            return {"connection": a["connection"], "platform": profile["platform"], "status": "SKIP_EXTERNAL", "reason": str(exc)}
        return _metadata_service(a).refresh(
            a["connection"],
            connector,
            schemas=a.get("schemas"),
            max_objects=int(a.get("max_objects", 5000)),
        )

    def metadata_autocomplete_handler(a: dict[str, Any]) -> dict[str, Any]:
        context = _metadata_service(a).schema_context(
            connection_name=a.get("connection"),
            query=a.get("asset_query", ""),
            limit=int(a.get("asset_limit", 500)),
        )
        return sql_autocomplete_impl(
            a.get("sql", ""),
            a.get("prefix", ""),
            context,
            limit=int(a.get("limit", 50)),
        )

    add("connection_add", Capability.GENERATE, lambda a: _connection_store(a).add(a["name"], a["platform"], a.get("config"), source=a.get("source", "manual"), replace=bool(a.get("replace", False))), "Add a secret-safe local connection profile.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("connection_remove", Capability.GENERATE, lambda a: {"removed": _connection_store(a).remove(a["name"])}, "Remove a local connection profile.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("connection_list", Capability.DISCOVER, lambda a: {"connections": _connection_store(a).list(), "default": _connection_store(a).default()}, "List redacted connection profiles.", platforms=frozenset({Platform.LOCAL}))
    add("connection_show", Capability.DISCOVER, lambda a: _connection_store(a).show(a["name"]), "Show one redacted connection profile.", platforms=frozenset({Platform.LOCAL}))
    add("connection_test", Capability.VERIFY, connection_test_handler, "Test one configured connection without revealing secrets.", platforms=frozenset({Platform.LOCAL}))
    add("connection_default", Capability.GENERATE, lambda a: {"default": _connection_store(a).set_default(a.get("name"))}, "Set or clear the default connection.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("connection_discover", Capability.DISCOVER, lambda a: _connection_store(a).discover(dbt_profiles=a.get("dbt_profiles")), "Discover environment and dbt profile connections without persisting secrets.", platforms=frozenset({Platform.LOCAL}))

    add("schema_refresh", Capability.DISCOVER, schema_refresh_handler, "Refresh persistent warehouse metadata using a configured read-only connector.", platforms=frozenset({Platform.LOCAL}))
    add("schema_index", Capability.DISCOVER, schema_refresh_handler, "Index live warehouse metadata into the local metadata service.", platforms=frozenset({Platform.LOCAL}))
    add("schema_search", Capability.DISCOVER, lambda a: {"assets": _metadata_service(a).search_assets(a.get("query", ""), connection_name=a.get("connection"), limit=int(a.get("limit", 50)))}, "Search persistent warehouse objects.", platforms=frozenset({Platform.LOCAL}))
    add("schema_inspect", Capability.DISCOVER, lambda a: _metadata_service(a).inspect(a["connection"], a["schema"], a["object"]), "Inspect indexed object and column metadata.", platforms=frozenset({Platform.LOCAL}))
    add("schema_tags", Capability.DISCOVER, lambda a: {"tags": _metadata_service(a).tags(a["connection"], a["schema"], a["object"])}, "Return indexed object tags.", platforms=frozenset({Platform.LOCAL}))
    add("metadata_status", Capability.DISCOVER, lambda a: _metadata_service(a).status(a.get("connection")), "Report metadata index counts and latest refresh evidence.", platforms=frozenset({Platform.LOCAL}))
    add("autocomplete", Capability.DISCOVER, metadata_autocomplete_handler, "Return SQL autocomplete candidates from persistent live metadata.", platforms=frozenset({Platform.LOCAL}))

    add("metadata_search", Capability.DISCOVER, lambda a: {"assets": MetadataIndex(a.get("database", ":memory:")).search_assets(a.get("query", ""), kind=a.get("kind"))}, "Search the local schema-aware metadata index.", platforms=frozenset({Platform.LOCAL}))
    add("metadata_column_search", Capability.DISCOVER, lambda a: {"columns": MetadataIndex(a.get("database", ":memory:")).search_columns(a.get("query", ""), pii_only=a.get("pii_only", False))}, "Search indexed columns and PII flags.", platforms=frozenset({Platform.LOCAL}))
    add("warehouse_status", Capability.DISCOVER, _warehouse_status, "Report adapter, driver, credentials and local-simulation availability.", platforms=frozenset({Platform.LOCAL}))

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


    # Cross-warehouse/local data diff primitives.
    add("data_diff_schema", Capability.VERIFY, lambda a: data_diff_schema_impl(a["source_schema"], a["target_schema"]), "Compare source and target schemas.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_row_count", Capability.VERIFY, lambda a: data_diff_row_count_impl(a["source_count"], a["target_count"], tolerance=a.get("tolerance", 0)), "Compare source and target row counts for a data-diff run.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_keys", Capability.VERIFY, lambda a: data_diff_keys_impl(a["source_rows"], a["target_rows"], a["key_columns"]), "Compare keyed row membership and duplicate keys.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_hash", Capability.VERIFY, lambda a: data_diff_hash_impl(a["source_rows"], a["target_rows"], a["key_columns"]), "Compare canonical row hashes by business key.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_rows", Capability.VERIFY, lambda a: data_diff_rows_impl(a["source_rows"], a["target_rows"], a["key_columns"], compare_columns=a.get("compare_columns")), "Return missing, extra, changed and matching keyed rows.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_aggregate", Capability.VERIFY, lambda a: data_diff_aggregate_impl(a["source_rows"], a["target_rows"], a["column"], aggregate=a.get("aggregate", "sum"), tolerance=a.get("tolerance", 0)), "Compare deterministic source/target aggregates.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_report", Capability.VERIFY, lambda a: data_diff_report_impl(a["source_rows"], a["target_rows"], a["key_columns"], aggregate_columns=a.get("aggregate_columns", ())), "Build a composite schema/row/key/hash/aggregate data-diff report.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_duckdb_demo", Capability.VERIFY, lambda a: duckdb_demo_diff(), "Run a real in-memory DuckDB source-target data-diff fixture.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))

    # Advanced dbt artifact intelligence.
    add("dbt_incremental_analysis", Capability.DBT, lambda a: dbt_incremental_analysis_impl(_dbt(a)), "Analyze incremental model keys, strategies and schema-change risk.")
    add("dbt_snapshot_analysis", Capability.DBT, lambda a: dbt_snapshot_analysis_impl(_dbt(a)), "Analyze dbt snapshot SCD configuration.")
    add("dbt_macro_analysis", Capability.DBT, lambda a: dbt_macro_analysis_impl(_dbt(a)), "Inventory dbt macros and package ownership.")
    add("dbt_failed_models", Capability.DBT, lambda a: dbt_failed_models_impl(_dbt(a)), "Return failed dbt model executions from run_results.")
    add("dbt_source_freshness", Capability.DBT, lambda a: dbt_source_freshness_impl(_dbt(a)), "Inspect dbt source freshness configuration.")
    add("dbt_leaf_candidates", Capability.DBT, lambda a: dbt_leaf_candidates_impl(_dbt(a)), "Find non-mart leaf models that may be unused and require review.")
    add("dbt_compiled_sql_review", Capability.DBT, lambda a: dbt_compiled_sql_review_impl(_dbt(a), limit=int(a.get("limit", 100))), "Run deterministic SQL review across compiled dbt models.")
    add("dbt_state_compare", Capability.DBT, lambda a: dbt_state_compare_impl(_dbt(a), a["previous_manifest"]), "Compare current dbt state to a previous manifest and calculate impact.")

    # Airflow operational/static reliability intelligence.
    add("airflow_retry_analysis", Capability.VERIFY, lambda a: airflow_retry_analysis_impl(_target(a)), "Analyze Airflow retry-policy coverage.")
    add("airflow_schedule_analysis", Capability.VERIFY, lambda a: airflow_schedule_analysis_impl(_target(a)), "Analyze schedules and catchup policy.")
    add("airflow_backfill_analysis", Capability.PLAN, lambda a: airflow_backfill_analysis_impl(_target(a)), "Identify static backfill risk before execution.")
    add("airflow_connection_analysis", Capability.DISCOVER, lambda a: airflow_connection_analysis_impl(_target(a)), "Map Airflow connection IDs to dependent DAGs.")
    add("airflow_pipeline_health", Capability.VERIFY, lambda a: airflow_pipeline_health_impl(_target(a)), "Calculate deterministic static Airflow pipeline-health evidence.")
    add("airflow_runtime_readiness", Capability.VERIFY, lambda a: airflow_runtime_readiness_impl(_target(a)), "Report static readiness and honest runtime/log SKIPs.")
    add("airflow_root_cause", Capability.VERIFY, lambda a: airflow_root_cause_impl(a["error"], dag_id=a.get("dag_id"), task_id=a.get("task_id")), "Classify Airflow/task failure text into evidence-backed probable causes.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_failure_lab", Capability.VERIFY, lambda a: airflow_failure_lab_impl(), "Run the deterministic local Airflow permission-failure diagnosis fixture.", platforms=frozenset({Platform.LOCAL}))

    # Cross-system health and root-cause correlation.
    add("platform_root_cause", Capability.VERIFY, lambda a: platform_root_cause_impl(_target(a), a["database"], asset=a.get("asset")), "Correlate platform, Airflow, dbt and DQ evidence into probable root cause.", platforms=frozenset({Platform.LOCAL}))
    add("asset_health_score", Capability.VERIFY, lambda a: asset_health_impl(_target(a), a["database"], a["asset"]), "Score one asset using graph connectivity and persisted DQ evidence.", platforms=frozenset({Platform.LOCAL}))
    add("pipeline_health_score", Capability.VERIFY, lambda a: overall_pipeline_health_impl(_target(a), a["database"]), "Score pipeline health from Airflow and persisted quality evidence.", platforms=frozenset({Platform.LOCAL}))

    # Proposal-only remediation. These tools never write files.
    add("propose_dbt_tests", Capability.PLAN, lambda a: propose_dbt_tests_impl(_dbt(a), limit=int(a.get("limit", 25))), "Propose dbt tests for currently unprotected models without applying changes.")
    add("propose_sql_repair", Capability.PLAN, lambda a: propose_sql_repair_impl(a["sql"], a.get("dialect")), "Propose SQL remediations from deterministic findings without editing SQL.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("propose_airflow_retry", Capability.PLAN, lambda a: propose_airflow_retry_impl(_target(a), a["dag_id"]), "Propose safer Airflow retry configuration without modifying DAG code.")
    add("propose_quality_rule", Capability.PLAN, lambda a: propose_quality_rule_impl(a["asset"], a["check_type"], severity=a.get("severity", "ERROR")), "Propose a deterministic DQ rule without persisting it.", platforms=frozenset({Platform.LOCAL}))

    return registry
