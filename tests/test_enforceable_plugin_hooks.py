from __future__ import annotations

from agentic_data_platform.models import ActorMode, Capability, Platform, Risk
from agentic_data_platform.plugins.manager import PluginManager
from agentic_data_platform.providers import ProviderResponse, ScriptedProvider, ToolCall
from agentic_data_platform.runtime import AgentRuntime, RuntimeStore
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry
from agentic_data_platform.tracing import TraceStore


def _runtime(tmp_path, registry: ToolRegistry, plugins: PluginManager) -> tuple[AgentRuntime, RuntimeStore, str]:
    store = RuntimeStore(tmp_path / "runtime.db")
    traces = TraceStore(tmp_path / "trace.db")
    session = store.create_session()
    return AgentRuntime(registry, store, traces, plugins=plugins), store, session


def test_plugin_manager_can_modify_enforceable_payload():
    plugins = PluginManager()
    plugins.register(
        "defaults",
        "tool.before",
        lambda payload: {"action": "modify", "updates": {"args": {**payload["args"], "limit": 10}}},
    )
    decision = plugins.evaluate("tool.before", {"tool": "x", "args": {"query": "hotel"}})

    assert decision.blocked is False
    assert decision.modified is True
    assert decision.payload["args"]["limit"] == 10


def test_runtime_hook_can_block_tool_before_execution(tmp_path):
    calls: list[dict] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_tool",
        capability=Capability.DISCOVER,
        risk=Risk.READ_ONLY,
        supported_platforms=frozenset({Platform.LOCAL}),
        handler=lambda args: calls.append(dict(args)) or {"status": "PASS"},
        description="read tool",
    ))
    plugins = PluginManager()
    plugins.register(
        "policy",
        "tool.before",
        lambda payload: {"action": "block", "reason": "blocked by project policy"},
    )
    runtime, store, session = _runtime(tmp_path, registry, plugins)
    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("read_tool", {"query": "x"}, "c1"),)),
        ProviderResponse(content="blocked"),
    ])

    result = runtime.run(session, "run it", provider, "test")

    assert result["response"] == "blocked"
    assert calls == []
    tool_message = [item for item in store.messages(session) if item["role"] == "tool"][0]
    assert "PermissionError" in tool_message["content"]
    assert "blocked by project policy" in tool_message["content"]


def test_runtime_hook_can_modify_safe_tool_arguments(tmp_path):
    calls: list[dict] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_tool",
        capability=Capability.DISCOVER,
        risk=Risk.READ_ONLY,
        supported_platforms=frozenset({Platform.LOCAL}),
        handler=lambda args: calls.append(dict(args)) or {"status": "PASS", "args": dict(args)},
        description="read tool",
    ))
    plugins = PluginManager()
    plugins.register(
        "defaults",
        "tool.before",
        lambda payload: {
            "action": "modify",
            "updates": {"args": {**payload["args"], "limit": 5}},
        },
    )
    runtime, _, session = _runtime(tmp_path, registry, plugins)
    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("read_tool", {"query": "reservation"}, "c1"),)),
        ProviderResponse(content="done"),
    ])

    runtime.run(session, "search", provider, "test")

    assert calls == [{"query": "reservation", "limit": 5, "_run_id": session, "_dry_run": False, "_approved": False, "_environment": "dev", "_actor_mode": "analyst"}]


def test_hook_argument_rewrite_invalidates_existing_mutation_approval(tmp_path):
    calls: list[dict] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="write_tool",
        capability=Capability.EXECUTE,
        risk=Risk.MUTATING,
        supported_platforms=frozenset({Platform.LOCAL}),
        handler=lambda args: calls.append(dict(args)) or {"status": "PASS"},
        requires_approval=True,
        description="approval-gated write",
    ))
    plugins = PluginManager()
    plugins.register(
        "rewrite",
        "tool.before",
        lambda payload: {
            "action": "modify",
            "updates": {"args": {**payload["args"], "value": "changed-after-approval"}},
        },
    )
    runtime, store, session = _runtime(tmp_path, registry, plugins)
    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("write_tool", {"value": "approved-value"}, "c1"),)),
        ProviderResponse(content="needs reapproval"),
    ])

    result = runtime.run(
        session,
        "change it",
        provider,
        "test",
        actor_mode=ActorMode.BUILDER,
        approved_tools={"write_tool"},
    )

    assert result["response"] == "needs reapproval"
    assert calls == []
    tool_message = [item for item in store.messages(session) if item["role"] == "tool"][0]
    assert "PermissionError" in tool_message["content"]
    assert "approval" in tool_message["content"].casefold()


def test_permission_hook_can_veto_an_approved_tool(tmp_path):
    calls: list[dict] = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        "write_tool",
        Capability.EXECUTE,
        Risk.MUTATING,
        lambda args: calls.append(dict(args)) or {"status": "PASS"},
        "approval-gated write",
        frozenset({Platform.LOCAL}),
        requires_approval=True,
    ))
    plugins = PluginManager()
    plugins.register(
        "prod-freeze",
        "permission.before",
        lambda payload: {"action": "block", "reason": "change freeze"},
    )
    runtime, store, session = _runtime(tmp_path, registry, plugins)
    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("write_tool", {"value": 1}, "c1"),)),
        ProviderResponse(content="blocked"),
    ])

    runtime.run(
        session,
        "write",
        provider,
        "test",
        actor_mode=ActorMode.BUILDER,
        approved_tools={"write_tool"},
    )

    assert calls == []
    tool_message = [item for item in store.messages(session) if item["role"] == "tool"][0]
    assert "change freeze" in tool_message["content"]
