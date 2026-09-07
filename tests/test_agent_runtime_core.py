from __future__ import annotations
import pytest
from agentic_data_platform.models import ActorMode
from agentic_data_platform.providers import ProviderResponse, ScriptedProvider, ToolCall, Usage
from agentic_data_platform.runtime import AgentLoopError, AgentRuntime, ContextManager, RuntimeStore
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tracing import TraceStore

def test_runtime_executes_tool_loop(tmp_path):
    store=RuntimeStore(tmp_path/"runtime.db"); traces=TraceStore(tmp_path/"trace.db"); session=store.create_session()
    provider=ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("sql_classify",{"sql":"SELECT 1"},"c1"),),usage=Usage(10,2)),
        ProviderResponse(content="read only",usage=Usage(20,4),finish_reason="stop")])
    result=AgentRuntime(build_tool_registry(),store,traces).run(session,"safe?",provider,"test")
    assert result["response"]=="read only"
    assert [m["role"] for m in store.messages(session)]==["user","tool","assistant"]
    assert any(e["kind"]=="tool" for e in traces.list(trace_id=result["trace_id"]))

def test_runtime_denies_mutation_for_analyst(tmp_path):
    store=RuntimeStore(tmp_path/"runtime.db"); traces=TraceStore(tmp_path/"trace.db"); session=store.create_session()
    provider=ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("migration_convert_model",{"sql":"SELECT 1","model_name":"x.sql"},"c1"),)),
        ProviderResponse(content="denied")])
    result=AgentRuntime(build_tool_registry(),store,traces).run(session,"change",provider,"test",actor_mode=ActorMode.ANALYST)
    assert result["response"]=="denied"
    assert "PermissionError" in [m for m in store.messages(session) if m["role"]=="tool"][0]["content"]

def test_loop_detection(tmp_path):
    store=RuntimeStore(tmp_path/"runtime.db"); traces=TraceStore(tmp_path/"trace.db"); session=store.create_session()
    repeated=ProviderResponse(tool_calls=(ToolCall("sql_classify",{"sql":"SELECT 1"},"same"),))
    with pytest.raises(AgentLoopError):
        AgentRuntime(build_tool_registry(),store,traces,repeated_tool_limit=2).run(
            session,"loop",ScriptedProvider([repeated,repeated,repeated]),"test")

def test_context_compacts():
    manager=ContextManager(max_tokens=100,reserve_tokens=20)
    messages=[{"role":"user","content":"x"*250},{"role":"assistant","content":"y"*250}]
    compacted,meta=manager.compact(messages)
    assert meta["compacted"] is True
    assert len(compacted)<=3
