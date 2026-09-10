from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.snowflake import (
    ManagedDbtExecutor,
    plan_managed_dbt,
    render_managed_dbt_sql,
    supported_managed_dbt_commands,
)
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


class ManagedDbtFixture:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def __call__(self, sql: str):
        self.executed.append(sql)
        lowered = sql.casefold()
        if lowered.startswith("execute dbt project"):
            return {
                "columns": ("MESSAGE",),
                "rows": ({"MESSAGE": "dbt command completed"},),
                "query_id": "q-dbt-1",
            }
        if "query_history_by_session" in lowered:
            return {
                "columns": ("QUERY_ID", "EXECUTION_STATUS"),
                "rows": ({"QUERY_ID": "q-dbt-1", "EXECUTION_STATUS": "SUCCESS"},),
            }
        raise AssertionError(f"unexpected SQL: {sql}")


def test_render_project_object_execution():
    sql = render_managed_dbt_sql(
        project_name="ANALYTICS.DBT_PROJECTS.HOSPITALITY",
        command="build",
        flags=["--select", "+fact_reservation+", "--target", "dev"],
    )

    assert sql == (
        "EXECUTE DBT PROJECT ANALYTICS.DBT_PROJECTS.HOSPITALITY "
        "ARGS = 'build --select +fact_reservation+ --target dev'"
    )


def test_render_workspace_execution_with_supported_options():
    sql = render_managed_dbt_sql(
        workspace_name="Hospitality dbt",
        command="run",
        flags=["--select", "fact_reservation"],
        dbt_version="1.11.11",
        dbt_environment="staging",
        env_vars={"DBT_DATABASE": "HOSPITALITY_STAGING"},
        external_access_integrations=["DBT_EAI"],
        project_root="projects/hospitality",
        if_exists=True,
    )

    assert 'EXECUTE DBT PROJECT IF EXISTS FROM WORKSPACE user$.public."Hospitality dbt"' in sql
    assert "ARGS = 'run --select fact_reservation'" in sql
    assert "DBT_VERSION = '1.11.11'" in sql
    assert "EXTERNAL_ACCESS_INTEGRATIONS = (DBT_EAI)" in sql
    assert "ENVIRONMENT = 'staging'" in sql
    assert "ENV_VARS = ('DBT_DATABASE' = 'HOSPITALITY_STAGING')" in sql
    assert "PROJECT_ROOT = 'projects/hospitality'" in sql


def test_managed_dbt_rejects_unsupported_snowflake_flags():
    with pytest.raises(ValueError, match="does not support flag"):
        render_managed_dbt_sql(
            project_name="ANALYTICS.DBT_PROJECTS.HOSPITALITY",
            command="run",
            flags=["--state", "./prod-state"],
        )


def test_managed_dbt_rejects_inline_secret_like_environment_variables():
    with pytest.raises(ValueError, match="sensitive dbt environment variable"):
        render_managed_dbt_sql(
            project_name="ANALYTICS.DBT_PROJECTS.HOSPITALITY",
            command="run",
            env_vars={"DBT_API_TOKEN": "secret"},
        )


def test_workspace_project_root_cannot_escape_workspace():
    with pytest.raises(ValueError, match="workspace-relative"):
        render_managed_dbt_sql(
            workspace_name="Hospitality dbt",
            command="build",
            project_root="../other-project",
        )


def test_managed_dbt_plan_binds_approval_to_exact_execution():
    first = plan_managed_dbt(
        ade_environment="dev",
        project_name="ANALYTICS.DBT_PROJECTS.HOSPITALITY",
        command="build",
        flags=["--select", "fact_reservation"],
    )
    second = plan_managed_dbt(
        ade_environment="dev",
        project_name="ANALYTICS.DBT_PROJECTS.HOSPITALITY",
        command="build",
        flags=["--select", "fact_payment"],
    )

    assert first["status"] == "PASS"
    assert first["statement_type"] == "EXECUTE_DBT_PROJECT"
    assert first["mode"] == "SNOWFLAKE_MANAGED_DBT_PLAN"
    assert first["approval_fingerprint"] != second["approval_fingerprint"]


def test_managed_dbt_real_execution_is_verified_from_query_history():
    fixture = ManagedDbtFixture()
    connector = SnowflakeConnector(
        fixture,
        SnowflakeConfig(database="ANALYTICS", schema="DBT_PROJECTS"),
    )
    executor = ManagedDbtExecutor(connector)
    kwargs = {
        "project_name": "ANALYTICS.DBT_PROJECTS.HOSPITALITY",
        "command": "test",
        "flags": ["--select", "fact_reservation"],
    }
    plan = plan_managed_dbt(ade_environment="dev", **kwargs)

    result = executor.execute(
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
        ade_environment="dev",
        **kwargs,
    )

    assert result["status"] == "PASS"
    assert result["verified"] is True
    assert result["query_id"] == "q-dbt-1"
    assert any("query_history_by_session" in item.casefold() for item in fixture.executed)


def test_managed_dbt_tool_dry_run_requires_approval_but_not_credentials(monkeypatch):
    for name in ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    registry = build_tool_registry()
    args = {
        "project_name": "ANALYTICS.DBT_PROJECTS.HOSPITALITY",
        "command": "build",
        "flags": ["--select", "fact_reservation"],
    }
    plan_def = registry.describe("snowflake_managed_dbt_plan")
    plan = registry.invoke(ToolInvocation(
        ToolRequest(
            "snowflake_managed_dbt_plan",
            "snowflake_managed_dbt_plan",
            Environment.DEV,
            plan_def.risk,
            args=args,
        ),
        run_id="managed-dbt-plan",
        actor_mode=ActorMode.ANALYST,
    ))

    execute_def = registry.describe("snowflake_managed_dbt_execute")
    request = ToolRequest(
        "snowflake_managed_dbt_execute",
        "snowflake_managed_dbt_execute",
        Environment.DEV,
        execute_def.risk,
        args={**args, "approval_fingerprint": plan["approval_fingerprint"]},
    )

    with pytest.raises(PermissionError):
        registry.invoke(ToolInvocation(
            request,
            run_id="managed-dbt-unapproved",
            actor_mode=ActorMode.BUILDER,
            approved=False,
            dry_run=True,
        ))

    result = registry.invoke(ToolInvocation(
        request,
        run_id="managed-dbt-approved",
        actor_mode=ActorMode.BUILDER,
        approved=True,
        dry_run=True,
    ))
    assert result["status"] == "PASS"
    assert result["mode"] == "DRY_RUN"
    assert result["executed"] is False


def test_managed_dbt_surfaces_are_exposed_through_cli_and_api():
    assert DOMAIN_CLI_TOOLS["dbt-managed"] == {
        "commands": "snowflake_managed_dbt_commands",
        "plan": "snowflake_managed_dbt_plan",
        "execute": "snowflake_managed_dbt_execute",
    }

    commands = supported_managed_dbt_commands()
    assert "build" in commands["commands"]
    assert "--state" in commands["blocked_flags"]

    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert set(domains.json()["dbt-managed"]) == {"commands", "plan", "execute"}

    response = client.post(
        "/api/v1/dbt-managed/plan",
        json={
            "args": {
                "project_name": "ANALYTICS.DBT_PROJECTS.HOSPITALITY",
                "command": "compile",
            },
            "environment": "dev",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PASS"
