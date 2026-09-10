from __future__ import annotations

import pytest

from agentic_data_platform.models import (
    ActorMode,
    Environment,
    InteractionMode,
    Risk,
    ToolRequest,
)
from agentic_data_platform.runtime.agent import AgentRuntime
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def _names(registry, mode: InteractionMode) -> set[str]:
    return {definition.name for definition in registry.definitions_for_mode(mode)}


def test_ask_and_plan_interaction_modes_expose_only_read_only_tools():
    registry = build_tool_registry()
    for mode in (InteractionMode.ASK, InteractionMode.PLAN):
        definitions = registry.definitions_for_mode(mode)
        assert definitions
        assert all(item.risk is Risk.READ_ONLY for item in definitions)


def test_edit_mode_allows_selected_region_mutation_but_not_whole_file_mutation():
    registry = build_tool_registry()
    names = _names(registry, InteractionMode.EDIT)

    assert "workspace_region_edit_plan" in names
    assert "workspace_region_edit_apply" in names
    assert "workspace_edit_apply" not in names
    assert "sandbox_shell_run" not in names


def test_code_mode_has_coding_tools_and_excludes_data_platform_surfaces():
    registry = build_tool_registry()
    names = _names(registry, InteractionMode.CODE)

    assert "workspace_edit_plan" in names
    assert "workspace_edit_apply" in names
    assert "workspace_region_edit_apply" in names
    assert "shell_run" in names
    assert "sandbox_shell_run" in names
    assert "git_change_plan" in names
    assert "git_change_apply" in names

    denied_prefixes = (
        "snowflake_",
        "dbt_",
        "notebook_",
        "mcp_",
        "skill_",
        "automation_",
        "hosted_runner_",
        "cortex_",
        "semantic_",
    )
    assert not [name for name in names if name.startswith(denied_prefixes)]


def test_interaction_mode_is_enforced_at_invocation_even_for_builder(tmp_path):
    registry = build_tool_registry()
    plan = registry.invoke(
        ToolInvocation(
            ToolRequest(
                tool="workspace_edit_plan",
                operation="workspace_edit_plan",
                environment=Environment.DEV,
                risk=Risk.READ_ONLY,
                args={
                    "workspace": str(tmp_path),
                    "path": "example.txt",
                    "content": "whole file\n",
                },
            ),
            run_id="code-plan",
            approved=False,
            actor_mode=ActorMode.BUILDER,
            interaction_mode=InteractionMode.CODE,
        )
    )
    assert plan["status"] == "PASS"

    with pytest.raises(PermissionError, match="edit interaction mode cannot invoke workspace_edit_apply"):
        registry.invoke(
            ToolInvocation(
                ToolRequest(
                    tool="workspace_edit_apply",
                    operation="workspace_edit_apply",
                    environment=Environment.DEV,
                    risk=Risk.MUTATING,
                    args={
                        "workspace": str(tmp_path),
                        "path": "example.txt",
                        "content": "whole file\n",
                        "approval_fingerprint": plan["approval_fingerprint"],
                    },
                ),
                run_id="edit-whole-file",
                approved=True,
                actor_mode=ActorMode.BUILDER,
                interaction_mode=InteractionMode.EDIT,
            )
        )


def test_code_mode_cannot_invoke_snowflake_tool_even_with_builder_privilege():
    registry = build_tool_registry()
    definition = next(
        item
        for item in registry.definitions()
        if item.name.startswith("snowflake_")
    )
    request = ToolRequest(
        tool=definition.name,
        operation=definition.name,
        environment=Environment.DEV,
        risk=definition.risk,
        platform=next(iter(definition.supported_platforms)),
        args={},
    )
    with pytest.raises(PermissionError, match="code interaction mode cannot invoke"):
        registry.invoke(
            ToolInvocation(
                request,
                run_id="code-snowflake-boundary",
                approved=True,
                actor_mode=ActorMode.ADMIN,
                interaction_mode=InteractionMode.CODE,
            )
        )


def test_agent_runtime_advertises_exact_interaction_mode_surface():
    registry = build_tool_registry()
    runtime = object.__new__(AgentRuntime)
    runtime.registry = registry

    code_specs = runtime._tool_specs(ActorMode.BUILDER, InteractionMode.CODE)
    edit_specs = runtime._tool_specs(ActorMode.BUILDER, InteractionMode.EDIT)
    ask_specs = runtime._tool_specs(ActorMode.ASK, InteractionMode.ASK)

    code_names = {item["name"] for item in code_specs}
    edit_names = {item["name"] for item in edit_specs}
    assert "workspace_edit_apply" in code_names
    assert "workspace_edit_apply" not in edit_names
    assert "workspace_region_edit_apply" in edit_names
    assert all(item["risk"] == "read_only" for item in ask_specs)
