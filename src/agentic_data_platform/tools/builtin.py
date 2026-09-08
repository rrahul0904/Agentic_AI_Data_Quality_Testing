"""Registration of deterministic platform tools shared by CLI, API and agents."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict
import os
from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.models import ActorMode, Capability, Environment, Platform, Risk, ToolRequest
from agentic_data_platform.migration.shiftforge_adapter import ShiftForgeAdapter
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.airflow_compat import AirflowAdapter, AirflowControlPlane
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
from agentic_data_platform.quality.warehouse_diff import WarehouseDiffEngine
from agentic_data_platform.sql.intelligence import (
    review_sql, sql_lineage,
)
from agentic_data_platform.sql.core_wrappers import (
    classify_schema_pii as core_classify_schema_pii,
    compare_sql as core_compare_sql,
    export_ddl as core_export_ddl,
    extract_sql_metadata as core_extract_sql_metadata,
    generate_sql_tests as core_generate_sql_tests,
    migration_safety as core_migration_safety,
    parse_dbt_project as core_parse_dbt_project,
    query_pii as core_query_pii,
    track_lineage as core_track_lineage,
)
from agentic_data_platform.sql.core_compat import (
    complete_sql as core_complete_sql,
    correct_sql as core_correct_sql,
    full_check as core_full_check,
    grade_sql as core_grade_sql,
    import_ddl as core_import_ddl,
    introspection_sql as core_introspection_sql,
    optimize_schema_context as core_optimize_schema_context,
    policy_check as core_policy_check,
    prune_schema as core_prune_schema,
    resolve_term as core_resolve_term,
    semantic_equivalence as core_semantic_equivalence,
    semantics as core_semantics,
    validate_sql as core_validate_sql,
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
from agentic_data_platform.training import (
    TrainingStore,
    import_markdown as training_import_markdown,
    list_entries as training_list_entries,
    remove_entry as training_remove_entry,
    save_entry as training_save_entry,
)
from agentic_data_platform.skills import SkillService
from agentic_data_platform.session import (
    SessionRuntime,
    SessionStore,
    cap_tool_result as session_cap_tool_result,
    retry_plan as session_retry_plan,
    session_overflow,
)
from agentic_data_platform.memory import MemoryStore
from agentic_data_platform.tracing import TraceStore
from agentic_data_platform.jobs import BackgroundJobEngine
from agentic_data_platform.review import (
    change_impact as review_change_impact,
    deliver_github_review,
    deliver_gitlab_review,
    deployment_risk as review_deployment_risk,
    recommended_tests as review_recommended_tests,
    review_dbt_changes,
)
from agentic_data_platform.mcp import (
    McpAuthStore,
    McpCatalog,
    McpClient,
    McpConfigStore,
    McpDiscovery,
    McpOAuthManager,
    configured_servers as mcp_configured_servers,
    merge_auth as mcp_merge_auth,
)
from agentic_data_platform.providers import (
    ModelCatalog,
    ModelRecord,
    ProviderRegistry,
    configured_auth as provider_configured_auth,
    family_vendor as provider_family_vendor,
    load_catalog_snapshot,
    normalize_messages as provider_normalize_messages,
    output_token_budget as provider_output_token_budget,
    provider_auth_status as provider_auth_status_impl,
)
from agentic_data_platform.governance import (
    classify_metadata_columns,
    excessive_privileges as governance_excessive_privileges,
    object_access as governance_object_access,
    pii_exposure as governance_pii_exposure,
    pii_policy_check as governance_pii_policy_check,
    propagate_pii as governance_propagate_pii,
    rbac_inventory as governance_rbac_inventory,
    sensitive_access_report as governance_sensitive_access_report,
)
from agentic_data_platform.finops import (
    cost_summary as finops_cost_summary,
    expensive_queries as finops_expensive_queries,
    full_finops_report,
    idle_resources as finops_idle_resources,
    query_errors as finops_query_errors,
    query_history as finops_query_history,
    query_patterns as finops_query_patterns,
    warehouse_advisor as finops_warehouse_advisor,
    warehouse_usage as finops_warehouse_usage,
)
from agentic_data_platform.connections.store import ConnectionStore
from agentic_data_platform.connections.docker_discovery import discover_docker_connections
from agentic_data_platform.connections.driver_install import (
    install_warehouse_driver,
    warehouse_driver_status,
)
from agentic_data_platform.connections.dbt_profiles import discover_dbt_profiles
from agentic_data_platform.connections.ssh_tunnel import SSHTunnelManager, TunnelConfig
from agentic_data_platform.onboarding import materialize_sample
from agentic_data_platform.teammates import TeammateManager
from agentic_data_platform.tools.feedback import submit_feedback
from agentic_data_platform.tools.parity_utils import (
    PostConnectSuggestions,
    normalize_error as parity_normalize_error,
    validate_table_name,
    validate_warehouse_name,
)
from agentic_data_platform.lineage.dbt import DbtColumnGraph
from agentic_data_platform.lineage.engine import (
    analyze_column_lineage as production_column_lineage,
    column_downstream as production_column_downstream,
    column_upstream as production_column_upstream,
)
from .registry import ToolDefinition, ToolInvocation, ToolRegistry
from agentic_data_platform.dbt.manifest_graph import DbtArtifacts, DbtManifestGraph
from agentic_data_platform.dbt.runtime import DbtRuntime
from agentic_data_platform.dbt.validators import run_validators as dbt_run_validators
from agentic_data_platform.dbt.generation import generate_schema_tests, generate_unit_tests


_JOB_ENGINES: dict[str, BackgroundJobEngine] = {}
_SUGGESTIONS = PostConnectSuggestions()
_SSH_TUNNELS = SSHTunnelManager()


def _target(args: dict[str, Any]) -> Path:
    return Path(args.get("project") or args.get("project_path") or args.get("target_dir") or ".").expanduser().resolve()


def _session_store(args: dict[str, Any]) -> SessionStore:
    path = args.get("session_database") or (_target(args) / ".ade" / "sessions.db")
    return SessionStore(path)


def _session_runtime(args: dict[str, Any]) -> SessionRuntime:
    training = TrainingStore(
        args.get("training_database")
        or (_target(args) / ".ade" / "training.db")
    )
    return SessionRuntime(_session_store(args), training=training)


def _memory_store(args: dict[str, Any]) -> MemoryStore:
    path = args.get("memory_database") or (_target(args) / ".ade" / "memory.db")
    return MemoryStore(path)


def _trace_store(args: dict[str, Any]) -> TraceStore:
    path = args.get("trace_database") or (_target(args) / ".ade" / "traces.db")
    return TraceStore(path)


def _job_engine(args: dict[str, Any]) -> BackgroundJobEngine:
    path = str(
        Path(
            args.get("job_database")
            or (_target(args) / ".ade" / "jobs.db")
        ).expanduser().resolve()
    )
    engine = _JOB_ENGINES.get(path)
    if engine is None:
        engine = BackgroundJobEngine(path, max_workers=int(args.get("max_workers", 4)))
        _JOB_ENGINES[path] = engine
    return engine


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


def _connector_profile(args: dict[str, Any], side: str):
    injected = args.get(f"_{side}_connector")
    if injected is not None:
        return injected
    connection_name = args.get(f"{side}_connection")
    if connection_name:
        profile = _connection_store(args).resolve_config(connection_name)
        return connector_from_args({"platform": profile["platform"], "config": profile["config"]})
    definition = args.get(side) or {}
    if not isinstance(definition, dict) or not definition.get("platform"):
        raise ValueError(f"{side} connector requires {side}_connection or a platform/config object")
    return connector_from_args(definition)


def _warehouse_diff_engine(args: dict[str, Any]) -> WarehouseDiffEngine:
    return WarehouseDiffEngine(_connector_profile(args, "source"), _connector_profile(args, "target"))


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
        ("MongoDB", "mongodb", True, _module_available("pymongo"), bool(os.getenv("ADE_MONGODB_URI")), False),
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
        supports_dry_run: bool = False,
        requires_approval: bool = False,
    ) -> None:
        registry.register(ToolDefinition(
            name=name, capability=capability, risk=risk, supported_platforms=platforms, handler=handler,
            description=description, input_schema=schema or {"type": "object"}, output_schema={"type": "object"},
            supports_dry_run=supports_dry_run, requires_approval=requires_approval,
        ))

    def tool_lookup_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            definition = registry.describe(a["tool_name"])
        except KeyError:
            return {
                "status": "NOT_FOUND",
                "tool_name": a.get("tool_name"),
                "available_tools": [item.name for item in registry.definitions()],
            }
        schema = definition.input_schema or {}
        required = set(schema.get("required") or ())
        parameters = []
        for name, field in (schema.get("properties") or {}).items():
            field = field if isinstance(field, dict) else {}
            parameters.append(
                {
                    "name": name,
                    "type": field.get("type", "unknown"),
                    "required": name in required,
                    "description": field.get("description", ""),
                }
            )
        return {
            "status": "PASS",
            "tool": {
                "name": definition.name,
                "description": definition.description,
                "capability": definition.capability.value,
                "risk": definition.risk.value,
                "enabled": definition.enabled,
                "platforms": sorted(item.value for item in definition.supported_platforms),
                "input_schema": schema,
                "output_schema": definition.output_schema,
                "parameters": parameters,
            },
        }

    add("sample_setup", Capability.GENERATE, lambda a: materialize_sample(home=a.get("home"), preferred_target_name=a.get("preferred_target_name", "agentic-data-sample-dbt"), allow_in_place_upgrade=bool(a.get("allow_in_place_upgrade", False)), install_alongside=bool(a.get("install_alongside", False))), "Materialize or safely reuse the shipped dbt + DuckDB starter sample.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("datamate_manager", Capability.EXECUTE, lambda a: TeammateManager(_target(a), database=a.get("teammate_database"), global_root=a.get("teammate_global_root")).execute(a["operation"], a), "Manage local AI teammates and their MCP integrations using the Datamate lifecycle operations.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("feedback_submit", Capability.EXECUTE, lambda a: submit_feedback(title=a["title"], category=a["category"], description=a["description"], include_context=bool(a.get("include_context", False)), repository=a.get("repository", "rrahul0904/Agentic_AI_Data_Quality_Testing"), session_id=a.get("session_id")), "Submit user feedback as a GitHub issue when gh is installed and authenticated.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

    add("tool_lookup", Capability.DISCOVER, tool_lookup_handler, "Look up a deterministic tool's full contract, risk and parameter schema.", platforms=frozenset({Platform.LOCAL}))
    add("input_validation", Capability.VERIFY, lambda a: {"status": "PASS" if not (validate_warehouse_name(a.get("warehouse")) or validate_table_name(a.get("table")) if "table" in a else validate_warehouse_name(a.get("warehouse"))) else "FAIL", "warehouse_error": validate_warehouse_name(a.get("warehouse")), "table_error": validate_table_name(a.get("table")) if "table" in a else None}, "Validate warehouse and table names before routing external operations.", platforms=frozenset({Platform.LOCAL}))
    add("response_normalization", Capability.VERIFY, lambda a: {"status": "PASS", "error": parity_normalize_error(a.get("error"))}, "Normalize external error envelopes without leaking arbitrary object details.", platforms=frozenset({Platform.LOCAL}))
    add("post_connect_suggestions", Capability.DISCOVER, lambda a: {"status": "PASS", "suggestions": _SUGGESTIONS.post_connect(warehouse_type=a.get("warehouse_type", "warehouse"), schema_indexed=bool(a.get("schema_indexed", False)), dbt_detected=bool(a.get("dbt_detected", False)), connection_count=int(a.get("connection_count", 1))), "progressive": _SUGGESTIONS.progressive(a.get("last_tool_used", "")) if a.get("last_tool_used") else None}, "Return contextual post-connect and progressive capability suggestions.", platforms=frozenset({Platform.LOCAL}))
    add("dbt_profiles", Capability.DISCOVER, lambda a: discover_dbt_profiles(path=a.get("path"), project_dir=a.get("project_dir") or a.get("project")), "Discover dbt profiles.yml warehouse outputs with credential redaction.", platforms=frozenset({Platform.LOCAL}))
    add("ssh_tunnel_start", Capability.EXECUTE, lambda a: _SSH_TUNNELS.start(a["name"], TunnelConfig(ssh_host=a["ssh_host"], ssh_user=a["ssh_user"], remote_host=a["remote_host"], remote_port=int(a["remote_port"]), ssh_port=int(a.get("ssh_port", 22)), local_port=int(a["local_port"]) if a.get("local_port") else None, identity_file=a.get("identity_file"))), "Start a managed SSH local-forward tunnel using key/agent authentication.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("ssh_tunnel_status", Capability.DISCOVER, lambda a: _SSH_TUNNELS.status(a["name"]), "Report managed SSH tunnel state.", platforms=frozenset({Platform.LOCAL}))
    add("ssh_tunnel_stop", Capability.EXECUTE, lambda a: _SSH_TUNNELS.stop(a["name"]), "Stop a managed SSH tunnel.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

    add("platform_discover", Capability.DISCOVER, lambda a: PlatformDiscovery(_target(a)).discover(), "Discover data-platform components and deterministic counts.")
    add("platform_inventory", Capability.DISCOVER, lambda a: PlatformDiscovery(_target(a)).inventory(), "Inventory dbt, Airflow, sources, Snowflake static objects and integrations.")
    add("platform_health", Capability.VERIFY, lambda a: PlatformDiscovery(_target(a)).health(), "Report static platform health and honest external skips.")
    def provider_catalog_handler(a: dict[str, Any]) -> ModelCatalog:
        if a.get("catalog_path"):
            return load_catalog_snapshot(a["catalog_path"])
        payload = a.get("catalog")
        if isinstance(payload, dict):
            return ModelCatalog.from_models_dev(payload)
        return ModelCatalog()

    add("provider_list", Capability.DISCOVER, lambda a: {"providers": ProviderRegistry().specs()}, "List provider protocols, configuration state and capabilities.", platforms=frozenset({Platform.LOCAL}))
    add("provider_auth", Capability.DISCOVER, lambda a: provider_configured_auth(ProviderRegistry()), "Report provider authentication configuration without revealing credentials.", platforms=frozenset({Platform.LOCAL}))
    add("provider_auth_status", Capability.DISCOVER, lambda a: provider_auth_status_impl(a["provider"], ProviderRegistry()), "Report one provider authentication state.", platforms=frozenset({Platform.LOCAL}))
    add("provider_family", Capability.DISCOVER, lambda a: {"family": a.get("family"), "vendor": provider_family_vendor(a.get("family"))}, "Map a concrete model family to its vendor bucket.", platforms=frozenset({Platform.LOCAL}))
    add("provider_models", Capability.DISCOVER, lambda a: {"models": [asdict(item) for item in provider_catalog_handler(a).list(provider_id=a.get("provider"), status=a.get("status"), supports_tools=a.get("supports_tools"))]}, "List structurally validated provider models.", platforms=frozenset({Platform.LOCAL}))
    add("provider_model_search", Capability.DISCOVER, lambda a: {"models": [asdict(item) for item in provider_catalog_handler(a).find(a.get("query", ""), provider_id=a.get("provider"), include_deprecated=bool(a.get("include_deprecated", False)))]}, "Search validated provider models.", platforms=frozenset({Platform.LOCAL}))
    add("provider_model_status", Capability.DISCOVER, lambda a: {"status": provider_catalog_handler(a).status(a["provider"], a["model"])}, "Return model lifecycle status.", platforms=frozenset({Platform.LOCAL}))
    add("provider_model_snapshot", Capability.DISCOVER, lambda a: provider_catalog_handler(a).snapshot(), "Return normalized provider-model catalog snapshot.", platforms=frozenset({Platform.LOCAL}))
    add("provider_transform", Capability.GENERATE, lambda a: {"messages": provider_normalize_messages(a["messages"], provider=a["provider"], model_id=a.get("model", ""))}, "Apply provider-specific safe message transforms.", platforms=frozenset({Platform.LOCAL}))
    add("provider_output_budget", Capability.VERIFY, lambda a: provider_output_token_budget(provider_catalog_handler(a).get(a["provider"], a["model"]), a["messages"], requested=a.get("requested"), floor=int(a.get("floor", 1024))), "Calculate and enforce output-token budget within model context limits.", platforms=frozenset({Platform.LOCAL}))


    def mcp_config_path(a: dict[str, Any]) -> Path:
        return Path(
            a.get("mcp_config")
            or (_target(a) / ".altimate-code" / "altimate-code.json")
        ).expanduser().resolve()

    def mcp_auth_store(a: dict[str, Any]) -> McpAuthStore:
        return McpAuthStore(
            a.get("mcp_auth_database")
            or (_target(a) / ".ade" / "mcp-auth.db")
        )

    def mcp_oauth_manager(a: dict[str, Any]) -> McpOAuthManager:
        return McpOAuthManager(
            a.get("mcp_oauth_database")
            or (_target(a) / ".ade" / "mcp-oauth.db")
        )

    def mcp_client_handler(a: dict[str, Any]) -> McpClient:
        configs = McpConfigStore.load(mcp_config_path(a))
        name = a["name"]
        if name not in configs:
            raise KeyError(f"MCP server not found: {name}")
        config = configs[name]
        headers = mcp_auth_store(a).headers(name)
        client = McpClient(mcp_merge_auth(config, headers))
        status = client.connect()
        if status.status != "connected":
            client.close()
            raise RuntimeError(status.error or status.status)
        return client

    def mcp_external(a: dict[str, Any], operation: str) -> dict[str, Any]:
        try:
            client = mcp_client_handler(a)
        except Exception as exc:
            return {"status": "SKIP_EXTERNAL", "name": a.get("name"), "reason": str(exc)}
        try:
            if operation == "tools":
                return {"status": "PASS", "name": a["name"], "tools": client.tools()}
            if operation == "resources":
                return {"status": "PASS", "name": a["name"], "resources": client.resources()}
            if operation == "call":
                return {
                    "status": "PASS",
                    "name": a["name"],
                    "result": client.call_tool(a["tool"], a.get("arguments") or {}),
                }
            return {"status": "PASS", "name": a["name"]}
        finally:
            client.close()

    add("mcp_list", Capability.DISCOVER, lambda a: mcp_configured_servers(mcp_config_path(a)), "List configured MCP servers and unresolved environment references.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_add", Capability.GENERATE, lambda a: {"path": str(McpConfigStore.add(mcp_config_path(a), a["name"], a["config"]))}, "Persist an MCP server configuration.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_remove", Capability.GENERATE, lambda a: {"removed": McpConfigStore.remove(mcp_config_path(a), a["name"])}, "Remove a persisted MCP server.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_enable", Capability.GENERATE, lambda a: {"path": str(McpConfigStore.set_enabled(mcp_config_path(a), a["name"], True)), "enabled": True}, "Enable an MCP server.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_disable", Capability.GENERATE, lambda a: {"path": str(McpConfigStore.set_enabled(mcp_config_path(a), a["name"], False)), "enabled": False}, "Disable an MCP server.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_discover", Capability.DISCOVER, lambda a: McpDiscovery.discover(_target(a)), "Discover MCP configuration from common coding-agent clients.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_catalog", Capability.DISCOVER, lambda a: {"entries": McpCatalog.builtin().list()}, "List installable MCP catalog entries.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_install", Capability.GENERATE, lambda a: {"path": str(McpCatalog.builtin().install(a["catalog_name"], mcp_config_path(a), server_name=a.get("name")))}, "Install a catalog MCP server into project config.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_auth_set_env", Capability.GENERATE, lambda a: mcp_auth_store(a).set_env_token(a["name"], a["env"], method=a.get("method", "bearer"), metadata=a.get("metadata")), "Configure MCP authentication by environment-variable reference only.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_auth_status", Capability.DISCOVER, lambda a: mcp_auth_store(a).status(a["name"]), "Report MCP auth state without exposing tokens.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_status", Capability.VERIFY, lambda a: mcp_external(a, "status"), "Connect to an MCP server and report honest status.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_tools", Capability.DISCOVER, lambda a: mcp_external(a, "tools"), "Discover tools exposed by one MCP server.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_resources", Capability.DISCOVER, lambda a: mcp_external(a, "resources"), "Discover resources exposed by one MCP server.", platforms=frozenset({Platform.LOCAL}))
    add("mcp_call", Capability.EXECUTE, lambda a: mcp_external(a, "call"), "Call an MCP tool through the governed runtime.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_oauth_begin", Capability.GENERATE, lambda a: mcp_oauth_manager(a).begin(a["name"], authorize_url=a["authorize_url"], client_id=a["client_id"], redirect_uri=a["redirect_uri"], token_url=a.get("token_url"), scope=a.get("scope")), "Begin MCP OAuth authorization with PKCE.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("mcp_oauth_callback", Capability.GENERATE, lambda a: mcp_oauth_manager(a).callback(state=a["state"], code=a.get("code"), error=a.get("error")), "Validate and consume an MCP OAuth callback state.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)


    def session_model(a: dict[str, Any]) -> ModelRecord:
        return ModelRecord(
            provider_id=str(a.get("provider") or "local"),
            model_id=str(a.get("model") or "unknown"),
            name=str(a.get("model_name") or a.get("model") or "Unknown"),
            context_window=int(a["context_window"]) if a.get("context_window") else None,
            max_output_tokens=int(a["max_output_tokens"]) if a.get("max_output_tokens") else None,
            supports_tools=bool(a.get("supports_tools", True)),
            supports_reasoning=bool(a.get("supports_reasoning", False)),
        )

    add("session_create", Capability.GENERATE, lambda a: _session_runtime(a).create(title=a.get("title"), provider=a.get("provider"), model=a.get("model"), metadata=a.get("metadata")), "Create a persistent governed agent session.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_list", Capability.DISCOVER, lambda a: {"sessions": _session_store(a).list(limit=int(a.get("limit", 100)))}, "List persistent agent sessions.", platforms=frozenset({Platform.LOCAL}))
    add("session_show", Capability.DISCOVER, lambda a: _session_runtime(a).project(a["session_id"]), "Project session status, messages, todos, reminders and state.", platforms=frozenset({Platform.LOCAL}))
    add("session_message_add", Capability.GENERATE, lambda a: _session_runtime(a).append(a["session_id"], a["role"], a.get("content"), error=a.get("error"), metadata=a.get("metadata")), "Append a typed persistent session message.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_messages", Capability.DISCOVER, lambda a: {"messages": _session_store(a).messages(a["session_id"], limit=a.get("limit"))}, "List ordered messages for a session.", platforms=frozenset({Platform.LOCAL}))
    add("session_status", Capability.DISCOVER, lambda a: _session_store(a).get(a["session_id"]), "Read governed session status.", platforms=frozenset({Platform.LOCAL}))
    add("session_status_set", Capability.GENERATE, lambda a: _session_store(a).set_status(a["session_id"], a["status"]), "Update governed session status.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_todo_add", Capability.GENERATE, lambda a: _session_store(a).add_todo(a["session_id"], a["text"], priority=int(a.get("priority", 0))), "Add a persistent session todo.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_todo_update", Capability.GENERATE, lambda a: _session_store(a).update_todo(a["todo_id"], a["status"]), "Update persistent session todo state.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_todos", Capability.DISCOVER, lambda a: {"todos": _session_store(a).todos(a["session_id"])}, "List session todos.", platforms=frozenset({Platform.LOCAL}))
    add("session_reminder_add", Capability.GENERATE, lambda a: _session_store(a).add_reminder(a["session_id"], a["text"], a.get("trigger") or {}), "Add a persistent session reminder.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_reminders", Capability.DISCOVER, lambda a: {"reminders": _session_store(a).reminders(a["session_id"], undelivered_only=bool(a.get("undelivered_only", False)))}, "List session reminders.", platforms=frozenset({Platform.LOCAL}))
    add("session_reminder_deliver", Capability.GENERATE, lambda a: _session_store(a).mark_reminder_delivered(a["reminder_id"]), "Mark a session reminder delivered.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_revert", Capability.GENERATE, lambda a: _session_store(a).revert_last(a["session_id"], roles=tuple(a.get("roles") or ("assistant", "tool"))), "Revert the latest assistant/tool session message.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_state", Capability.DISCOVER, lambda a: _session_store(a).state(a["session_id"]), "Read persistent session run state.", platforms=frozenset({Platform.LOCAL}))
    add("session_state_patch", Capability.GENERATE, lambda a: _session_store(a).patch_state(a["session_id"], a["patch"]), "Patch persistent session run state.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_prompt", Capability.DISCOVER, lambda a: _session_runtime(a).prompt(a["session_id"], project_root=a.get("project") or a.get("project_root"), query=a.get("query"), system=a.get("system"), include_training=bool(a.get("include_training", True)), training_limit=int(a.get("training_limit", 6)), training_chars=int(a.get("training_chars", 10000))), "Build the bounded instruction/training/reminder session prompt.", platforms=frozenset({Platform.LOCAL}))
    add("session_compact", Capability.GENERATE, lambda a: _session_runtime(a).compact(a["session_id"], keep_recent=int(a.get("keep_recent", 8)), summary_chars=int(a.get("summary_chars", 8000))), "Compact older session messages into deterministic state summary.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_nudge", Capability.GENERATE, lambda a: _session_runtime(a).nudge(a["session_id"], threshold_assistant_messages=int(a.get("threshold_assistant_messages", 3))), "Detect tool-starved assistant loops and persist a deterministic nudge.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("session_termination", Capability.VERIFY, lambda a: _session_runtime(a).termination(a["session_id"], validator_context=a.get("validator_context"), require_todos_complete=bool(a.get("require_todos_complete", True))), "Run session termination gates across todos and validators.", platforms=frozenset({Platform.LOCAL}))
    add("session_retry_plan", Capability.PLAN, lambda a: session_retry_plan(int(a.get("attempt", 1)), error=a.get("error"), status_code=a.get("status_code"), max_attempts=int(a.get("max_attempts", 5)), base_seconds=float(a.get("base_seconds", 1.0)), max_seconds=float(a.get("max_seconds", 30.0))), "Classify retryability and bounded exponential backoff.", platforms=frozenset({Platform.LOCAL}))
    add("session_tool_result_cap", Capability.VERIFY, lambda a: session_cap_tool_result(a.get("value"), max_chars=int(a.get("max_chars", 20000))), "Cap oversized tool results while preserving head/tail evidence.", platforms=frozenset({Platform.LOCAL}))
    add("session_overflow", Capability.VERIFY, lambda a: session_overflow(session_model(a), a.get("messages") or (), requested_output_tokens=a.get("requested_output_tokens")), "Detect context-window overflow against normalized model limits.", platforms=frozenset({Platform.LOCAL}))

    add("memory_save", Capability.GENERATE, lambda a: {"memory_id": _memory_store(a).save_memory(a["content"], scope=a.get("scope", "project"), project_id=a.get("project_id"), tags=list(a.get("tags") or ()), citations=list(a.get("citations") or ()), expires_at=a.get("expires_at"))}, "Persist explicit project/global memory with provenance.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("memory_list", Capability.DISCOVER, lambda a: {"memories": _memory_store(a).list_memories(scope=a.get("scope"), project_id=a.get("project_id"), limit=int(a.get("limit", 200)))}, "List bounded non-expired memories.", platforms=frozenset({Platform.LOCAL}))
    add("memory_search", Capability.DISCOVER, lambda a: {"memories": _memory_store(a).search(a.get("query", ""), project_id=a.get("project_id"), limit=int(a.get("limit", 50)))}, "Search project/global memory deterministically.", platforms=frozenset({Platform.LOCAL}))
    add("memory_remove", Capability.GENERATE, lambda a: {"removed": _memory_store(a).remove_memory(a["memory_id"])}, "Remove one persisted memory.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

    add("trace_list", Capability.DISCOVER, lambda a: {"traces": _trace_store(a).traces(limit=int(a.get("limit", 100)))}, "List trace summaries with generation/tool/error counts.", platforms=frozenset({Platform.LOCAL}))
    add("trace_show", Capability.DISCOVER, lambda a: _trace_store(a).tree(a["trace_id"]) if not a.get("event_id") else _trace_store(a).show(a["event_id"]), "Show a trace event tree or one event.", platforms=frozenset({Platform.LOCAL}))
    add("trace_export", Capability.DISCOVER, lambda a: {"trace_id": a["trace_id"], "format": a.get("format", "json"), "content": _trace_store(a).export_html(a["trace_id"]) if a.get("format") == "html" else _trace_store(a).export_json(a["trace_id"])}, "Export trace evidence as JSON or standalone HTML.", platforms=frozenset({Platform.LOCAL}))
    add("trace_replay", Capability.DISCOVER, lambda a: _trace_store(a).replay(a["trace_id"]), "Reconstruct recorded trace timeline without re-executing side effects.", platforms=frozenset({Platform.LOCAL}))

    def job_submit_handler(a: dict[str, Any]) -> dict[str, Any]:
        tool_name = a["tool"]
        definition = registry.describe(tool_name)
        if definition.risk != Risk.READ_ONLY:
            raise PermissionError(
                f"generic background jobs refuse mutating tool: {tool_name}"
            )
        payload = dict(a.get("args") or {})
        if a.get("project") and not payload.get("project"):
            payload["project"] = a["project"]
        engine = _job_engine(a)

        def execute_job() -> dict[str, Any]:
            request = ToolRequest(
                tool=tool_name,
                operation=tool_name,
                environment=Environment.DEV,
                risk=definition.risk,
                args=payload,
            )
            return registry.invoke(
                ToolInvocation(
                    request,
                    run_id=f"job-{tool_name}",
                    actor_mode=ActorMode.ANALYST,
                )
            )

        job_id = engine.submit(f"tool:{tool_name}", execute_job)
        return {
            "job_id": job_id,
            "tool": tool_name,
            "status": "QUEUED",
        }

    add("job_submit", Capability.GENERATE, job_submit_handler, "Queue a read-only deterministic tool as a persistent background job.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("job_list", Capability.DISCOVER, lambda a: {"jobs": _job_engine(a).list(limit=int(a.get("limit", 100)))}, "List persistent background jobs.", platforms=frozenset({Platform.LOCAL}))
    add("job_show", Capability.DISCOVER, lambda a: _job_engine(a).get(a["job_id"]), "Show one background job.", platforms=frozenset({Platform.LOCAL}))
    add("job_cancel", Capability.GENERATE, lambda a: {"job_id": a["job_id"], "cancelled": _job_engine(a).cancel(a["job_id"])}, "Cancel a queued background job when cancellation is still possible.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

    def training_store(a: dict[str, Any]) -> TrainingStore:
        return TrainingStore(
            a.get("training_database")
            or (_target(a) / ".ade" / "training.db")
        )

    def skill_service(a: dict[str, Any]) -> SkillService:
        return SkillService(
            _target(a),
            state_path=a.get("skill_database")
            or (_target(a) / ".ade" / "skills.db"),
        )

    def skill_execute_handler(a: dict[str, Any]) -> dict[str, Any]:
        service = skill_service(a)
        available = {definition.name for definition in registry.definitions()}

        def invoke_inner(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
            definition = registry.describe(tool_name)
            request = ToolRequest(
                tool=tool_name,
                operation=tool_name,
                environment=Environment.DEV,
                risk=definition.risk,
                args=payload,
            )
            return registry.invoke(
                ToolInvocation(
                    request,
                    run_id=str(a.get("_run_id") or f"skill-{a['name']}"),
                    actor_mode=ActorMode.BUILDER,
                )
            )

        return service.execute(
            a["name"],
            available_tools=available,
            invoke=invoke_inner,
            args=a.get("args"),
            tool_args=a.get("tool_args"),
        )

    add("training_save", Capability.GENERATE, lambda a: training_save_entry(_memory_store(a), kind=a["kind"], name=a["name"], content=a["content"], scope=a.get("scope", "project"), project_id=a.get("project_id"), source=a.get("source"), citations=list(a.get("citations") or ())), "Save or update a named learned training entry with preserved application count.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("training_list", Capability.DISCOVER, lambda a: training_list_entries(_memory_store(a), kind=a.get("kind"), scope=a.get("scope", "all"), project_id=a.get("project_id")), "List learned training entries, counts, application usage and context budget.", platforms=frozenset({Platform.LOCAL}))
    add("training_remove", Capability.GENERATE, lambda a: training_remove_entry(_memory_store(a), kind=a["kind"], name=a["name"], scope=a.get("scope", "project"), project_id=a.get("project_id")), "Remove one named learned training entry.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("training_import", Capability.GENERATE, lambda a: training_import_markdown(_memory_store(a), a["file_path"], kind=a["kind"], scope=a.get("scope", "project"), project_id=a.get("project_id"), dry_run=bool(a.get("dry_run", True)), max_entries=int(a.get("max_entries", 20))), "Import named learned training entries from Markdown H2 sections with dry-run preview.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

    add("training_ingest", Capability.GENERATE, lambda a: training_store(a).ingest_project(_target(a), patterns=tuple(a.get("patterns") or ("AGENTS.md", "CLAUDE.md", "README.md", "docs/**/*.md", "specs/**/*.md", "models/**/*.sql", "models/**/*.yml", "models/**/*.yaml", "dbt_project.yml")), max_files=int(a.get("max_files", 2000)), max_bytes_per_file=int(a.get("max_bytes_per_file", 2000000))), "Index bounded project knowledge into the local training corpus.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("training_ingest_text", Capability.GENERATE, lambda a: training_store(a).ingest_text(a["source"], a["text"], source_type=a.get("source_type", "text"), metadata=a.get("metadata")), "Index explicit approved text into the local training corpus.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("training_search", Capability.DISCOVER, lambda a: {"results": training_store(a).search(a.get("query", ""), limit=int(a.get("limit", 10)))}, "Search local project training knowledge.", platforms=frozenset({Platform.LOCAL}))
    add("training_context", Capability.DISCOVER, lambda a: training_store(a).context(a.get("query", ""), limit=int(a.get("limit", 8)), max_chars=int(a.get("max_chars", 12000))), "Build bounded project context for agent injection.", platforms=frozenset({Platform.LOCAL}))
    add("training_status", Capability.DISCOVER, lambda a: training_store(a).status(), "Report local project training corpus status.", platforms=frozenset({Platform.LOCAL}))
    add("training_clear", Capability.GENERATE, lambda a: training_store(a).clear(), "Clear the local project training corpus.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

    def skill_install_handler(a: dict[str, Any]) -> dict[str, Any]:
        service = skill_service(a)
        if a.get("source"):
            return service.install_source(
                a["source"],
                scope=a.get("scope", "project"),
                name=a.get("name"),
                overwrite=bool(a.get("overwrite", False)),
            )
        return service.install(
            a["name"],
            overwrite=bool(a.get("overwrite", False)),
        )

    add("skill_catalog", Capability.DISCOVER, lambda a: {"skills": skill_service(a).catalog()}, "List the exact builtin parity skill catalog.", platforms=frozenset({Platform.LOCAL}))
    add("skill_install", Capability.GENERATE, skill_install_handler, "Install a builtin, local, or GitHub skill into the project/global skill roots.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_install_source", Capability.GENERATE, lambda a: skill_service(a).install_source(a["source"], scope=a.get("scope", "project"), name=a.get("name"), overwrite=bool(a.get("overwrite", False))), "Install skills from a safe local path or https://github.com source.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_create", Capability.GENERATE, lambda a: skill_service(a).create(a["name"], a.get("description", ""), a["body"], scope=a.get("scope", "project"), always_apply=bool(a.get("always_apply", False)), apply_paths=tuple(a.get("apply_paths") or ())), "Create a project/global SKILL.md with validated metadata.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_test", Capability.VERIFY, lambda a: skill_service(a).test(a["name"]), "Validate an installed skill file and metadata.", platforms=frozenset({Platform.LOCAL}))
    add("skill_install_all", Capability.GENERATE, lambda a: skill_service(a).install_all(overwrite=bool(a.get("overwrite", False))), "Install all builtin parity skills.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_list", Capability.DISCOVER, lambda a: {"skills": skill_service(a).list()}, "List installed project/global skills and state.", platforms=frozenset({Platform.LOCAL}))
    add("skill_show", Capability.DISCOVER, lambda a: skill_service(a).inspect(a["name"]), "Inspect one installed skill.", platforms=frozenset({Platform.LOCAL}))
    add("skill_enable", Capability.GENERATE, lambda a: skill_service(a).set_enabled(a["name"], True), "Enable an installed skill.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_disable", Capability.GENERATE, lambda a: skill_service(a).set_enabled(a["name"], False), "Disable an installed skill.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_remove", Capability.GENERATE, lambda a: skill_service(a).remove(a["name"]), "Remove an installed skill.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("skill_auto_load", Capability.DISCOVER, lambda a: {"skills": skill_service(a).auto_load()}, "Resolve deterministic skill auto-load rules for the project.", platforms=frozenset({Platform.LOCAL}))
    add("skill_plan", Capability.PLAN, lambda a: skill_service(a).plan(a["name"], {definition.name for definition in registry.definitions()}), "Plan an executable skill and report missing tool dependencies.", platforms=frozenset({Platform.LOCAL}))
    add("skill_execute", Capability.EXECUTE, skill_execute_handler, "Execute a skill as an ordered governed deterministic tool workflow.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

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

    def dbt_runtime(a: dict[str, Any]) -> DbtRuntime:
        project = Path(a.get("dbt_project") or (_target(a) / "dbt")).expanduser().resolve()
        profiles = a.get("profiles_dir")
        return DbtRuntime(
            project,
            profiles_dir=profiles,
            executable=a.get("dbt_executable", "dbt"),
            timeout=int(a.get("timeout", 1800)),
        )

    def dbt_execute(a: dict[str, Any], verb: str) -> dict[str, Any]:
        options = {
            "select": a.get("select"),
            "exclude": a.get("exclude"),
            "target": a.get("target"),
            "vars": a.get("vars"),
            "state": a.get("state"),
            "defer": bool(a.get("defer", False)),
            "timeout": int(a.get("timeout", 1800)),
        }
        if verb == "ls":
            options["output"] = a.get("output", "json")
        return dbt_runtime(a).execute(verb, **options)

    add("dbt_parse", Capability.DBT, lambda a: dbt_execute(a, "parse"), "Run governed dbt parse and capture artifacts.")
    add("dbt_ls", Capability.DBT, lambda a: dbt_execute(a, "ls"), "Run governed dbt ls with selector support.")
    add("dbt_compile", Capability.DBT, lambda a: dbt_execute(a, "compile"), "Compile selected dbt resources and capture artifacts.")
    add("dbt_run", Capability.DBT, lambda a: dbt_execute(a, "run"), "Run selected dbt models with structured artifact verification.", risk=Risk.MUTATING)
    add("dbt_test", Capability.DBT, lambda a: dbt_execute(a, "test"), "Execute selected dbt tests and verify run_results.")
    add("dbt_build", Capability.DBT, lambda a: dbt_execute(a, "build"), "Build selected dbt resources with artifact-level success verification.", risk=Risk.MUTATING)
    add("dbt_seed", Capability.DBT, lambda a: dbt_execute(a, "seed"), "Load dbt seeds through the governed runtime.", risk=Risk.MUTATING)
    add("dbt_snapshot", Capability.DBT, lambda a: dbt_execute(a, "snapshot"), "Execute dbt snapshots through the governed runtime.", risk=Risk.MUTATING)

    add(
        "dbt_validate",
        Capability.VERIFY,
        lambda a: dbt_run_validators(
            Path(a.get("dbt_project") or (_target(a) / "dbt")),
            dialect=a.get("dialect", "snowflake"),
            touched_models=a.get("touched_models", ()),
            session_start_epoch=a.get("session_start_epoch"),
            task_requires_build=bool(a.get("task_requires_build", False)),
        ),
        "Run all pinned deterministic dbt completion validators.",
    )
    add(
        "dbt_test_generate",
        Capability.GENERATE,
        lambda a: generate_schema_tests(
            _dbt(a).artifacts.manifest,
            a["model"],
            relationships=a.get("relationships"),
            accepted_values=a.get("accepted_values"),
        ),
        "Generate dbt schema-test YAML proposals from manifest metadata.",
    )
    add(
        "dbt_unit_test_gen",
        Capability.GENERATE,
        lambda a: generate_unit_tests(
            _dbt(a).artifacts.manifest,
            a["model"],
            dialect=a.get("dialect", "snowflake"),
            max_scenarios=int(a.get("max_scenarios", 3)),
        ),
        "Generate dbt 1.8+ unit-test YAML from compiled SQL, dependencies, types and lineage.",
    )

    def dbt_review_handler(a: dict[str, Any]) -> dict[str, Any]:
        previous_manifest = a.get("previous_manifest")
        if isinstance(previous_manifest, str):
            previous_manifest = __import__("json").loads(
                Path(previous_manifest).read_text()
            )
        return review_dbt_changes(
            a.get("dbt_project") or (_target(a) / "dbt"),
            target_dir=a.get("target_dir"),
            repository=a.get("repository") or _target(a),
            changed_files=a.get("changed_files"),
            base=a.get("base", "origin/main"),
            head=a.get("head", "HEAD"),
            previous_manifest=previous_manifest,
            dialect=a.get("dialect", "snowflake"),
        )

    add("dbt_pr_review", Capability.VERIFY, dbt_review_handler, "Run deterministic dbt PR review with validators, SQL findings, impact, tests and PII evidence.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("change_impact", Capability.VERIFY, lambda a: review_change_impact(dbt_review_handler(a)), "Calculate changed dbt asset downstream impact from signed review evidence.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("recommended_tests", Capability.PLAN, lambda a: review_recommended_tests(dbt_review_handler(a)), "Recommend dbt selectors and affected tests for changed assets.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("deployment_risk", Capability.VERIFY, lambda a: review_deployment_risk(dbt_review_handler(a)), "Calculate deterministic pre-merge deployment risk.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("github_pr_review", Capability.EXECUTE, lambda a: deliver_github_review(dbt_review_handler(a), repository=a["github_repository"], pull_number=int(a["pull_number"]), token_env=a.get("token_env", "GITHUB_TOKEN"), api_url=a.get("api_url", "https://api.github.com"), dry_run=bool(a.get("dry_run_delivery", False))), "Post a deterministic review verdict to a GitHub pull request.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("gitlab_mr_review", Capability.EXECUTE, lambda a: deliver_gitlab_review(dbt_review_handler(a), project=a["gitlab_project"], merge_request_iid=int(a["merge_request_iid"]), token_env=a.get("token_env", "GITLAB_TOKEN"), api_url=a.get("api_url", "https://gitlab.com/api/v4"), dry_run=bool(a.get("dry_run_delivery", False))), "Post a deterministic review verdict to a GitLab merge request.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

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

    def airflow_control(a: dict[str, Any]) -> AirflowControlPlane:
        return AirflowControlPlane(_target(a))

    def airflow_runtime(a: dict[str, Any], *, allow_mutation: bool = False) -> AirflowAdapter:
        return AirflowAdapter(
            a.get("airflow_url") or os.getenv("ADE_AIRFLOW_URL"),
            version=a.get("airflow_version") or os.getenv("ADE_AIRFLOW_VERSION"),
            token=a.get("airflow_token") or os.getenv("ADE_AIRFLOW_TOKEN"),
            username=a.get("airflow_username") or os.getenv("ADE_AIRFLOW_USERNAME"),
            password=a.get("airflow_password") or os.getenv("ADE_AIRFLOW_PASSWORD"),
            transport=a.get("_airflow_transport"),
            allow_mutation=allow_mutation,
        )

    add("airflow_graph", Capability.DISCOVER, lambda a, kind="graph": airflow_control(a).report(kind, a), "Airflow 2/3 airflow graph deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_static_dag_intelligence", Capability.DISCOVER, lambda a: airflow_control(a).report("static", a), "Expose full Airflow 2/3 static DAG semantics without importing DAG modules.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_dag_lineage", Capability.DISCOVER, lambda a, kind="graph": airflow_control(a).report(kind, a), "Airflow 2/3 airflow dag lineage deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_task_lineage", Capability.DISCOVER, lambda a, kind="graph": airflow_control(a).report(kind, a), "Airflow 2/3 airflow task lineage deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_lineage", Capability.DISCOVER, lambda a, kind="graph": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset lineage deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_cross_system_lineage", Capability.DISCOVER, lambda a, kind="graph": airflow_control(a).report(kind, a), "Airflow 2/3 airflow cross system lineage deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_inventory", Capability.DISCOVER, lambda a, kind="assets": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset inventory deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_dependencies", Capability.DISCOVER, lambda a, kind="assets": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset dependencies deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_producers", Capability.DISCOVER, lambda a, kind="assets": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset producers deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_consumers", Capability.DISCOVER, lambda a, kind="assets": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset consumers deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_events", Capability.DISCOVER, lambda a, kind="events": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset events deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_partition_analysis", Capability.VERIFY, lambda a, kind="assets": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset partition analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_event_schedule_analysis", Capability.VERIFY, lambda a, kind="events": airflow_control(a).report(kind, a), "Airflow 2/3 airflow event schedule analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_asset_watchers", Capability.DISCOVER, lambda a, kind="events": airflow_control(a).report(kind, a), "Airflow 2/3 airflow asset watchers deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_event_stalls", Capability.VERIFY, lambda a, kind="events": airflow_control(a).report(kind, a), "Airflow 2/3 airflow event stalls deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_dynamic_mapping_analysis", Capability.VERIFY, lambda a, kind="mapping": airflow_control(a).report(kind, a), "Airflow 2/3 airflow dynamic mapping analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_mapping_risk", Capability.VERIFY, lambda a, kind="mapping": airflow_control(a).report(kind, a), "Airflow 2/3 airflow mapping risk deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_mapping_cardinality", Capability.VERIFY, lambda a, kind="mapping": airflow_control(a).report(kind, a), "Airflow 2/3 airflow mapping cardinality deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_deferrable_analysis", Capability.VERIFY, lambda a, kind="deferrable": airflow_control(a).report(kind, a), "Airflow 2/3 airflow deferrable analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_triggerer_health", Capability.VERIFY, lambda a, kind="deferrable": airflow_control(a).report(kind, a), "Airflow 2/3 airflow triggerer health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_sensor_efficiency", Capability.VERIFY, lambda a, kind="deferrable": airflow_control(a).report(kind, a), "Airflow 2/3 airflow sensor efficiency deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_bundle_inventory", Capability.DISCOVER, lambda a, kind="bundles": airflow_control(a).report(kind, a), "Airflow 2/3 airflow bundle inventory deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_bundle_versions", Capability.DISCOVER, lambda a, kind="bundles": airflow_control(a).report(kind, a), "Airflow 2/3 airflow bundle versions deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_bundle_security", Capability.VERIFY, lambda a, kind="bundles": airflow_control(a).report(kind, a), "Airflow 2/3 airflow bundle security deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_bundle_drift", Capability.VERIFY, lambda a, kind="bundles": airflow_control(a).report(kind, a), "Airflow 2/3 airflow bundle drift deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_sdk_compatibility", Capability.VERIFY, lambda a, kind="sdk": airflow_control(a).report(kind, a), "Airflow 2/3 airflow sdk compatibility deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_upgrade_findings", Capability.VERIFY, lambda a, kind="upgrade": airflow_control(a).report(kind, a), "Airflow 2/3 airflow upgrade findings deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_import_errors", Capability.VERIFY, lambda a, kind="parse": airflow_control(a).report(kind, a), "Airflow 2/3 airflow import errors deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_parse_health", Capability.VERIFY, lambda a, kind="parse": airflow_control(a).report(kind, a), "Airflow 2/3 airflow parse health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_duplicate_dags", Capability.VERIFY, lambda a, kind="parse": airflow_control(a).report(kind, a), "Airflow 2/3 airflow duplicate dags deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_parse_performance", Capability.VERIFY, lambda a, kind="parse": airflow_control(a).report(kind, a), "Airflow 2/3 airflow parse performance deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_upgrade_analysis", Capability.VERIFY, lambda a, kind="upgrade": airflow_control(a).report(kind, a), "Airflow 2/3 airflow upgrade analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_failed_dags", Capability.VERIFY, lambda a, kind="parse": airflow_control(a).report(kind, a), "Airflow 2/3 airflow failed dags deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_failed_tasks", Capability.VERIFY, lambda a, kind="parse": airflow_control(a).report(kind, a), "Airflow 2/3 airflow failed tasks deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_duration_analysis", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow duration analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_queue_analysis", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow queue analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_pool_analysis", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow pool analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_scheduler_health", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow scheduler health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_dag_processor_health", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow dag processor health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_worker_health", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow worker health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_deadline_analysis", Capability.VERIFY, lambda a, kind="deadline": airflow_control(a).report(kind, a), "Airflow 2/3 airflow deadline analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_task_root_cause", Capability.VERIFY, lambda a, kind="root_cause": airflow_control(a).report(kind, a), "Airflow 2/3 airflow task root cause deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_pipeline_root_cause", Capability.VERIFY, lambda a, kind="root_cause": airflow_control(a).report(kind, a), "Airflow 2/3 airflow pipeline root cause deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_backfill_plan", Capability.PLAN, lambda a, kind="backfill": airflow_control(a).report(kind, a), "Airflow 2/3 airflow backfill plan deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_backfill_risk", Capability.VERIFY, lambda a, kind="backfill": airflow_control(a).report(kind, a), "Airflow 2/3 airflow backfill risk deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_backfill_dry_run", Capability.PLAN, lambda a, kind="backfill": airflow_control(a).report(kind, a), "Airflow 2/3 airflow backfill dry run deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_retry_policy_analysis", Capability.VERIFY, lambda a, kind="quality": airflow_control(a).report(kind, a), "Airflow 2/3 airflow retry policy analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_retry_storms", Capability.VERIFY, lambda a, kind="quality": airflow_control(a).report(kind, a), "Airflow 2/3 airflow retry storms deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_deadline_health", Capability.VERIFY, lambda a, kind="deadline": airflow_control(a).report(kind, a), "Airflow 2/3 airflow deadline health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_connection_impact", Capability.VERIFY, lambda a, kind="graph": airflow_control(a).report(kind, a), "Airflow 2/3 airflow connection impact deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_variables_used", Capability.DISCOVER, lambda a, kind="security": airflow_control(a).report(kind, a), "Airflow 2/3 airflow variables used deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_secret_risk", Capability.VERIFY, lambda a, kind="security": airflow_control(a).report(kind, a), "Airflow 2/3 airflow secret risk deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_xcom_analysis", Capability.VERIFY, lambda a, kind="xcom": airflow_control(a).report(kind, a), "Airflow 2/3 airflow xcom analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_xcom_risk", Capability.VERIFY, lambda a, kind="xcom": airflow_control(a).report(kind, a), "Airflow 2/3 airflow xcom risk deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_pool_health", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow pool health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_queue_health", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow queue health deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_concurrency_analysis", Capability.VERIFY, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow concurrency analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_capacity_plan", Capability.PLAN, lambda a, kind="capacity": airflow_control(a).report(kind, a), "Airflow 2/3 airflow capacity plan deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_executor_analysis", Capability.VERIFY, lambda a, kind="executor": airflow_control(a).report(kind, a), "Airflow 2/3 airflow executor analysis deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_log_summary", Capability.VERIFY, lambda a, kind="logs": airflow_control(a).report(kind, a), "Airflow 2/3 airflow log summary deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_log_errors", Capability.VERIFY, lambda a, kind="logs": airflow_control(a).report(kind, a), "Airflow 2/3 airflow log errors deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_log_root_cause", Capability.VERIFY, lambda a, kind="root_cause": airflow_control(a).report(kind, a), "Airflow 2/3 airflow log root cause deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_openlineage_status", Capability.VERIFY, lambda a, kind="openlineage": airflow_control(a).report(kind, a), "Airflow 2/3 airflow openlineage status deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_openlineage_events", Capability.DISCOVER, lambda a, kind="openlineage": airflow_control(a).report(kind, a), "Airflow 2/3 airflow openlineage events deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_openlineage_graph", Capability.DISCOVER, lambda a, kind="openlineage": airflow_control(a).report(kind, a), "Airflow 2/3 airflow openlineage graph deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_deployment_readiness", Capability.VERIFY, lambda a, kind="deployment": airflow_control(a).report(kind, a), "Airflow 2/3 airflow deployment readiness deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_doctor", Capability.VERIFY, lambda a, kind="doctor": airflow_control(a).report(kind, a), "Airflow 2/3 airflow doctor deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_quality_scan", Capability.VERIFY, lambda a, kind="quality": airflow_control(a).report(kind, a), "Airflow 2/3 airflow quality scan deterministic control-plane capability.", platforms=frozenset({Platform.LOCAL}))

    add("airflow_runtime_dags", Capability.DISCOVER, lambda a: airflow_runtime(a).dags(limit=int(a.get("limit", 100))), "List DAGs through the version-aware Airflow REST adapter.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_runtime_dag_runs", Capability.DISCOVER, lambda a: airflow_runtime(a).dag_runs(a["dag_id"], limit=int(a.get("limit", 100))), "List DAG runs through the Airflow REST adapter.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_runtime_task_instances", Capability.DISCOVER, lambda a: airflow_runtime(a).task_instances(a["dag_id"], a["run_id"]), "List task instances through the Airflow REST adapter.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_runtime_logs", Capability.DISCOVER, lambda a: airflow_runtime(a).logs(a["dag_id"], a["run_id"], a["task_id"], try_number=int(a.get("try_number", 1))), "Read bounded task logs through the Airflow REST adapter.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_runtime_assets", Capability.DISCOVER, lambda a: airflow_runtime(a).assets(), "List runtime Assets/Datasets via Airflow API.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_runtime_import_errors", Capability.DISCOVER, lambda a: airflow_runtime(a).import_errors(), "List runtime DAG import errors via Airflow API.", platforms=frozenset({Platform.LOCAL}))
    add("airflow_trigger", Capability.EXECUTE, lambda a: airflow_runtime(a, allow_mutation=True).trigger(a["dag_id"], conf=a.get("conf"), dry_run=bool(a.get("_dry_run"))), "Trigger an Airflow DAG only through governed Builder approval.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING, supports_dry_run=True, requires_approval=True)
    add("airflow_pause", Capability.EXECUTE, lambda a: airflow_runtime(a, allow_mutation=True).pause(a["dag_id"], dry_run=bool(a.get("_dry_run"))), "Pause an Airflow DAG only through governed Builder approval.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING, supports_dry_run=True, requires_approval=True)
    add("airflow_unpause", Capability.EXECUTE, lambda a: airflow_runtime(a, allow_mutation=True).unpause(a["dag_id"], dry_run=bool(a.get("_dry_run"))), "Unpause an Airflow DAG only through governed Builder approval.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING, supports_dry_run=True, requires_approval=True)
    add("airflow_clear", Capability.EXECUTE, lambda a: airflow_runtime(a, allow_mutation=True).clear(a["dag_id"], start_date=a.get("start_date"), end_date=a.get("end_date"), dry_run=bool(a.get("_dry_run"))), "Clear Airflow task instances only through governed Builder approval.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING, supports_dry_run=True, requires_approval=True)
    add("airflow_backfill_execute", Capability.EXECUTE, lambda a: airflow_runtime(a, allow_mutation=True).backfill(a["dag_id"], start_date=a["start_date"], end_date=a["end_date"], dry_run=bool(a.get("_dry_run"))), "Execute an Airflow backfill only through governed Builder approval.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING, supports_dry_run=True, requires_approval=True)

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

    # Behavior-compatible Altimate core wrappers over deterministic Python engines.
    add("altimate_core_complete", Capability.DISCOVER, lambda a: core_complete_sql(a["sql"], int(a.get("cursor_pos", len(a["sql"]))), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Return cursor-aware SQL completion suggestions.", platforms=sql_platforms)
    add("altimate_core_equivalence", Capability.VERIFY, lambda a: core_semantic_equivalence(a["sql1"], a["sql2"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Check schema-aware semantic SQL equivalence.", platforms=sql_platforms)
    add("altimate_core_grade", Capability.VERIFY, lambda a: core_grade_sql(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Grade deterministic SQL quality on an A-F scale.", platforms=sql_platforms)
    add("altimate_core_optimize_context", Capability.DISCOVER, lambda a: core_optimize_schema_context(schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Create five progressive schema-context disclosure levels.", platforms=sql_platforms)
    add("altimate_core_policy", Capability.VERIFY, lambda a: core_policy_check(a["sql"], a["policy_json"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Check SQL against deterministic JSON governance policy.", platforms=sql_platforms)
    add("altimate_core_prune_schema", Capability.DISCOVER, lambda a: core_prune_schema(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Prune schema context to SQL-referenced tables.", platforms=sql_platforms)
    add("altimate_core_resolve_term", Capability.DISCOVER, lambda a: core_resolve_term(a["term"], schema_context=a.get("schema_context"), schema_path=a.get("schema_path"), limit=int(a.get("limit", 20))), "Resolve business terms to schema tables and columns.", platforms=sql_platforms)
    add("altimate_core_semantics", Capability.VERIFY, lambda a: core_semantics(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Run schema-aware semantic SQL validation.", platforms=sql_platforms)
    add("altimate_core_validate", Capability.VERIFY, lambda a: core_validate_sql(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Validate SQL syntax and schema references.", platforms=sql_platforms)
    add("altimate_core_check", Capability.VERIFY, lambda a: core_full_check(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Run composite validation, lint, safety and PII analysis.", platforms=sql_platforms)
    add("altimate_core_correct", Capability.GENERATE, lambda a: core_correct_sql(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path"), max_iterations=int(a.get("max_iterations", 3))), "Iteratively correct supported SQL defects with deterministic verification.", platforms=sql_platforms)
    add("altimate_core_import_ddl", Capability.GENERATE, lambda a: core_import_ddl(a["ddl"], dialect=a.get("dialect")), "Convert CREATE TABLE DDL into structured schema context.", platforms=sql_platforms)
    add("altimate_core_introspection_sql", Capability.GENERATE, lambda a: core_introspection_sql(a["db_type"], a["database"], schema_name=a.get("schema_name")), "Generate warehouse introspection SQL for supported engines.", platforms=sql_platforms)

    # Compatibility aliases where the native ADE engine already supersedes the reference wrapper.
    add("altimate_core_fingerprint", Capability.VERIFY, lambda a: sql_fingerprint_impl(a["sql"], a.get("dialect")), "Compatibility alias for structural SQL fingerprint.", platforms=sql_platforms)
    add("altimate_core_fix", Capability.GENERATE, lambda a: sql_fix_impl(a["sql"], a.get("dialect"), a.get("schema_context")), "Compatibility alias for deterministic SQL fix.", platforms=sql_platforms)
    add("altimate_core_rewrite", Capability.GENERATE, lambda a: sql_rewrite_impl(a["sql"], a.get("dialect"), a.get("schema_context")), "Compatibility alias for deterministic SQL rewrite.", platforms=sql_platforms)
    add("altimate_core_column_lineage", Capability.VERIFY, lambda a: production_column_lineage(a["sql"], dialect=a.get("dialect"), schema=a.get("schema_context"), sources=a.get("sources")), "Compatibility alias for column lineage.", platforms=sql_platforms)
    add("altimate_core_schema_diff", Capability.VERIFY, lambda a: data_diff_schema_impl(a["source_schema"], a["target_schema"]), "Compatibility alias for schema diff.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("altimate_core_classify_pii", Capability.VERIFY, lambda a: core_classify_schema_pii(schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Classify PII columns across schema context.", platforms=sql_platforms)
    add("altimate_core_query_pii", Capability.VERIFY, lambda a: core_query_pii(a["sql"], schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Analyze query-level PII exposure.", platforms=sql_platforms)
    add("altimate_core_compare", Capability.VERIFY, lambda a: core_compare_sql(a["left_sql"], a["right_sql"], dialect=a.get("dialect")), "Structurally compare two SQL queries.", platforms=sql_platforms)
    add("altimate_core_export_ddl", Capability.GENERATE, lambda a: core_export_ddl(schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Export structured schema context as CREATE TABLE DDL.", platforms=sql_platforms)
    add("altimate_core_extract_metadata", Capability.DISCOVER, lambda a: core_extract_sql_metadata(a["sql"], dialect=a.get("dialect")), "Extract tables, columns, functions and CTEs from SQL.", platforms=sql_platforms)
    add("altimate_core_migration", Capability.VERIFY, lambda a: core_migration_safety(a["old_ddl"], a["new_ddl"], dialect=a.get("dialect")), "Analyze DDL migration safety and data-loss risk.", platforms=sql_platforms)
    add("altimate_core_parse_dbt", Capability.DBT, lambda a: core_parse_dbt_project(a["project_dir"]), "Parse dbt project artifacts into models, sources, tests and seeds.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("altimate_core_testgen", Capability.GENERATE, lambda a: core_generate_sql_tests(a["sql"], dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Generate deterministic SQL boundary, NULL, join and schema test scenarios.", platforms=sql_platforms)
    add("altimate_core_track_lineage", Capability.VERIFY, lambda a: core_track_lineage(list(a.get("queries") or ()), dialect=a.get("dialect"), schema_context=a.get("schema_context"), schema_path=a.get("schema_path")), "Track column lineage across multiple SQL queries.", platforms=sql_platforms)

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
    add("lineage_check", Capability.VERIFY, lambda a: production_column_lineage(a["sql"], dialect=a.get("dialect", "snowflake"), schema=a.get("schema_context"), sources=a.get("sources")), "Reference-compatible column-level SQL lineage check.", platforms=sql_platforms)
    add("impact_analysis", Capability.VERIFY, lambda a: (_column_graph({"target_dir": Path(a.get("manifest_path", "target/manifest.json")).expanduser().resolve().parent, **a}).impact(a["model"], a["column"]) if a.get("column") else _dbt({"target_dir": Path(a.get("manifest_path", "target/manifest.json")).expanduser().resolve().parent, **a}).impact(a["model"])), "Analyze dbt model/column downstream blast radius.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
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

    def warehouse_add_handler(a: dict[str, Any]) -> dict[str, Any]:
        config = dict(a.get("config") or {})
        platform = str(config.pop("type", a.get("platform") or "")).casefold()
        if not platform:
            raise ValueError('warehouse config requires "type"')
        return _connection_store(a).add(
            a["name"],
            platform,
            config,
            source=a.get("source", "warehouse_add"),
            replace=bool(a.get("replace", False)),
        )

    def schema_cache_status_handler(a: dict[str, Any]) -> dict[str, Any]:
        service = _metadata_service(a)
        rows = service.connection.execute(
            """
            SELECT o.connection_name,
                   COUNT(DISTINCT o.object_id) AS tables_count,
                   COUNT(c.column_name) AS columns_count,
                   MAX(COALESCE(c.refreshed_at, o.refreshed_at)) AS last_indexed
            FROM metadata_objects o
            LEFT JOIN metadata_columns c ON c.object_id = o.object_id
            GROUP BY o.connection_name
            ORDER BY o.connection_name
            """
        ).fetchall()
        warehouses = [
            {
                "name": str(row["connection_name"]),
                "type": next(
                    (
                        item["platform"]
                        for item in _connection_store(a).list()
                        if item["name"] == row["connection_name"]
                    ),
                    "unknown",
                ),
                "schemas_count": len(
                    {
                        item["schema_name"]
                        for item in service.search_assets(
                            "",
                            connection_name=str(row["connection_name"]),
                            limit=5000,
                        )
                        if item.get("schema_name")
                    }
                ),
                "tables_count": int(row["tables_count"] or 0),
                "columns_count": int(row["columns_count"] or 0),
                "last_indexed": row["last_indexed"],
            }
            for row in rows
        ]
        return {
            "status": "PASS",
            "cache_path": service.path,
            "total_tables": sum(item["tables_count"] for item in warehouses),
            "total_columns": sum(item["columns_count"] for item in warehouses),
            "warehouses": warehouses,
        }

    def schema_detect_pii_handler(a: dict[str, Any]) -> dict[str, Any]:
        service = _metadata_service(a)
        columns = service.search_columns(
            "",
            connection_name=a.get("warehouse") or a.get("connection"),
            limit=int(a.get("limit", 10000)),
        )
        schema_name = str(a.get("schema_name") or "").casefold()
        table_name = str(a.get("table") or "").casefold()
        filtered = [
            item
            for item in columns
            if (
                not schema_name
                or str(item.get("schema_name") or "").casefold() == schema_name
            )
            and (
                not table_name
                or str(item.get("object_name") or "").casefold() == table_name
            )
        ]
        result = classify_metadata_columns(filtered)
        by_category: dict[str, int] = {}
        tables = set()
        for finding in result.get("findings", ()):
            category = str(finding.get("category") or "unknown")
            by_category[category] = by_category.get(category, 0) + 1
            if finding.get("object_id"):
                tables.add(str(finding["object_id"]))
        return {
            "status": "PASS",
            "success": True,
            "columns_scanned": len(filtered),
            "finding_count": len(result.get("findings", ())),
            "tables_with_pii": len(tables),
            "by_category": dict(sorted(by_category.items())),
            "findings": result.get("findings", []),
        }

    add("warehouse_add", Capability.GENERATE, warehouse_add_handler, "Reference-compatible warehouse connection add with secret-safe config storage.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("warehouse_list", Capability.DISCOVER, lambda a: {"warehouses": _connection_store(a).list(), "default": _connection_store(a).default()}, "Reference-compatible warehouse connection listing.", platforms=frozenset({Platform.LOCAL}))
    add("warehouse_remove", Capability.GENERATE, lambda a: {"removed": _connection_store(a).remove(a["name"])}, "Reference-compatible warehouse removal.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)
    add("warehouse_test", Capability.VERIFY, connection_test_handler, "Reference-compatible warehouse connectivity test.", platforms=frozenset({Platform.LOCAL}))
    add("warehouse_discover", Capability.DISCOVER, lambda a: discover_docker_connections(), "Discover supported warehouse containers through Docker.", platforms=frozenset({Platform.LOCAL}))
    add("schema_cache_status", Capability.DISCOVER, schema_cache_status_handler, "Return local schema cache totals and per-warehouse freshness.", platforms=frozenset({Platform.LOCAL}))
    add("schema_detect_pii", Capability.VERIFY, schema_detect_pii_handler, "Scan indexed warehouse columns for deterministic PII classifications.", platforms=frozenset({Platform.LOCAL}))

    add("schema_refresh", Capability.DISCOVER, schema_refresh_handler, "Refresh persistent warehouse metadata using a configured read-only connector.", platforms=frozenset({Platform.LOCAL}))
    add("schema_index", Capability.DISCOVER, schema_refresh_handler, "Index live warehouse metadata into the local metadata service.", platforms=frozenset({Platform.LOCAL}))
    add("schema_search", Capability.DISCOVER, lambda a: {"assets": _metadata_service(a).search_assets(a.get("query", ""), connection_name=a.get("connection"), limit=int(a.get("limit", 50)))}, "Search persistent warehouse objects.", platforms=frozenset({Platform.LOCAL}))
    add("schema_inspect", Capability.DISCOVER, lambda a: _metadata_service(a).inspect(a["connection"], a["schema"], a["object"]), "Inspect indexed object and column metadata.", platforms=frozenset({Platform.LOCAL}))
    add("schema_tags", Capability.DISCOVER, lambda a: {"tags": _metadata_service(a).tags(a["connection"], a["schema"], a["object"])}, "Return indexed object tags.", platforms=frozenset({Platform.LOCAL}))
    def pii_scan_handler(a: dict[str, Any]) -> dict[str, Any]:
        service = _metadata_service(a)
        columns = service.search_columns(
            a.get("query", ""),
            connection_name=a.get("connection"),
            limit=int(a.get("limit", 1000)),
        )
        result = classify_metadata_columns(columns)
        persisted = 0
        if bool(a.get("persist", True)):
            for finding in result["findings"]:
                if finding.get("object_id") and finding.get("column"):
                    service.set_pii(
                        str(finding["object_id"]),
                        str(finding["column"]),
                        str(finding["category"]),
                        float(finding["confidence"]),
                    )
                    persisted += 1
        return {**result, "persisted": persisted}

    def pii_graph_handler(a: dict[str, Any]) -> dict[str, Any]:
        graph = _column_graph(a).graph()
        findings = a.get("findings")
        if findings is None:
            columns = _metadata_service(a).search_columns(
                "",
                connection_name=a.get("connection"),
                pii_only=True,
                limit=int(a.get("limit", 5000)),
            )
            findings = [
                {
                    "node_id": item.get("node_id"),
                    "asset_id": item.get("asset_id"),
                    "column": item.get("column_name"),
                    "category": item.get("pii_category"),
                    "confidence": item.get("pii_confidence"),
                    "evidence": ["persisted metadata classification"],
                }
                for item in columns
                if item.get("pii_category")
            ]
        return governance_propagate_pii(
            graph,
            findings,
            minimum_confidence=float(a.get("minimum_confidence", 0.7)),
        )

    def pii_exposure_handler(a: dict[str, Any]) -> dict[str, Any]:
        graph = _column_graph(a).graph()
        findings = a.get("findings") or []
        if not findings:
            columns = _metadata_service(a).search_columns(
                "",
                connection_name=a.get("connection"),
                pii_only=True,
                limit=int(a.get("limit", 5000)),
            )
            findings = [
                {
                    "node_id": item.get("node_id"),
                    "asset_id": item.get("asset_id"),
                    "column": item.get("column_name"),
                    "category": item.get("pii_category"),
                    "confidence": item.get("pii_confidence"),
                    "evidence": ["persisted metadata classification"],
                }
                for item in columns
                if item.get("pii_category")
            ]
        return governance_pii_exposure(graph, findings)

    def pii_policy_handler(a: dict[str, Any]) -> dict[str, Any]:
        schema_context = a.get("schema_context")
        if schema_context is None:
            schema_context = _metadata_service(a).schema_context(
                connection_name=a.get("connection"),
                query=a.get("asset_query", ""),
                limit=int(a.get("asset_limit", 500)),
            )
        return governance_pii_policy_check(
            a["sql"],
            schema_context,
            allow_categories=a.get("allow_categories", ()),
            action=a.get("action", "query"),
        )

    def rbac_inventory_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            connector = finops_connector(a)
        except ExternalConnectionUnavailable as exc:
            return {"status": "SKIP_EXTERNAL", "reason": str(exc), "graph": {"nodes": [], "edges": []}}
        return governance_rbac_inventory(connector)

    def pii_access_handler(a: dict[str, Any]) -> dict[str, Any]:
        inventory = rbac_inventory_handler(a)
        if inventory.get("status") != "PASS":
            return inventory
        pii_objects = a.get("pii_objects")
        if pii_objects is None:
            pii_objects = _metadata_service(a).search_columns(
                "",
                connection_name=a.get("connection"),
                pii_only=True,
                limit=int(a.get("limit", 5000)),
            )
        return governance_sensitive_access_report(inventory["graph"], pii_objects)

    add("pii_scan", Capability.VERIFY, pii_scan_handler, "Classify and optionally persist PII metadata evidence.", platforms=frozenset({Platform.LOCAL}))
    add("pii_lineage", Capability.DISCOVER, pii_graph_handler, "Propagate evidence-backed PII classifications through dbt column lineage.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("pii_exposure", Capability.VERIFY, pii_exposure_handler, "Find downstream dbt assets exposed to PII.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("pii_policy_check", Capability.VERIFY, pii_policy_handler, "Block SQL that references disallowed PII categories.", platforms=frozenset({Platform.LOCAL}))
    add("pii_downstream_assets", Capability.DISCOVER, pii_exposure_handler, "Return downstream assets carrying propagated PII.", platforms=frozenset({Platform.LOCAL, Platform.DBT}))
    add("rbac_audit", Capability.VERIFY, rbac_inventory_handler, "Build warehouse user-role-object access graph.", platforms=frozenset({Platform.LOCAL}))
    add("rbac_object_access", Capability.DISCOVER, lambda a: governance_object_access(rbac_inventory_handler(a)["graph"], a["object"]), "List principals with access to a warehouse object.", platforms=frozenset({Platform.LOCAL}))
    add("rbac_risk", Capability.VERIFY, lambda a: governance_excessive_privileges(rbac_inventory_handler(a)["graph"], observed_objects_by_principal=a.get("observed_objects_by_principal"), minimum_grants=int(a.get("minimum_grants", 20)), unused_ratio_threshold=float(a.get("unused_ratio_threshold", 0.8))), "Detect excessive role/user grants using observed-access evidence.", platforms=frozenset({Platform.LOCAL}))
    add("pii_access_report", Capability.VERIFY, pii_access_handler, "Correlate PII metadata with warehouse RBAC access.", platforms=frozenset({Platform.LOCAL}))

    add("metadata_status", Capability.DISCOVER, lambda a: _metadata_service(a).status(a.get("connection")), "Report metadata index counts and latest refresh evidence.", platforms=frozenset({Platform.LOCAL}))
    add("autocomplete", Capability.DISCOVER, metadata_autocomplete_handler, "Return SQL autocomplete candidates from persistent live metadata.", platforms=frozenset({Platform.LOCAL}))

    add("metadata_search", Capability.DISCOVER, lambda a: {"assets": MetadataIndex(a.get("database", ":memory:")).search_assets(a.get("query", ""), kind=a.get("kind"))}, "Search the local schema-aware metadata index.", platforms=frozenset({Platform.LOCAL}))
    add("metadata_column_search", Capability.DISCOVER, lambda a: {"columns": MetadataIndex(a.get("database", ":memory:")).search_columns(a.get("query", ""), pii_only=a.get("pii_only", False))}, "Search indexed columns and PII flags.", platforms=frozenset({Platform.LOCAL}))
    def finops_connector(a: dict[str, Any]):
        connection = a.get("connection")
        if connection:
            profile = _connection_store(a).resolve_config(connection)
            return connector_from_args({"platform": profile["platform"], "config": profile["config"]})
        definition = a.get("warehouse") if isinstance(a.get("warehouse"), dict) else a
        return connector_from_args(definition)

    def finops_history_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            return finops_query_history(
                finops_connector(a),
                days=int(a.get("days", 7)),
                limit=int(a.get("limit", 1000)),
                region=a.get("region", "region-us"),
            )
        except ExternalConnectionUnavailable as exc:
            return {"status": "SKIP_EXTERNAL", "reason": str(exc), "queries": []}

    def finops_report_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            return full_finops_report(
                finops_connector(a),
                days=int(a.get("days", 7)),
                limit=int(a.get("limit", 1000)),
                credit_price_usd=a.get("credit_price_usd"),
                region=a.get("region", "region-us"),
            )
        except ExternalConnectionUnavailable as exc:
            return {"status": "SKIP_EXTERNAL", "reason": str(exc)}

    add("finops_query_history", Capability.DISCOVER, finops_history_handler, "Read normalized warehouse query history from configured connector.", platforms=frozenset({Platform.LOCAL}))
    add("finops_expensive_queries", Capability.VERIFY, lambda a: {"queries": finops_expensive_queries(finops_history_handler(a).get("queries", []), limit=int(a.get("top", 25)), min_elapsed_ms=a.get("min_elapsed_ms"))}, "Rank expensive queries from normalized execution evidence.", platforms=frozenset({Platform.LOCAL}))
    add("finops_query_errors", Capability.VERIFY, lambda a: {"queries": finops_query_errors(finops_history_handler(a).get("queries", []))}, "Extract failed/error warehouse queries.", platforms=frozenset({Platform.LOCAL}))
    add("finops_query_patterns", Capability.VERIFY, lambda a: {"patterns": finops_query_patterns(finops_history_handler(a).get("queries", []), limit=int(a.get("top", 20)))}, "Aggregate parameter-insensitive query patterns.", platforms=frozenset({Platform.LOCAL}))
    add("finops_cost_summary", Capability.VERIFY, lambda a: finops_cost_summary(finops_connector(a), days=int(a.get("days", 7)), credit_price_usd=a.get("credit_price_usd"), region=a.get("region", "region-us")), "Calculate connector-supported cost or credit evidence.", platforms=frozenset({Platform.LOCAL}))
    add("finops_warehouse_usage", Capability.VERIFY, lambda a: finops_warehouse_usage(finops_connector(a), days=int(a.get("days", 7))), "Read warehouse load and metering evidence.", platforms=frozenset({Platform.LOCAL}))
    add("finops_warehouse_advisor", Capability.PLAN, lambda a: finops_warehouse_advisor(finops_connector(a), days=int(a.get("days", 7))), "Generate evidence-backed warehouse right-sizing recommendations.", platforms=frozenset({Platform.LOCAL}))
    add("finops_idle_resources", Capability.VERIFY, lambda a: finops_idle_resources(finops_connector(a), days=int(a.get("days", 7))), "Detect idle warehouse resources from measured usage.", platforms=frozenset({Platform.LOCAL}))
    add("finops_report", Capability.VERIFY, finops_report_handler, "Build complete query, cost, and warehouse FinOps report.", platforms=frozenset({Platform.LOCAL}))

    def finops_analyze_credits_handler(a: dict[str, Any]) -> dict[str, Any]:
        try:
            connector = finops_connector(a)
            cost = finops_cost_summary(
                connector,
                days=int(a.get("days", 30)),
                credit_price_usd=a.get("credit_price_usd"),
                region=a.get("region", "region-us"),
            )
            usage = finops_warehouse_usage(
                connector,
                days=int(a.get("days", 30)),
            )
            advisor = finops_warehouse_advisor(
                connector,
                days=int(a.get("days", 30)),
            )
        except ExternalConnectionUnavailable as exc:
            return {
                "status": "SKIP_EXTERNAL",
                "reason": str(exc),
                "total_credits": 0,
                "warehouse_summary": [],
                "recommendations": [],
                "daily_usage": [],
            }
        return {
            "status": "PASS",
            "total_credits": float(
                cost.get("credits_used")
                or cost.get("total_credits")
                or cost.get("credits")
                or 0
            ),
            "days_analyzed": int(a.get("days", 30)),
            "warehouse_summary": usage.get("warehouses", usage.get("rows", [])),
            "recommendations": advisor.get("recommendations", []),
            "daily_usage": cost.get("daily_usage", []),
            "cost_summary": cost,
        }

    def finops_role_graph(a: dict[str, Any]) -> dict[str, Any]:
        inventory = rbac_inventory_handler(a)
        if inventory.get("status") != "PASS":
            return inventory
        return inventory["graph"]

    add("finops_analyze_credits", Capability.VERIFY, finops_analyze_credits_handler, "Reference-compatible credit/cost consumption analysis.", platforms=frozenset({Platform.LOCAL}))
    add("finops_unused_resources", Capability.VERIFY, lambda a: finops_idle_resources(finops_connector(a), days=int(a.get("days", 30))), "Reference-compatible idle and unused warehouse-resource analysis.", platforms=frozenset({Platform.LOCAL}))
    add("finops_warehouse_advice", Capability.PLAN, lambda a: finops_warehouse_advisor(finops_connector(a), days=int(a.get("days", 30))), "Reference-compatible warehouse right-sizing advice.", platforms=frozenset({Platform.LOCAL}))
    add("finops_role_grants", Capability.DISCOVER, lambda a: {"status": "PASS", "graph": finops_role_graph(a), "role": a.get("role"), "object_name": a.get("object_name")}, "Reference-compatible warehouse RBAC grants view.", platforms=frozenset({Platform.LOCAL}))
    add("finops_role_hierarchy", Capability.DISCOVER, lambda a: {"status": "PASS", "graph": finops_role_graph(a)}, "Reference-compatible role hierarchy view.", platforms=frozenset({Platform.LOCAL}))
    add("finops_user_roles", Capability.DISCOVER, lambda a: {"status": "PASS", "graph": finops_role_graph(a)}, "Reference-compatible user-to-role assignment view.", platforms=frozenset({Platform.LOCAL}))

    add("warehouse_status", Capability.DISCOVER, _warehouse_status, "Report adapter, driver, credentials and local-simulation availability.", platforms=frozenset({Platform.LOCAL}))
    add("warehouse_driver_status", Capability.DISCOVER, lambda a: warehouse_driver_status(a["platform"]), "Report warehouse driver package and installation state.", platforms=frozenset({Platform.LOCAL}))
    add("warehouse_install_driver", Capability.EXECUTE, lambda a: install_warehouse_driver(a["platform"], dry_run=bool(a.get("dry_run", True))), "Install one allowlisted warehouse driver package; dry-run is the default.", platforms=frozenset({Platform.LOCAL}), risk=Risk.MUTATING)

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
    def data_diff_hash_handler(a: dict[str, Any]) -> dict[str, Any]:
        if "source_rows" in a:
            return data_diff_hash_impl(a["source_rows"], a["target_rows"], a["key_columns"])
        try:
            return _warehouse_diff_engine(a).hash(
                a["source_table"],
                a["target_table"],
                key_columns=a["key_columns"],
                compare_columns=a.get("compare_columns"),
                exclude_columns=a.get("exclude_columns", ()),
                where=a.get("where"),
                max_partition_rows=int(a.get("max_partition_rows", 50000)),
                max_depth=int(a.get("max_depth", 24)),
                detail_limit=int(a.get("detail_limit", 100)),
            )
        except ExternalConnectionUnavailable as exc:
            return {"algorithm": "HASH_DIFF", "status": "SKIP_EXTERNAL", "reason": str(exc)}

    add("data_diff_hash", Capability.VERIFY, data_diff_hash_handler, "Run bounded partition hash diff across configured warehouses or compare local row hashes.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_rows", Capability.VERIFY, lambda a: data_diff_rows_impl(a["source_rows"], a["target_rows"], a["key_columns"], compare_columns=a.get("compare_columns")), "Return missing, extra, changed and matching keyed rows.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_aggregate", Capability.VERIFY, lambda a: data_diff_aggregate_impl(a["source_rows"], a["target_rows"], a["column"], aggregate=a.get("aggregate", "sum"), tolerance=a.get("tolerance", 0)), "Compare deterministic source/target aggregates.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    add("data_diff_report", Capability.VERIFY, lambda a: data_diff_report_impl(a["source_rows"], a["target_rows"], a["key_columns"], aggregate_columns=a.get("aggregate_columns", ())), "Build a composite schema/row/key/hash/aggregate data-diff report.", platforms=frozenset({Platform.LOCAL, Platform.DUCKDB}))
    def production_diff(a: dict[str, Any], algorithm: str) -> dict[str, Any]:
        try:
            engine = _warehouse_diff_engine(a)
            common = {
                "key_columns": a["key_columns"],
                "compare_columns": a.get("compare_columns"),
                "exclude_columns": a.get("exclude_columns", ()),
            }
            if algorithm == "PLAN":
                return engine.plan(a["source_table"], a["target_table"], **common)
            if algorithm == "PROFILE":
                return engine.profile(
                    a["source_table"],
                    a["target_table"],
                    columns=a.get("columns"),
                    where=a.get("where"),
                    numeric_tolerance=float(a.get("numeric_tolerance", 0.0)),
                )
            if algorithm == "JOIN_DIFF":
                return engine.join(
                    a["source_table"],
                    a["target_table"],
                    **common,
                    where=a.get("where"),
                    row_sample_limit=int(a.get("row_sample_limit", 10000)),
                )
            if algorithm == "CASCADE":
                return engine.cascade(
                    a["source_table"],
                    a["target_table"],
                    **common,
                    where=a.get("where"),
                    numeric_tolerance=float(a.get("numeric_tolerance", 0.0)),
                    max_partition_rows=int(a.get("max_partition_rows", 50000)),
                    detail_limit=int(a.get("detail_limit", 100)),
                )
            return engine.auto(
                a["source_table"],
                a["target_table"],
                **common,
                where=a.get("where"),
                row_sample_limit=int(a.get("row_sample_limit", 10000)),
                max_partition_rows=int(a.get("max_partition_rows", 50000)),
                detail_limit=int(a.get("detail_limit", 100)),
            )
        except ExternalConnectionUnavailable as exc:
            return {"algorithm": algorithm, "status": "SKIP_EXTERNAL", "reason": str(exc)}

    add("data_diff", Capability.VERIFY, lambda a: production_diff(a, "AUTO"), "Auto-select production cross-warehouse data diff.", platforms=frozenset({Platform.LOCAL}))
    add("data_diff_plan", Capability.PLAN, lambda a: production_diff(a, "PLAN"), "Plan a production cross-warehouse data diff.", platforms=frozenset({Platform.LOCAL}))
    add("data_diff_profile", Capability.VERIFY, lambda a: production_diff(a, "PROFILE"), "Run PII-safe profile diff without retrieving raw rows.", platforms=frozenset({Platform.LOCAL}))
    add("data_diff_join", Capability.VERIFY, lambda a: production_diff(a, "JOIN_DIFF"), "Run warehouse-pushdown or bounded cross-warehouse join diff.", platforms=frozenset({Platform.LOCAL}))
    add("data_diff_cascade", Capability.VERIFY, lambda a: production_diff(a, "CASCADE"), "Run profile then bounded hash/detail cascade diff.", platforms=frozenset({Platform.LOCAL}))

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
