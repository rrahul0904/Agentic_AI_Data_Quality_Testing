from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.models import (
    DryRunResult,
    QueryResult,
    SchemaMetadata,
    TableMetadata,
)
from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.governance import (
    execute_permission_change,
    permission_change_plan,
)
from agentic_data_platform.tools.builtin import build_tool_registry


class ReadOnlyPostgresConnector(DataPlatformConnector):
    platform = "postgres"

    def capabilities(self) -> set[ConnectorCapability]:
        return {
            ConnectorCapability.QUERY_READ,
            ConnectorCapability.QUERY_DRY_RUN,
        }

    def list_schemas(self) -> list[SchemaMetadata]:
        return []

    def list_tables(self, schema: str) -> list[TableMetadata]:
        return []

    def describe_table(self, schema: str, table: str) -> TableMetadata:
        return TableMetadata(table, schema)

    def dry_run_sql(self, sql: str) -> DryRunResult:
        return DryRunResult(True)

    def execute_read(self, sql: str) -> QueryResult:
        return QueryResult((), ())


def test_snowflake_permission_plan_is_least_privilege_hash_bound():
    plan = permission_change_plan(
        platform="snowflake",
        action="grant_privilege",
        principal="ANALYST_ROLE",
        principal_kind="role",
        privilege="select",
        object_type="table",
        object_name="RAW.RESERVATIONS",
        environment="dev",
        reason="read reservation evidence",
    )

    assert plan["status"] == "PASS"
    assert plan["statement"] == (
        "GRANT SELECT ON TABLE RAW.RESERVATIONS TO ROLE ANALYST_ROLE"
    )
    assert plan["verification_sql"] == "SHOW GRANTS TO ROLE ANALYST_ROLE"
    assert plan["least_privilege"]["single_principal"] is True
    assert plan["least_privilege"]["wildcard_principal"] is False
    assert plan["policy"]["approval_required"] is True
    assert plan["approval_fingerprint"]


def test_permission_plan_tracks_observed_blast_radius():
    graph = {
        "nodes": [
            {"node_id": "role:ANALYST_ROLE", "kind": "role", "name": "ANALYST_ROLE"},
            {"node_id": "table:RAW.A", "kind": "table", "name": "RAW.A"},
        ],
        "edges": [
            {
                "source": "role:ANALYST_ROLE",
                "target": "table:RAW.A",
                "kind": "granted",
                "privilege": "SELECT",
            }
        ],
    }
    plan = permission_change_plan(
        platform="snowflake",
        action="grant_privilege",
        principal="ANALYST_ROLE",
        principal_kind="role",
        privilege="select",
        object_type="table",
        object_name="RAW.B",
        observed_graph=graph,
    )
    assert plan["blast_radius"]["reachable_access_before"] == 1


def test_postgres_and_databricks_plans_are_provider_specific():
    postgres = permission_change_plan(
        platform="postgres",
        action="grant_privilege",
        principal="analyst_user",
        principal_kind="user",
        privilege="select",
        object_type="table",
        object_name="public.reservations",
    )
    databricks = permission_change_plan(
        platform="databricks",
        action="grant_privilege",
        principal="ANALYST_ROLE",
        principal_kind="role",
        privilege="select",
        object_type="table",
        object_name="main.raw.reservations",
    )

    assert postgres["statement"] == (
        "GRANT SELECT ON TABLE public.reservations TO analyst_user"
    )
    assert databricks["statement"] == (
        "GRANT SELECT ON TABLE main.raw.reservations TO ROLE ANALYST_ROLE"
    )


def test_stale_permission_approval_never_executes():
    calls: list[str] = []

    def executor(sql: str) -> dict[str, Any]:
        calls.append(sql)
        return {"rows": []}

    connector = SnowflakeConnector(executor)
    plan = permission_change_plan(
        platform="snowflake",
        action="grant_privilege",
        principal="ANALYST_ROLE",
        privilege="select",
        object_type="table",
        object_name="RAW.RESERVATIONS",
    )

    result = execute_permission_change(
        connector,
        plan,
        approval_fingerprint="tampered",
    )

    assert result["status"] == "STALE_APPROVAL"
    assert calls == []


def test_production_revoke_requires_admin_before_mutation():
    calls: list[str] = []

    def executor(sql: str) -> dict[str, Any]:
        calls.append(sql)
        return {"rows": []}

    connector = SnowflakeConnector(executor)
    plan = permission_change_plan(
        platform="snowflake",
        action="revoke_privilege",
        principal="ANALYST_ROLE",
        privilege="select",
        object_type="table",
        object_name="RAW.RESERVATIONS",
        environment="prod",
    )
    result = execute_permission_change(
        connector,
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
        actor_mode="builder",
    )

    assert result["status"] == "BLOCKED_POLICY"
    assert calls == []


def test_platform_mismatch_blocks_before_execution():
    connector = ReadOnlyPostgresConnector()
    plan = permission_change_plan(
        platform="snowflake",
        action="grant_privilege",
        principal="ANALYST_ROLE",
        privilege="select",
        object_type="table",
        object_name="RAW.RESERVATIONS",
    )

    result = execute_permission_change(
        connector,
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
    )

    assert result["status"] == "BLOCKED_PLATFORM_MISMATCH"


def test_read_only_connector_cannot_gain_implicit_mutation_capability():
    connector = ReadOnlyPostgresConnector()
    plan = permission_change_plan(
        platform="postgres",
        action="grant_privilege",
        principal="analyst_user",
        principal_kind="user",
        privilege="select",
        object_type="table",
        object_name="public.reservations",
    )

    result = execute_permission_change(
        connector,
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
    )

    assert result["status"] == "BLOCKED_UNSUPPORTED"
    assert "read-only connector contract remains intact" in result["reason"]


def test_governed_snowflake_permission_executes_and_independently_verifies():
    calls: list[str] = []

    def executor(sql: str) -> dict[str, Any]:
        calls.append(sql)
        if sql.startswith("SHOW GRANTS"):
            return {
                "rows": [
                    {
                        "privilege": "SELECT",
                        "granted_on": "TABLE",
                        "name": "RAW.RESERVATIONS",
                        "grantee_name": "ANALYST_ROLE",
                    }
                ],
                "query_id": "verify-1",
            }
        return {"rows": [], "query_id": "mutation-1"}

    connector = SnowflakeConnector(executor)
    plan = permission_change_plan(
        platform="snowflake",
        action="grant_privilege",
        principal="ANALYST_ROLE",
        privilege="select",
        object_type="table",
        object_name="RAW.RESERVATIONS",
    )

    result = execute_permission_change(
        connector,
        plan,
        approval_fingerprint=plan["approval_fingerprint"],
        actor_mode="admin",
    )

    assert result["status"] == "PASS"
    assert result["verification_status"] == "PASS"
    assert result["evidence"]["verification_row_count"] == 1
    assert result["evidence"]["statement_sha256"]
    assert result["evidence_fingerprint"]
    assert calls == [
        "GRANT SELECT ON TABLE RAW.RESERVATIONS TO ROLE ANALYST_ROLE",
        "SHOW GRANTS TO ROLE ANALYST_ROLE",
    ]


def test_permissions_tools_cli_and_api_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {"permission_plan", "permission_execute"} <= names

    expected = set(DOMAIN_CLI_TOOLS["governance"])
    assert {"permission-plan", "permission-execute"} <= expected

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    assert set(response.json()["governance"]) == expected
