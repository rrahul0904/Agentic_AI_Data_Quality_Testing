from __future__ import annotations

import pytest

from agentic_data_platform.models import ActorMode, Environment, Risk, ToolRequest
from agentic_data_platform.runners.sandbox import sandbox_shell_plan, sandbox_shell_run
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolInvocation


def test_container_sandbox_plan_has_strong_default_isolation(tmp_path):
    plan = sandbox_shell_plan(
        tmp_path,
        ["python", "-c", "print('ok')"],
        timeout_seconds=15,
        memory_mb=256,
        cpus=0.5,
        pids_limit=64,
    )

    assert plan["status"] == "PASS"
    assert plan["execution_class"] == "CONTAINER_SANDBOX"
    assert plan["sandboxed"] is True
    assert plan["network_enabled"] is False
    assert plan["security"]["implicit_shell"] is False
    assert plan["security"]["root_filesystem_read_only"] is True
    assert plan["security"]["capabilities_dropped"] == "ALL"
    assert plan["security"]["no_new_privileges"] is True
    assert plan["security"]["network_default"] == "DENY"
    command = plan["docker_command"]
    assert "--cap-drop" in command
    assert "ALL" in command
    assert "--read-only" in command
    assert "no-new-privileges" in command
    assert "--pids-limit" in command
    assert "--memory" in command
    assert "--cpus" in command
    network_index = command.index("--network")
    assert command[network_index + 1] == "none"
    assert plan["approval_fingerprint"]


def test_container_sandbox_background_plan_is_named_and_persistent_for_observation(tmp_path):
    plan = sandbox_shell_plan(
        tmp_path,
        ["python", "-c", "print('background')"],
        background=True,
        workspace_write=False,
    )

    assert plan["container_name"].startswith("ade-sandbox-")
    assert "-d" in plan["docker_command"]
    assert "--name" in plan["docker_command"]
    assert plan["security"]["workspace_mount"] == "ro"
    assert "--rm" not in plan["docker_command"]


def test_container_sandbox_rejects_workspace_escape(tmp_path):
    with pytest.raises(ValueError, match="cwd escapes"):
        sandbox_shell_plan(tmp_path, ["python", "-V"], cwd="../outside")


def test_container_sandbox_fails_closed_when_runtime_is_unavailable(tmp_path):
    plan = sandbox_shell_plan(
        tmp_path,
        ["python", "-c", "print('never executed')"],
        docker_executable="definitely-no-such-docker-binary",
    )
    result = sandbox_shell_run(
        tmp_path,
        ["python", "-c", "print('never executed')"],
        approval_fingerprint=plan["approval_fingerprint"],
        docker_executable="definitely-no-such-docker-binary",
    )

    assert result["status"] == "BLOCKED_UNAVAILABLE"
    assert result["execution_class"] == "CONTAINER_SANDBOX"
    assert result["sandboxed"] is False
    assert "refusing to downgrade" in result["reason"]


def test_container_sandbox_stale_approval_never_reaches_runtime(tmp_path):
    result = sandbox_shell_run(
        tmp_path,
        ["python", "-V"],
        approval_fingerprint="tampered",
        docker_executable="definitely-no-such-docker-binary",
    )
    assert result["status"] == "STALE_APPROVAL"


def test_sandbox_shell_tools_share_ask_plan_and_approval_boundaries(tmp_path):
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    expected = {
        "sandbox_shell_plan",
        "sandbox_shell_run",
        "sandbox_shell_status",
        "sandbox_shell_logs",
        "sandbox_shell_kill",
    }
    assert expected <= names

    plan = sandbox_shell_plan(
        tmp_path,
        ["python", "-V"],
        docker_executable="definitely-no-such-docker-binary",
    )
    request = ToolRequest(
        tool="sandbox_shell_run",
        operation="sandbox_shell_run",
        environment=Environment.DEV,
        risk=Risk.MUTATING,
        args={
            "workspace": str(tmp_path),
            "command": ["python", "-V"],
            "approval_fingerprint": plan["approval_fingerprint"],
            "docker_executable": "definitely-no-such-docker-binary",
        },
    )

    for mode in (ActorMode.ASK, ActorMode.PLAN):
        with pytest.raises(PermissionError, match=f"{mode.value} mode cannot invoke"):
            registry.invoke(
                ToolInvocation(
                    request=request,
                    run_id=f"{mode.value}-sandbox-boundary",
                    approved=True,
                    actor_mode=mode,
                )
            )

    result = registry.invoke(
        ToolInvocation(
            request=request,
            run_id="builder-sandbox-boundary",
            approved=True,
            actor_mode=ActorMode.BUILDER,
        )
    )
    assert result["status"] == "BLOCKED_UNAVAILABLE"
