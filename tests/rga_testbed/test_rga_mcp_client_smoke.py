from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    return load_module(
        "rga_mcp_client_smoke_test",
        ROOT / "scripts" / "rga_testbed" / "smoke_snowflake_mcp.py",
    )


def test_mcp_endpoint_builder_matches_snowflake_managed_endpoint():
    module = _module()
    assert module.build_endpoint(
        endpoint=None,
        account_url="acct.snowflakecomputing.com",
        database="DB NAME",
        schema="AI",
        server="RGA MCP",
    ) == (
        "https://acct.snowflakecomputing.com/api/v2/databases/DB%20NAME/"
        "schemas/AI/mcp-servers/RGA%20MCP"
    )


def test_mcp_live_mode_is_fail_closed_without_oauth_or_confirm():
    module = _module()
    errors = module.validate_request(
        endpoint="https://acct.snowflakecomputing.com/api/v2/databases/DB/schemas/AI/mcp-servers/MCP",
        expected_tool="governed_agent",
        question="What is revenue?",
        token_env="SNOWFLAKE_MCP_ACCESS_TOKEN",
        env={},
        timeout=120,
        confirm=False,
        dry_run=False,
    )
    assert "OAuth bearer token is required in SNOWFLAKE_MCP_ACCESS_TOKEN" in errors
    assert "Refusing live Snowflake MCP invocation without --confirm" in errors


def test_mcp_dry_run_requires_no_token_and_documents_sse_transport():
    module = _module()
    endpoint = "https://acct.snowflakecomputing.com/api/v2/databases/DB/schemas/AI/mcp-servers/MCP"
    assert module.validate_request(
        endpoint=endpoint,
        expected_tool="governed_agent",
        question="What is revenue?",
        token_env="SNOWFLAKE_MCP_ACCESS_TOKEN",
        env={},
        timeout=120,
        confirm=False,
        dry_run=True,
    ) == []
    plan = module.plan(
        endpoint=endpoint,
        expected_tool="governed_agent",
        question="What is revenue?",
        token_env="SNOWFLAKE_MCP_ACCESS_TOKEN",
        timeout=120,
    )
    assert plan["status"] == "DRY_RUN"
    assert [item["method"] for item in plan["requests"]] == [
        "tools/list",
        "tools/call",
    ]
    assert all(
        item["accept"] == "application/json, text/event-stream"
        for item in plan["requests"]
    )
    assert plan["evidence_policy"]["persist_oauth_token"] is False
    assert plan["evidence_policy"]["persist_agent_reasoning"] is False


def test_mcp_sse_parser_handles_done_and_multiple_events():
    module = _module()
    payload = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":2,"result":{"content":[]}}\n\n'
        'data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"ok"}]}}\n\n'
        'data: [DONE]\n'
    )
    events = module.parse_sse(payload)
    assert len(events) == 2
    assert events[-1]["result"]["content"][0]["text"] == "ok"


def test_mcp_tools_list_evidence_is_metadata_only():
    module = _module()
    tools = module.tools_from_result(
        {
            "tools": [
                {
                    "name": "governed_agent",
                    "title": "Governed Agent",
                    "description": "Answers business questions",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                }
            ]
        }
    )
    assert tools[0]["name"] == "governed_agent"
    assert tools[0]["title"] == "Governed Agent"
    assert "description" not in tools[0]
    assert tools[0]["description_sha256"]
    assert tools[0]["input_schema_sha256"]


def test_mcp_smoke_invokes_discovered_tool_without_persisting_raw_result(monkeypatch):
    module = _module()
    calls = []

    def fake_post(*, endpoint, token, payload, timeout):
        assert token == "oauth-secret"
        request = json.loads(payload)
        calls.append(request)
        if request["method"] == "tools/list":
            return {
                "http_status": 200,
                "content_type": "application/json",
                "transport": "json",
                "response_sha256": "list-hash",
                "request_id": "req-list",
                "event_count": 1,
                "events": [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "tools": [
                                {
                                    "name": "governed_agent",
                                    "description": "Governed agent",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"message": {"type": "string"}},
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        return {
            "http_status": 200,
            "content_type": "text/event-stream",
            "transport": "sse",
            "response_sha256": "call-hash",
            "request_id": "req-call",
            "event_count": 1,
            "events": [
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "content": [
                            {"type": "text", "text": "private intermediate and final payload"}
                        ]
                    },
                }
            ],
        }

    monkeypatch.setattr(module, "_post", fake_post)
    evidence = module.smoke(
        endpoint="https://acct.example/mcp",
        token="oauth-secret",
        expected_tool="governed_agent",
        question="What is governed revenue?",
        timeout=120,
    )

    assert evidence["status"] == "PASS"
    assert evidence["expected_tool"] == "governed_agent"
    assert evidence["tools_call"]["transport"] == "sse"
    assert evidence["tools_call"]["result_present"] is True
    assert evidence["oauth"] == {
        "token_present": True,
        "token_persisted": False,
    }
    serialized = json.dumps(evidence)
    assert "oauth-secret" not in serialized
    assert "private intermediate" not in serialized
    assert evidence["reasoning_persisted"] is False
    assert calls[1]["params"] == {
        "name": "governed_agent",
        "arguments": {"message": "What is governed revenue?"},
    }
