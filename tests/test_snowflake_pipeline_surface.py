from __future__ import annotations

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS, build_parser
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


EXPECTED_TOOLS = {
    "snowflake_copy_analyze",
    "snowflake_pipe_inventory",
    "snowflake_pipe_status",
    "snowflake_pipe_validate",
    "snowflake_stream_inventory",
    "snowflake_stream_status",
    "snowflake_copy_history",
    "snowflake_copy_validate",
    "snowflake_table_quality",
    "snowflake_pipeline_health",
}


def test_snowflake_pipeline_tools_are_registered():
    registry = build_tool_registry()
    assert EXPECTED_TOOLS <= {definition.name for definition in registry.definitions()}


def test_snowflake_pipeline_cli_domain_is_complete():
    assert set(DOMAIN_CLI_TOOLS["snowflake-test"].values()) == EXPECTED_TOOLS
    parsed = build_parser().parse_args([
        "snowflake-test",
        "copy-analyze",
        "--args",
        '{"sql":"COPY INTO RAW.T FROM @STAGE ON_ERROR=ABORT_STATEMENT"}',
    ])
    assert parsed.command == "snowflake-test"
    assert parsed.operation == "copy-analyze"


def test_snowflake_pipeline_api_domain_and_static_copy_analysis():
    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert set(item["tool"] for item in domains.json()["snowflake-testing"].values()) == EXPECTED_TOOLS

    response = client.post(
        "/api/v1/snowflake-testing/copy-analyze",
        json={"args": {"sql": "COPY INTO RAW.T FROM @STAGE FILE_FORMAT=(TYPE=CSV) ON_ERROR=ABORT_STATEMENT"}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PASS"


def test_live_snowflake_tools_skip_external_without_credentials(monkeypatch):
    for name in ("ADE_SNOWFLAKE_ACCOUNT", "ADE_SNOWFLAKE_USER", "ADE_SNOWFLAKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    registry = build_tool_registry()
    definition = registry.describe("snowflake_pipe_inventory")
    request = ToolRequest(
        "snowflake_pipe_inventory",
        "snowflake_pipe_inventory",
        Environment.DEV,
        definition.risk,
        args={},
    )
    result = registry.invoke(
        ToolInvocation(
            request,
            run_id="snowflake-pipeline-no-credentials",
            actor_mode=ActorMode.ANALYST,
        )
    )
    assert result["status"] == "SKIP_EXTERNAL"
    assert result["platform"] == "snowflake"
