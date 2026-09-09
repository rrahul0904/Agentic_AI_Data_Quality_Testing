from __future__ import annotations

import threading

from agentic_data_platform.agents.parallel import (
    ParallelSubagentCoordinator,
    RuntimeSubagentExecutor,
    SubagentDefinition,
    SubagentRegistry,
    SubagentTask,
)
from agentic_data_platform.models import Capability, Platform, Risk
from agentic_data_platform.providers import ScriptedProvider
from agentic_data_platform.runtime import AgentRuntime, RuntimeStore
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry
from agentic_data_platform.tracing import TraceStore


def test_subagent_registry_discovers_project_markdown_definitions(tmp_path):
    folder = tmp_path / ".ade" / "agents"
    folder.mkdir(parents=True)
    (folder / "snowflake.md").write_text(
        """---
name: snowflake-investigator
description: Investigate Snowflake ingestion failures.
tools:
  - semantic_search
  - snowflake_pipeline_rca
actor_mode: analyst
max_steps: 6
timeout_seconds: 90
---
Use deterministic warehouse evidence before drawing conclusions.
"""
    )

    registry = SubagentRegistry.discover(tmp_path)
    items = registry.list()

    assert len(items) == 1
    assert items[0]["name"] == "snowflake-investigator"
    assert items[0]["allowed_tools"] == ["semantic_search", "snowflake_pipeline_rca"]
    assert items[0]["max_steps"] == 6
    assert "deterministic warehouse evidence" in items[0]["system_prompt"]


def test_parallel_coordinator_executes_tasks_concurrently():
    barrier = threading.Barrier(2, timeout=2)

    def execute(task: SubagentTask):
        barrier.wait()
        return {"status": "PASS", "summary": f"finished {task.definition.name}"}

    coordinator = ParallelSubagentCoordinator(execute, max_workers=2)
    result = coordinator.run([
        SubagentTask(SubagentDefinition("a", "first"), "inspect snowflake"),
        SubagentTask(SubagentDefinition("b", "second"), "inspect airflow"),
    ])

    assert result["status"] == "PASS"
    assert result["task_count"] == 2
    assert [item["name"] for item in result["results"]] == ["a", "b"]


def test_parallel_coordinator_isolates_one_subagent_failure():
    def execute(task: SubagentTask):
        if task.definition.name == "broken":
            raise RuntimeError("boom")
        return {"status": "PASS", "summary": "ok"}

    result = ParallelSubagentCoordinator(execute, max_workers=3).run([
        SubagentTask(SubagentDefinition("snowflake", "warehouse"), "inspect"),
        SubagentTask(SubagentDefinition("broken", "failure"), "inspect"),
        SubagentTask(SubagentDefinition("dbt", "transform"), "inspect"),
    ])

    assert result["status"] == "FAIL"
    assert result["failed_count"] == 1
    assert result["results"][0]["status"] == "PASS"
    assert result["results"][1]["status"] == "FAIL"
    assert "RuntimeError" in result["results"][1]["error"]
    assert result["results"][2]["status"] == "PASS"


def test_runtime_subagent_registry_is_hard_scoped_to_allowed_tools(tmp_path):
    registry = ToolRegistry()
    for name in ("semantic_search", "snowflake_pipeline_rca", "snowflake_mutation_execute"):
        registry.register(ToolDefinition(
            name=name,
            capability=Capability.DISCOVER,
            risk=Risk.READ_ONLY,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: {"status": "PASS"},
            description=name,
        ))

    runtime = AgentRuntime(
        registry,
        RuntimeStore(tmp_path / "runtime.db"),
        TraceStore(tmp_path / "trace.db"),
    )
    executor = RuntimeSubagentExecutor(
        runtime,
        lambda definition: ScriptedProvider([]),
        project_root=tmp_path,
    )
    definition = SubagentDefinition(
        "investigator",
        "read-only investigator",
        allowed_tools=("semantic_search", "snowflake_pipeline_rca"),
    )

    scoped = executor._scoped_registry(definition)
    names = {item.name for item in scoped.definitions()}

    assert names == {"semantic_search", "snowflake_pipeline_rca"}
    assert "snowflake_mutation_execute" not in names
