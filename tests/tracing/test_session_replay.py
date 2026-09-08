from agentic_data_platform.runtime.replay import replay_session
from agentic_data_platform.runtime.store import RuntimeStore
from agentic_data_platform.tracing.store import TraceStore


def test_session_replay_is_read_only_and_aggregates_usage(tmp_path):
    store = RuntimeStore(tmp_path / "runtime.db")
    traces = TraceStore(tmp_path / "traces.db")
    session_id = store.create_session(provider="demo", model="demo")
    store.add_message(session_id, "user", "hello")
    store.add_message(session_id, "assistant", "done")
    generation = store.add_generation(session_id, "demo", "demo", "stop", {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
    call = store.start_tool_call(session_id, generation, "sql_classify", {"sql": "select 1"})
    store.finish_tool_call(call, {"status": "PASS"}, "SUCCESS")
    result = replay_session(store, traces, session_id)
    assert result["read_only"] is True
    assert result["reexecuted"] is False
    assert result["token_totals"]["total_tokens"] == 8
    assert result["final_outcome"] == "done"
