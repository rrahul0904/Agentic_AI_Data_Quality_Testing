from __future__ import annotations

import sqlite3

from agentic_data_platform.metadata.service import MetadataService
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def invoke(registry, name, args, *, actor=ActorMode.BUILDER):
    definition = registry.describe(name)
    request = ToolRequest(
        tool=name,
        operation=name,
        environment=Environment.DEV,
        risk=definition.risk,
        args=args,
    )
    return registry.invoke(
        ToolInvocation(
            request,
            run_id=f"alias-{name}",
            actor_mode=actor,
        )
    )


def test_reference_warehouse_aliases_use_secret_safe_connection_store(tmp_path):
    database = tmp_path / "warehouse.sqlite"
    sqlite3.connect(database).close()
    registry = build_tool_registry()
    common = {"project": str(tmp_path)}

    added = invoke(
        registry,
        "warehouse_add",
        {
            **common,
            "name": "local-sqlite",
            "config": {
                "type": "sqlite",
                "path": str(database),
            },
        },
    )
    assert added["name"] == "local-sqlite"
    assert added["platform"] == "sqlite"

    listed = invoke(
        registry,
        "warehouse_list",
        common,
        actor=ActorMode.ANALYST,
    )
    assert listed["warehouses"][0]["name"] == "local-sqlite"

    tested = invoke(
        registry,
        "warehouse_test",
        {**common, "name": "local-sqlite"},
        actor=ActorMode.ANALYST,
    )
    assert tested["status"] == "PASS"

    removed = invoke(
        registry,
        "warehouse_remove",
        {**common, "name": "local-sqlite"},
    )
    assert removed["removed"] is True


def test_reference_schema_cache_and_pii_aliases(tmp_path):
    metadata_path = tmp_path / ".ade" / "metadata.db"
    service = MetadataService(metadata_path)
    now = "2026-09-07T00:00:00+00:00"
    service.connection.execute(
        """
        INSERT INTO metadata_objects(
          object_id, connection_name, warehouse, catalog, schema_name,
          object_name, object_type, owner, comment, tags_json,
          primary_key_json, foreign_keys_json, partitioning_json,
          clustering_json, refreshed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "local::public:guests",
            "local",
            "sqlite",
            None,
            "public",
            "guests",
            "table",
            None,
            None,
            "[]",
            "[]",
            "[]",
            "[]",
            "[]",
            now,
        ),
    )
    service.connection.execute(
        """
        INSERT INTO metadata_columns(
          column_id, object_id, column_name, ordinal_position, data_type,
          nullable, default_value, comment, tags_json, pii_category,
          pii_confidence, refreshed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "local::public:guests:guest_email",
            "local::public:guests",
            "guest_email",
            1,
            "VARCHAR",
            1,
            None,
            "Guest email address",
            "[]",
            None,
            None,
            now,
        ),
    )
    service.connection.commit()

    registry = build_tool_registry()
    common = {
        "project": str(tmp_path),
        "metadata_database": str(metadata_path),
    }
    cache = invoke(
        registry,
        "schema_cache_status",
        common,
        actor=ActorMode.ANALYST,
    )
    assert cache["total_tables"] == 1
    assert cache["total_columns"] == 1
    assert cache["warehouses"][0]["name"] == "local"

    pii = invoke(
        registry,
        "schema_detect_pii",
        {**common, "warehouse": "local", "schema_name": "public", "table": "guests"},
        actor=ActorMode.ANALYST,
    )
    assert pii["columns_scanned"] == 1
    assert pii["finding_count"] >= 1
    assert "email" in pii["by_category"]


def test_reference_lineage_alias_is_callable():
    registry = build_tool_registry()
    result = invoke(
        registry,
        "lineage_check",
        {
            "sql": "SELECT o.order_id, o.amount FROM orders o",
            "dialect": "snowflake",
            "schema_context": {
                "orders": {
                    "order_id": "INTEGER",
                    "amount": "NUMBER",
                }
            },
        },
        actor=ActorMode.ANALYST,
    )
    assert result["parseable"] is True
    assert result["status"] == "PASS"


def test_reference_public_tool_ids_are_registered():
    names = {item.name for item in build_tool_registry().definitions()}
    expected = {
        "warehouse_add",
        "warehouse_discover",
        "warehouse_install_driver",
        "warehouse_list",
        "warehouse_remove",
        "warehouse_test",
        "schema_cache_status",
        "schema_detect_pii",
        "lineage_check",
        "impact_analysis",
        "finops_analyze_credits",
        "finops_expensive_queries",
        "finops_query_history",
        "finops_role_grants",
        "finops_role_hierarchy",
        "finops_user_roles",
        "finops_unused_resources",
        "finops_warehouse_advice",
        "dbt_pr_review",
        "dbt_profiles",
        "dbt_unit_test_gen",
        "feedback_submit",
        "mcp_discover",
        "post_connect_suggestions",
        "response_normalization",
        "sample_setup",
        "tool_lookup",
        "training_import",
        "training_list",
        "training_remove",
        "training_save",
    }
    assert expected.issubset(names)
