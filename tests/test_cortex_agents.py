from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.cortex import CortexAgentClient
from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def test_cortex_agent_create_plan_matches_current_rest_contract():
    client = CortexAgentClient(account_url="", token="")
    specification = {
        "name": "hospitality_agent",
        "comment": "Hospitality operations agent",
        "tools": [
            {
                "tool_spec": {
                    "type": "cortex_analyst_text_to_sql",
                    "name": "Analyst1",
                    "description": "Hospitality semantic analyst",
                }
            }
        ],
    }

    plan = client.plan_create(
        "HOTEL",
        "AI",
        specification,
        create_mode="ifNotExists",
    )

    assert plan == {
        "status": "PASS",
        "method": "POST",
        "path": "/api/v2/databases/HOTEL/schemas/AI/agents",
        "query": {"createMode": "ifNotExists"},
        "request": specification,
    }


def test_cortex_agent_offline_crud_returns_honest_external_skip():
    client = CortexAgentClient(account_url="", token="")

    listed = client.list("HOTEL", "AI")
    shown = client.describe("HOTEL", "AI", "hospitality_agent")
    created = client.create("HOTEL", "AI", {"name": "hospitality_agent"})

    assert listed["status"] == "SKIP_EXTERNAL"
    assert listed["method"] == "GET"
    assert shown["endpoint"].endswith("/HOTEL/schemas/AI/agents/hospitality_agent")
    assert created["status"] == "SKIP_EXTERNAL"
    assert created["method"] == "POST"


def test_cortex_thread_contract_and_background_run_validation():
    client = CortexAgentClient(account_url="", token="")

    created = client.create_thread(origin_application="ade")
    assert created["status"] == "SKIP_EXTERNAL"
    assert created["endpoint"].endswith("/api/v2/cortex/threads")

    with pytest.raises(ValueError, match="require a thread_id"):
        client.build_run_request(
            "Diagnose the reservation pipeline",
            background=True,
        )

    request = client.build_run_request(
        "Diagnose the reservation pipeline",
        thread_id=1234,
        parent_message_id=0,
        tool_names=["Analyst1", "Search1"],
        background=True,
        stream=False,
    )
    assert request["thread_id"] == 1234
    assert request["parent_message_id"] == 0
    assert request["background"] is True
    assert request["stream"] is False
    assert request["tool_choice"] == {
        "type": "required",
        "name": ["Analyst1", "Search1"],
    }


def test_cortex_agent_run_offline_preserves_full_request_for_certification():
    client = CortexAgentClient(account_url="", token="")

    result = client.run(
        "HOTEL",
        "AI",
        "hospitality_agent",
        "Why did RevPAR fall?",
        thread_id=99,
        tool_names=["Analyst1"],
        background=True,
    )

    assert result["status"] == "SKIP_EXTERNAL"
    assert result["endpoint"].endswith("/HOTEL/schemas/AI/agents/hospitality_agent:run")
    assert result["request"]["messages"][0]["content"][0]["text"] == "Why did RevPAR fall?"
    assert result["request"]["background"] is True


def test_cortex_agent_mutation_tools_require_builder_and_approval():
    registry = build_tool_registry()
    definition = registry.describe("cortex_agent_create")
    request = ToolRequest(
        tool="cortex_agent_create",
        operation="cortex_agent_create",
        environment=Environment.DEV,
        risk=definition.risk,
        args={
            "database": "HOTEL",
            "schema": "AI",
            "specification": {"name": "hospitality_agent"},
            "account_url": "",
            "token": "",
        },
    )

    with pytest.raises(PermissionError):
        registry.invoke(
            ToolInvocation(
                request,
                run_id="analyst-create",
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
        )
    )
    assert result["status"] == "SKIP_EXTERNAL"


def test_cortex_agent_surfaces_are_exposed():
    assert set(DOMAIN_CLI_TOOLS["cortex-agent"]) == {
        "create-plan",
        "create",
        "list",
        "show",
        "update",
        "delete",
        "run-plan",
        "run",
        "feedback",
        "thread-create",
        "thread-list",
        "thread-show",
        "thread-update",
        "thread-delete",
    }

    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert set(domains.json()["cortex-agent"]) == set(DOMAIN_CLI_TOOLS["cortex-agent"])

    plan = client.post(
        "/api/v1/cortex-agent/create-plan",
        json={
            "args": {
                "database": "HOTEL",
                "schema": "AI",
                "specification": {"name": "hospitality_agent"},
            }
        },
    )
    assert plan.status_code == 200
    assert plan.json()["status"] == "PASS"
