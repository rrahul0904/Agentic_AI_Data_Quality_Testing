from __future__ import annotations

import time

import pytest

from agentic_data_platform.models import ActorMode, Environment, ToolRequest
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation
from agentic_data_platform.tracing import TraceStore


def invoke(registry, name, args, *, actor=ActorMode.BUILDER):
    definition = registry.describe(name)
    request = ToolRequest(
        tool=name,
        operation=name,
        environment=Environment.DEV,
        risk=definition.risk,
        args=args,
    )
    return registry.invoke(
        ToolInvocation(
            request=request,
            run_id=f"test-{name}",
            actor_mode=actor,
        )
    )


def test_session_and_memory_tools_persist_through_registry(tmp_path):
    registry = build_tool_registry()
    common = {"project": str(tmp_path)}

    session = invoke(
        registry,
        "session_create",
        {**common, "title": "Parity session"},
    )
    session_id = session["session_id"]
    invoke(
        registry,
        "session_message_add",
        {
            **common,
            "session_id": session_id,
            "role": "user",
            "content": "Review reservation lineage",
        },
    )
    invoke(
        registry,
        "session_todo_add",
        {**common, "session_id": session_id, "text": "verify CI"},
    )

    # Read surfaces are available to Analyst mode.
    status = invoke(
        registry,
        "session_status",
        {**common, "session_id": session_id},
        actor=ActorMode.ANALYST,
    )
    assert status["title"] == "Parity session"
    projected = invoke(
        registry,
        "session_show",
        {**common, "session_id": session_id},
        actor=ActorMode.ANALYST,
    )
    assert projected["role_counts"]["user"] == 1
    assert projected["todos"][0]["text"] == "verify CI"

    saved = invoke(
        registry,
        "memory_save",
        {
            **common,
            "content": "fact_reservation grain is reservation_id",
            "project_id": "hotel",
            "tags": ["reservation"],
        },
    )
    found = invoke(
        registry,
        "memory_search",
        {
            **common,
            "query": "reservation",
            "project_id": "hotel",
        },
        actor=ActorMode.ANALYST,
    )
    assert found["memories"][0]["memory_id"] == saved["memory_id"]


def test_session_read_write_permissions_are_separated(tmp_path):
    registry = build_tool_registry()
    session = invoke(
        registry,
        "session_create",
        {"project": str(tmp_path)},
    )
    session_id = session["session_id"]

    # Analyst can read but cannot mutate.
    assert invoke(
        registry,
        "session_state",
        {"project": str(tmp_path), "session_id": session_id},
        actor=ActorMode.ANALYST,
    ) == {}

    definition = registry.describe("session_state_patch")
    request = ToolRequest(
        tool="session_state_patch",
        operation="session_state_patch",
        environment=Environment.DEV,
        risk=definition.risk,
        args={
            "project": str(tmp_path),
            "session_id": session_id,
            "patch": {"phase": "test"},
        },
    )
    with pytest.raises(PermissionError):
        registry.invoke(
            ToolInvocation(
                request=request,
                run_id="analyst-write",
                actor_mode=ActorMode.ANALYST,
            )
        )

    updated = invoke(
        registry,
        "session_state_patch",
        {
            "project": str(tmp_path),
            "session_id": session_id,
            "patch": {"phase": "test"},
        },
    )
    assert updated["phase"] == "test"


def test_trace_tools_export_tree_and_recorded_replay(tmp_path):
    trace_path = tmp_path / ".ade" / "traces.db"
    store = TraceStore(trace_path)
    root = store.start(
        "session",
        "agent.run",
        trace_id="trace-fixture",
        session_id="session-fixture",
        payload={"context_sources": {"memory_ids": ["m1"]}},
    )
    tool = store.start(
        "tool",
        "sql_classify",
        trace_id="trace-fixture",
        session_id="session-fixture",
        parent_id=root,
        payload={"args": {"sql": "SELECT 1"}, "risk": "read_only"},
    )
    store.finish(tool, "SUCCESS", {"result": {"read_only": True}})
    store.finish(root, "SUCCESS", {"steps": 1})

    registry = build_tool_registry()
    common = {
        "project": str(tmp_path),
        "trace_database": str(trace_path),
    }
    listed = invoke(
        registry,
        "trace_list",
        common,
        actor=ActorMode.ANALYST,
    )
    assert listed["traces"][0]["trace_id"] == "trace-fixture"
    shown = invoke(
        registry,
        "trace_show",
        {**common, "trace_id": "trace-fixture"},
        actor=ActorMode.ANALYST,
    )
    assert shown["event_count"] == 2
    replay = invoke(
        registry,
        "trace_replay",
        {**common, "trace_id": "trace-fixture"},
        actor=ActorMode.ANALYST,
    )
    assert replay["reexecuted"] is False
    exported = invoke(
        registry,
        "trace_export",
        {**common, "trace_id": "trace-fixture", "format": "html"},
        actor=ActorMode.ANALYST,
    )
    assert "<html>" in exported["content"].casefold()


def test_background_jobs_accept_read_only_tools_and_refuse_mutations(tmp_path):
    registry = build_tool_registry()
    common = {
        "project": str(tmp_path),
        "job_database": str(tmp_path / ".ade" / "jobs.db"),
    }
    queued = invoke(
        registry,
        "job_submit",
        {
            **common,
            "tool": "sql_classify",
            "args": {"sql": "SELECT 1"},
        },
    )
    job_id = queued["job_id"]
    for _ in range(200):
        current = invoke(
            registry,
            "job_show",
            {**common, "job_id": job_id},
            actor=ActorMode.ANALYST,
        )
        if current["status"] in {"SUCCESS", "FAILED"}:
            break
        time.sleep(0.01)
    assert current["status"] == "SUCCESS"
    assert current["result"]["query_type"] == "read"
    assert current["result"]["blocked"] is False

    with pytest.raises(PermissionError):
        invoke(
            registry,
            "job_submit",
            {
                **common,
                "tool": "memory_save",
                "args": {"content": "should not run"},
            },
        )


def test_overflow_registered_tool_executes_for_analyst():
    registry = build_tool_registry()
    result = invoke(registry, "session_overflow", {"messages": [{"role": "user", "content": "hello"}]},
                    actor=ActorMode.ANALYST)
    assert result["status"] == "PASS"
    assert result["overflow"] is False
