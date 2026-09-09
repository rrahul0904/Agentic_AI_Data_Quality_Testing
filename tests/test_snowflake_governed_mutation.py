from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS, build_parser
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.snowflake import GovernedSnowflakeMutationExecutor, plan_snowflake_mutation
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


class MutationFixture:
    def __init__(self) -> None:
        self.created = False
        self.columns = {"ID"}
        self.row_count = 3
        self.statements: list[str] = []

    def __call__(self, sql: str):
        self.statements.append(sql)
        lowered = sql.casefold().strip()

        if lowered.startswith("show tables like"):
            rows = ({"name": "RESERVATIONS"},) if self.created else ()
            return {"columns": ("name",), "rows": rows}

        if lowered.startswith("create table"):
            self.created = True
            return {"columns": (), "rows": (), "query_id": "q-create"}

        if lowered.startswith("drop table"):
            self.created = False
            return {"columns": (), "rows": (), "query_id": "q-drop"}

        if lowered.startswith("desc table"):
            return {
                "columns": ("name", "type"),
                "rows": tuple({"name": column, "type": "VARCHAR"} for column in sorted(self.columns)),
            }

        if lowered.startswith("alter table"):
            if "add column source_system" in lowered:
                self.columns.add("SOURCE_SYSTEM")
            return {"columns": (), "rows": (), "query_id": "q-alter"}

        if lowered.startswith("truncate"):
            self.row_count = 0
            return {"columns": (), "rows": (), "query_id": "q-truncate"}

        if lowered.startswith("select count(*) as row_count"):
            return {"columns": ("ROW_COUNT",), "rows": ({"ROW_COUNT": self.row_count},)}

        if lowered.startswith("grant "):
            return {"columns": (), "rows": (), "query_id": "q-grant"}

        if lowered.startswith("revoke "):
            return {"columns": (), "rows": (), "query_id": "q-revoke"}

        if lowered.startswith("use "):
            return {"columns": (), "rows": (), "query_id": "q-use"}

        if lowered.startswith("call "):
            return {"columns": (), "rows": (), "query_id": "q-call"}

        if lowered.startswith("insert into"):
            return {"columns": (), "rows": (), "query_id": "q-insert"}

        if "query_history_by_session" in lowered:
            return {
                "columns": ("QUERY_ID", "EXECUTION_STATUS"),
                "rows": tuple(
                    {"QUERY_ID": query_id, "EXECUTION_STATUS": "SUCCESS"}
                    for query_id in ("q-insert", "q-grant", "q-revoke", "q-use", "q-call")
                ),
            }

        raise AssertionError(f"unexpected SQL: {sql}")


def _connector(fixture: MutationFixture | None = None) -> tuple[SnowflakeConnector, MutationFixture]:
    fixture = fixture or MutationFixture()
    return (
        SnowflakeConnector(
            fixture,
            SnowflakeConfig(database="HOTEL", schema="RAW"),
        ),
        fixture,
    )


def test_create_plan_has_exact_fingerprint_and_verification():
    result = plan_snowflake_mutation(
        "CREATE TABLE HOTEL.RAW.RESERVATIONS (ID NUMBER)",
        environment="dev",
    )

    assert result["status"] == "PASS"
    assert result["statement_type"] == "CREATE"
    assert result["object_type"] == "TABLE"
    assert result["target"] == "HOTEL.RAW.RESERVATIONS"
    assert result["risk_level"] == "safe_create"
    assert result["destructive"] is False
    assert len(result["approval_fingerprint"]) == 64
    assert result["verification_plan"][0]["sql"] == (
        "SHOW TABLES LIKE 'RESERVATIONS' IN SCHEMA HOTEL.RAW"
    )


def test_approval_fingerprint_changes_when_statement_changes():
    first = plan_snowflake_mutation(
        "ALTER TABLE HOTEL.RAW.RESERVATIONS ADD COLUMN SOURCE_SYSTEM VARCHAR",
        environment="staging",
    )
    second = plan_snowflake_mutation(
        "ALTER TABLE HOTEL.RAW.RESERVATIONS ADD COLUMN SOURCE_SYSTEM VARCHAR(50)",
        environment="staging",
    )

    assert first["approval_fingerprint"] != second["approval_fingerprint"]


def test_approval_fingerprint_preserves_string_literal_content():
    double_space = plan_snowflake_mutation(
        "INSERT INTO HOTEL.RAW.NOTES VALUES ('a  b')",
        environment="dev",
    )
    single_space = plan_snowflake_mutation(
        "INSERT INTO HOTEL.RAW.NOTES VALUES ('a b')",
        environment="dev",
    )
    comment_like_literal = plan_snowflake_mutation(
        "INSERT INTO HOTEL.RAW.NOTES VALUES ('--not-a-comment')",
        environment="dev",
    )
    ordinary_literal = plan_snowflake_mutation(
        "INSERT INTO HOTEL.RAW.NOTES VALUES ('not-a-comment')",
        environment="dev",
    )

    assert double_space["approval_fingerprint"] != single_space["approval_fingerprint"]
    assert comment_like_literal["approval_fingerprint"] != ordinary_literal["approval_fingerprint"]


def test_approval_fingerprint_ignores_comments_only_outside_literals():
    plain = plan_snowflake_mutation(
        "INSERT INTO HOTEL.RAW.NOTES VALUES ('payload')",
        environment="dev",
    )
    commented = plan_snowflake_mutation(
        "INSERT INTO HOTEL.RAW.NOTES VALUES ('payload') -- deployment note",
        environment="dev",
    )
    block_commented = plan_snowflake_mutation(
        "INSERT /* deployment note */ INTO HOTEL.RAW.NOTES VALUES ('payload')",
        environment="dev",
    )

    assert plain["approval_fingerprint"] == commented["approval_fingerprint"]
    assert plain["approval_fingerprint"] == block_commented["approval_fingerprint"]


def test_approval_fingerprint_preserves_dollar_quoted_content():
    first = plan_snowflake_mutation(
        "CALL HOTEL.RAW.PROC($body$--literal one$body$)",
        environment="dev",
    )
    second = plan_snowflake_mutation(
        "CALL HOTEL.RAW.PROC($body$--literal two$body$)",
        environment="dev",
    )

    assert first["approval_fingerprint"] != second["approval_fingerprint"]


def test_multi_statement_request_is_blocked():
    result = plan_snowflake_mutation(
        "CREATE TABLE A(ID NUMBER); DROP TABLE B",
        environment="dev",
    )
    assert result["status"] == "FAIL"
    assert result["code"] == "MULTI_STATEMENT_BLOCKED"


def test_prod_drop_is_blocked_without_break_glass(monkeypatch):
    monkeypatch.delenv("ADE_PROD_DESTRUCTIVE_BREAK_GLASS", raising=False)
    result = plan_snowflake_mutation(
        "DROP TABLE HOTEL.RAW.RESERVATIONS",
        environment="prod",
    )

    assert result["status"] == "BLOCKED_POLICY"
    assert result["destructive"] is True


def test_create_or_replace_and_unbounded_delete_are_destructive():
    replace = plan_snowflake_mutation(
        "CREATE OR REPLACE TABLE HOTEL.RAW.RESERVATIONS (ID NUMBER)",
        environment="dev",
    )
    delete = plan_snowflake_mutation(
        "DELETE FROM HOTEL.RAW.RESERVATIONS",
        environment="dev",
    )

    assert replace["destructive"] is True
    assert replace["statement_type"] == "CREATE_OR_REPLACE"
    assert delete["destructive"] is True


def test_secret_values_are_redacted_from_plan():
    result = plan_snowflake_mutation(
        "CREATE STAGE HOTEL.RAW.LANDING CREDENTIALS=(AWS_KEY_ID='abc' AWS_SECRET_KEY='xyz')",
        environment="dev",
    )

    assert result["status"] == "PASS"
    assert "abc" not in result["statement_preview"]
    assert "xyz" not in result["statement_preview"]
    assert result["statement_preview"].count("***REDACTED***") == 2


def test_create_executes_only_after_matching_approval_and_verifies():
    connector, fixture = _connector()
    executor = GovernedSnowflakeMutationExecutor(connector)
    sql = "CREATE TABLE HOTEL.RAW.RESERVATIONS (ID NUMBER)"
    plan = executor.plan(sql, environment="dev")

    mismatch = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint="wrong",
        approved=True,
    )
    assert mismatch["status"] == "BLOCKED_APPROVAL"
    assert fixture.created is False

    result = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
    )
    assert result["status"] == "PASS"
    assert result["executed"] is True
    assert result["verified"] is True
    assert result["query_id"] == "q-create"
    assert fixture.created is True


def test_destructive_drop_requires_second_confirmation_and_verifies_absence():
    connector, fixture = _connector()
    fixture.created = True
    executor = GovernedSnowflakeMutationExecutor(connector)
    sql = "DROP TABLE HOTEL.RAW.RESERVATIONS"
    plan = executor.plan(sql, environment="dev")

    blocked = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
    )
    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert blocked["code"] == "DESTRUCTIVE_CONFIRMATION_REQUIRED"
    assert fixture.created is True

    result = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
        confirm_destructive=True,
    )
    assert result["status"] == "PASS"
    assert result["verified"] is True
    assert fixture.created is False



def test_alter_table_verifies_the_requested_column_change():
    connector, fixture = _connector()
    fixture.created = True
    executor = GovernedSnowflakeMutationExecutor(connector)
    sql = "ALTER TABLE HOTEL.RAW.RESERVATIONS ADD COLUMN SOURCE_SYSTEM VARCHAR(50)"
    plan = executor.plan(sql, environment="dev")

    result = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
    )

    assert result["status"] == "PASS"
    assert "SOURCE_SYSTEM" in fixture.columns
    assert any(item["kind"] == "column_presence" and item["passed"] for item in result["verification"])


def test_truncate_requires_destructive_confirmation_and_verifies_zero_rows():
    connector, fixture = _connector()
    fixture.created = True
    executor = GovernedSnowflakeMutationExecutor(connector)
    sql = "TRUNCATE TABLE HOTEL.RAW.RESERVATIONS"
    plan = executor.plan(sql, environment="dev")

    blocked = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
    )
    assert blocked["status"] == "BLOCKED_APPROVAL"

    result = executor.execute(
        sql,
        environment="dev",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
        confirm_destructive=True,
    )
    assert result["status"] == "PASS"
    assert fixture.row_count == 0
    assert any(item["kind"] == "row_count" and item["passed"] for item in result["verification"])


def test_security_session_and_procedure_statements_are_governed():
    grant = plan_snowflake_mutation(
        "GRANT SELECT ON TABLE HOTEL.RAW.RESERVATIONS TO ROLE ANALYST",
        environment="dev",
    )
    revoke = plan_snowflake_mutation(
        "REVOKE SELECT ON TABLE HOTEL.RAW.RESERVATIONS FROM ROLE ANALYST",
        environment="dev",
    )
    use = plan_snowflake_mutation("USE ROLE ANALYST", environment="dev")
    call = plan_snowflake_mutation("CALL HOTEL.RAW.REPAIR_PIPELINE()", environment="dev")

    assert grant["risk_level"] == "security_change"
    assert grant["destructive"] is False
    assert revoke["risk_level"] == "security_change"
    assert revoke["destructive"] is True
    assert use["statement_type"] == "USE"
    assert call["statement_type"] == "CALL"

def test_mutation_dry_run_does_not_execute():
    connector, fixture = _connector()
    executor = GovernedSnowflakeMutationExecutor(connector)
    sql = "ALTER TABLE HOTEL.RAW.RESERVATIONS ADD COLUMN SOURCE_SYSTEM VARCHAR(50)"
    plan = executor.plan(sql, environment="staging")

    result = executor.execute(
        sql,
        environment="staging",
        approval_fingerprint=plan["approval_fingerprint"],
        approved=True,
        dry_run=True,
    )

    assert result["status"] == "PASS"
    assert result["mode"] == "DRY_RUN"
    assert result["executed"] is False
    assert fixture.statements == []


def test_tool_registry_blocks_analyst_and_requires_approval():
    connector, _ = _connector()
    registry = build_tool_registry()
    definition = registry.describe("snowflake_mutation_execute")
    sql = "CREATE TABLE HOTEL.RAW.RESERVATIONS (ID NUMBER)"
    plan = plan_snowflake_mutation(sql, environment="dev")
    request = ToolRequest(
        tool="snowflake_mutation_execute",
        operation="snowflake_mutation_execute",
        environment=Environment.DEV,
        risk=definition.risk,
        args={
            "sql": sql,
            "approval_fingerprint": plan["approval_fingerprint"],
            "_connector": connector,
        },
    )

    with pytest.raises(PermissionError):
        registry.invoke(
            ToolInvocation(
                request,
                run_id="analyst-write",
                actor_mode=ActorMode.ANALYST,
                approved=True,
            )
        )

    with pytest.raises(PermissionError):
        registry.invoke(
            ToolInvocation(
                request,
                run_id="builder-unapproved",
                actor_mode=ActorMode.BUILDER,
                approved=False,
            )
        )

    result = registry.invoke(
        ToolInvocation(
            request,
            run_id="builder-approved",
            actor_mode=ActorMode.BUILDER,
            approved=True,
            dry_run=True,
        )
    )
    assert result["status"] == "PASS"
    assert result["mode"] == "DRY_RUN"


def test_cli_and_api_expose_governed_snowflake_admin_surface(monkeypatch):
    assert DOMAIN_CLI_TOOLS["snowflake-admin"] == {
        "plan": "snowflake_mutation_plan",
        "execute": "snowflake_mutation_execute",
    }

    parsed = build_parser().parse_args(
        [
            "snowflake-admin",
            "execute",
            "--environment",
            "prod",
            "--builder",
            "--approved",
            "--dry-run",
            "--args",
            '{"sql":"CREATE TABLE HOTEL.RAW.T(ID NUMBER)","approval_fingerprint":"x"}',
        ]
    )
    assert parsed.environment == "prod"
    assert parsed.builder is True
    assert parsed.approved is True
    assert parsed.dry_run is True

    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert {
        item["tool"] for item in domains.json()["snowflake-admin"].values()
    } == {"snowflake_mutation_plan", "snowflake_mutation_execute"}

    response = client.post(
        "/api/v1/snowflake-admin/plan",
        json={
            "args": {"sql": "CREATE TABLE HOTEL.RAW.T(ID NUMBER)"},
            "environment": "dev",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PASS"

    for name in ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    execute = client.post(
        "/api/v1/snowflake-admin/execute",
        json={
            "args": {
                "sql": "CREATE TABLE HOTEL.RAW.T(ID NUMBER)",
                "approval_fingerprint": response.json()["approval_fingerprint"],
            },
            "actor_mode": "builder",
            "environment": "dev",
            "approved": True,
            "dry_run": True,
        },
    )
    assert execute.status_code == 200
    assert execute.json()["status"] == "PASS"
    assert execute.json()["mode"] == "DRY_RUN"
    assert execute.json()["executed"] is False

    direct = client.post(
        "/tools/snowflake_mutation_execute",
        json={
            "args": {
                "sql": "CREATE TABLE HOTEL.RAW.T(ID NUMBER)",
                "approval_fingerprint": response.json()["approval_fingerprint"],
            },
            "actor_mode": "builder",
            "environment": "dev",
            "approved": True,
            "dry_run": True,
        },
    )
    assert direct.status_code == 200
    assert direct.json()["status"] == "PASS"
    assert direct.json()["mode"] == "DRY_RUN"
