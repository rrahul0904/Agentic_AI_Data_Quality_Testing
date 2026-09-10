from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.models import (
    ActorMode,
    Capability,
    Environment,
    InteractionMode,
    Platform,
    Risk,
)
from agentic_data_platform.runners.hosted import (
    HostedRunnerStore,
    normalize_workspace_policy,
    runner_satisfies_workspace_policy,
)
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry


def _isolation_metadata(**overrides):
    isolation = {
        "enforced": True,
        "execution_class": "HOSTED_ISOLATED_WORKSPACE",
        "network_enabled": False,
        "memory_mb": 2048,
        "cpus": 2.0,
        "pids_limit": 512,
        "filesystem_scopes": ["workspace", "read_only_workspace"],
    }
    isolation.update(overrides)
    return {"workspace_isolation": isolation}


def test_workspace_policy_is_explicit_fingerprinted_and_reference_only():
    policy = normalize_workspace_policy(
        {
            "sandbox_required": True,
            "workspace_id": "job-123",
            "filesystem_scope": "workspace",
            "network_enabled": False,
            "memory_mb": 1024,
            "cpus": 1.5,
            "pids_limit": 128,
            "credential_refs": ["secret://snowflake/prod", "env://DBT_TOKEN"],
        }
    )
    assert policy["execution_class"] == "HOSTED_ISOLATED_WORKSPACE"
    assert policy["sandbox_required"] is True
    assert policy["network_enabled"] is False
    assert policy["credential_refs"] == ["env://DBT_TOKEN", "secret://snowflake/prod"]
    assert policy["policy_fingerprint"]

    with pytest.raises(ValueError, match="credential references only"):
        normalize_workspace_policy({"secrets": {"token": "plaintext"}})


def test_legacy_nonisolated_job_remains_backward_compatible(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(name="legacy", capabilities=["read_probe"])
    job = store.submit(tool_name="read_probe", args={"asset": "reservations"})

    assert job["interaction_mode"] == "agent"
    assert job["workspace_policy"]["sandbox_required"] is False
    leased = store.lease(runner["runner_id"])
    assert leased is not None
    assert leased["job_id"] == job["job_id"]


def test_isolated_job_cannot_lease_to_unattested_runner(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(name="plain", capabilities=["read_probe"])
    job = store.submit(
        tool_name="read_probe",
        args={},
        workspace_policy={
            "sandbox_required": True,
            "network_enabled": False,
            "memory_mb": 512,
            "cpus": 1,
            "pids_limit": 64,
        },
    )

    assert store.lease(runner["runner_id"]) is None
    readiness = store.workspace_readiness(job["job_id"], runner_id=runner["runner_id"])
    assert readiness["status"] == "BLOCKED_ISOLATION"
    assert readiness["compatible_runner_ids"] == []

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read_probe",
            capability=Capability.DISCOVER,
            risk=Risk.READ_ONLY,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: {"status": "PASS"},
        )
    )
    blocked = store.run_once(registry, runner["runner_id"])
    assert blocked["status"] == "BLOCKED_ISOLATION"
    assert store.job(job["job_id"])["status"] == "QUEUED"


def test_isolated_job_leases_only_to_runner_satisfying_policy(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    weak = store.register_runner(
        name="weak",
        capabilities=["read_probe"],
        metadata=_isolation_metadata(memory_mb=128),
    )
    strong = store.register_runner(
        name="strong",
        capabilities=["read_probe"],
        metadata=_isolation_metadata(),
    )
    job = store.submit(
        tool_name="read_probe",
        args={},
        workspace_policy={
            "sandbox_required": True,
            "filesystem_scope": "workspace",
            "network_enabled": False,
            "memory_mb": 1024,
            "cpus": 1.5,
            "pids_limit": 256,
        },
    )

    assert runner_satisfies_workspace_policy(
        weak,
        job["workspace_policy"],
    ) is False
    assert store.lease(weak["runner_id"]) is None

    readiness = store.workspace_readiness(job["job_id"])
    assert readiness["status"] == "PASS"
    assert readiness["compatible_runner_ids"] == [strong["runner_id"]]

    leased = store.lease(strong["runner_id"])
    assert leased["job_id"] == job["job_id"]
    assert leased["workspace_policy"]["policy_fingerprint"] == job["workspace_policy"]["policy_fingerprint"]


def test_network_denied_job_rejects_runner_with_unrestricted_network(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(
        name="networked",
        capabilities=["read_probe"],
        metadata=_isolation_metadata(network_enabled=True),
    )
    job = store.submit(
        tool_name="read_probe",
        args={},
        workspace_policy={
            "sandbox_required": True,
            "network_enabled": False,
        },
    )

    assert runner_satisfies_workspace_policy(runner, job["workspace_policy"]) is False


def test_hosted_runner_preserves_interaction_mode_policy(tmp_path):
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="snowflake_fake_mutation",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: calls.append(args) or {"status": "PASS"},
            requires_approval=True,
        )
    )
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(
        name="worker",
        capabilities=["snowflake_fake_mutation"],
    )
    job = store.submit(
        tool_name="snowflake_fake_mutation",
        args={},
        actor_mode=ActorMode.ADMIN,
        interaction_mode=InteractionMode.CODE,
        environment=Environment.DEV,
        approved=True,
    )

    result = store.run_once(registry, runner["runner_id"])

    assert result["status"] == "BLOCKED_POLICY"
    assert "code interaction mode cannot invoke" in result["error"]
    assert calls == []
    assert store.job(job["job_id"])["interaction_mode"] == "code"


def test_hosted_isolation_tools_are_exposed_in_registry_and_api():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {
        "hosted_runner_submit",
        "hosted_runner_workspace_readiness",
        "hosted_runner_run_once",
    } <= names

    client = TestClient(create_app())
    response = client.get("/api/v1/domains")
    assert response.status_code == 200
    runner = response.json()["runner"]
    assert "workspace-readiness" in runner
