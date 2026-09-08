from pathlib import Path

from agentic_data_platform.models import ActorMode
from agentic_data_platform.providers.mock import ScriptedProvider
from agentic_data_platform.providers.base import ProviderResponse
from agentic_data_platform.runtime.agent import AgentRuntime
from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tracing.store import TraceStore


def test_runtime_emits_incremental_generation_events(tmp_path: Path):
    store = RuntimeStore(tmp_path / "runtime.db")
    traces = TraceStore(tmp_path / "traces.db")
    session_id = store.create_session()
    provider = ScriptedProvider([ProviderResponse(content="done", finish_reason="stop")])
    events = []
    result = AgentRuntime(build_tool_registry(), store, traces).run(
        session_id,
        "hello",
        provider,
        "scripted",
        actor_mode=ActorMode.ANALYST,
        event_handler=events.append,
    )
    assert result["response"] == "done"
    names = [item["event"] for item in events]
    assert names[0] == "session.started"
    assert "generation.started" in names
    assert "generation.finished" in names
    assert names[-1] == "session.finished"
