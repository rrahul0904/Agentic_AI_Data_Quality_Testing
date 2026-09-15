from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agentic_data_platform.acp_server import ADEACPAgent
from agentic_data_platform.models import Capability, Platform, Risk
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry


class FakeACPConnection:
    def __init__(self, *, allow: bool = True):
        self.allow = allow
        self.permission_requests = []
        self.updates = []

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        self.permission_requests.append((session_id, tool_call, options, kwargs))
        if self.allow:
            outcome = SimpleNamespace(outcome="selected", option_id="allow_once")
        else:
            outcome = SimpleNamespace(outcome="cancelled", option_id=None)
        return SimpleNamespace(outcome=outcome)

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append((session_id, update, kwargs))


def _registry(observed):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="acp_mutation",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            requires_approval=True,
            handler=lambda args: observed.append(dict(args)) or {"changed": args["value"]},
        )
    )
    return registry


def test_acp_permission_bridge_executes_only_the_exact_approved_fingerprint(tmp_path):
    observed = []
    connection = FakeACPConnection(allow=True)
    agent = ADEACPAgent(registry=_registry(observed))
    agent.on_connect(connection)
    session = asyncio.run(agent.new_session(cwd=str(tmp_path), mcp_servers=[]))

    result = asyncio.run(
        agent.ext_method(
            "ade/tool/invoke",
            {
                "sessionId": session.session_id,
                "tool": "acp_mutation",
                "args": {"value": 7, "token": "sk-abcdefghijklmnop"},
                "platform": "local",
            },
        )
    )

    assert result["status"] == "PASS"
    assert result["acp_permission"] == "allow_once"
    assert len(result["approval_fingerprint"]) == 64
    assert observed and observed[0]["value"] == 7
    assert observed[0]["_approved"] is True
    assert len(connection.permission_requests) == 1
    _, tool_call, options, _ = connection.permission_requests[0]
    assert "Approve ADE tool" in tool_call.title
    assert tool_call.raw_input["args"]["token"] == "[REDACTED]"
    assert {option.option_id for option in options} == {"allow_once", "deny"}


def test_acp_permission_denial_fails_closed_without_mutation(tmp_path):
    observed = []
    connection = FakeACPConnection(allow=False)
    agent = ADEACPAgent(registry=_registry(observed))
    agent.on_connect(connection)
    session = asyncio.run(agent.new_session(cwd=str(tmp_path), mcp_servers=[]))

    result = asyncio.run(
        agent.ext_method(
            "ade/tool/invoke",
            {
                "sessionId": session.session_id,
                "tool": "acp_mutation",
                "args": {"value": 9},
                "platform": "local",
            },
        )
    )

    assert result["status"] == "DENIED"
    assert result["acp_permission"] == "denied"
    assert observed == []


def test_acp_delivers_completed_response_as_bounded_message_chunks(tmp_path):
    connection = FakeACPConnection()
    agent = ADEACPAgent()
    agent.on_connect(connection)
    session = asyncio.run(agent.new_session(cwd=str(tmp_path), mcp_servers=[]))

    emitted = asyncio.run(agent._emit_message_chunks(session.session_id, "x" * 2505, chunk_chars=1000))
    assert emitted is True
    assert len(connection.updates) == 3
    lengths = [len(item[1].content.text) for item in connection.updates]
    assert lengths == [1000, 1000, 505]

    evidence = asyncio.run(agent.ext_method("ade/session/evidence", {"sessionId": session.session_id}))
    assert evidence["streaming"] == "buffered_acp_message_chunks"
    assert evidence["providerCancellation"] == "not_supported_by_current_provider_runtime"