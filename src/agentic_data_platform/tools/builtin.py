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


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _warehouse_status(_: dict[str, Any]) -> dict[str, Any]:
    definitions = [
        ("Snowflake", True, _module_available("snowflake"), all(os.getenv(k) for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")), False),
        ("PostgreSQL", False, _module_available("psycopg"), bool(os.getenv("POSTGRES_HOST")), True),
        ("Oracle", False, _module_available("oracledb"), bool(os.getenv("ORACLE_HOST")), True),
        ("DuckDB", False, _module_available("duckdb"), True, True),
        ("BigQuery", True, _module_available("google.cloud"), bool(os.getenv("GOOGLE_CLOUD_PROJECT")), False),
        ("Redshift", False, _module_available("psycopg"), bool(os.getenv("REDSHIFT_HOST")), False),
        ("Databricks", True, _module_available("databricks"), bool(os.getenv("DATABRICKS_HOST")), False),
    ]
    adapters = []
    for name, adapter, driver, configured, simulation in definitions:
        live = bool(adapter and driver and configured)
        adapters.append({
            "name": name,
            "adapter_available": adapter,
            "driver_installed": driver,
            "credentials_configured": configured,
            "live_connectivity": "AVAILABLE_TO_CHECK" if live else "SKIP",
            "simulation_available": simulation,
            "status": "PASS" if live else "WARN" if adapter or simulation else "PARTIAL",
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
    add("sql_review", Capability.VERIFY, lambda a: review_sql(a["sql"], a.get("dialect")), "Review SQL with deterministic AST safety and performance rules.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("sql_lineage", Capability.DISCOVER, lambda a: sql_lineage(a["sql"], a.get("dialect")), "Calculate first-version table and column SQL lineage.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("sql_column_lineage", Capability.DISCOVER, lambda a: column_lineage(a["sql"], a.get("dialect")), "Map projected columns to source columns.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("column_upstream", Capability.DISCOVER, lambda a: column_upstream(a["sql"], a["column"], a.get("dialect")), "Find SQL column upstream lineage.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
    add("column_downstream", Capability.DISCOVER, lambda a: column_downstream(a["sql"], a["column"], a.get("dialect")), "Find SQL column downstream projections.", platforms=frozenset({Platform.LOCAL, Platform.SNOWFLAKE, Platform.BIGQUERY, Platform.REDSHIFT, Platform.SPARK}))
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
