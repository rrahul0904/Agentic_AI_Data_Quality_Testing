from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.automations import AutomationService
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.models import (
    ActorMode,
    Capability,
    Environment,
    InteractionMode,
    Platform,
    Risk,
)
from agentic_data_platform.runners import HostedRunnerStore
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry


UTC = timezone.utc
DUE = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)


def _registry(calls: list[dict]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="hosted_probe",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: calls.append(dict(args)) or {"status": "PASS"},
            requires_approval=True,
        )
    )
    return registry


def _isolation_metadata():
    return {
        "workspace_isolation": {
            "enforced": True,
            "execution_class": "HOSTED_ISOLATED_WORKSPACE",
            "network_enabled": False,
            "memory_mb": 2048,
            "cpus": 2.0,
            "pids_limit": 512,
            "filesystem_scopes": ["workspace", "read_only_workspace"],
        }
    }


def test_hosted_automation_persists_backend_interaction_and_workspace_policy(tmp_path):
    service = AutomationService(tmp_path / "automations.db")
    automation = service.create(
        name="nightly-governed-check",
        tool_name="hosted_probe",
        args={"asset": "reservations"},
        schedule={"type": "once", "at": DUE.isoformat()},
        actor_mode=ActorMode.BUILDER,
        interaction_mode=InteractionMode.CODE,
        environment=Environment.STAGING,
        execution_backend="hosted",
        workspace_policy={
            "sandbox_required": True,
            "workspace_id": "nightly-check",
            "filesystem_scope": "read_only_workspace",
            "network_enabled": False,
            "memory_mb": 1024,
            "cpus": 1.5,
            "pids_limit": 128,
            "credential_refs": ["secret://warehouse/read-only"],
        },
        now=datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
    )

    assert automation["execution_backend"] == "hosted"
    assert automation["interaction_mode"] == "code"
    assert automation["workspace_policy"]["sandbox_required"] is True
    assert automation["workspace_policy"]["filesystem_scope"] == "read_only_workspace"
    assert automation["workspace_policy"]["policy_fingerprint"]


def test_local_worker_never_executes_hosted_automation(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    service = AutomationService(tmp_path / "automations.db")
    automation = service.create(
        name="hosted-only",
        tool_name="hosted_probe",
        args={"value": 7},
        schedule={"type": "once", "at": DUE.isoformat()},
        actor_mode=ActorMode.BUILDER,
        interaction_mode=InteractionMode.AGENT,
        execution_backend="hosted",
        workspace_policy={"sandbox_required": True},
        now=datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
    )

    result = service.run_due(registry, now=DUE)

    assert result["run_count"] == 0
    assert calls == []
    stored = service.get(automation["automation_id"])
    assert stored["run_count"] == 0
    assert stored["enabled"] is True


def test_due_hosted_automation_dispatches_exact_contract_and_disables_one_shot(tmp_path):
    service = AutomationService(tmp_path / "automations.db")
    hosted = HostedRunnerStore(tmp_path / "hosted.db")
    automation = service.create(
        name="hosted-write",
        tool_name="hosted_probe",
        args={"value": 11},
        schedule={"type": "once", "at": DUE.isoformat()},
        actor_mode=ActorMode.BUILDER,
        interaction_mode=InteractionMode.CODE,
        environment=Environment.DEV,
        approved=True,
        execution_backend="hosted",
        workspace_policy={
            "sandbox_required": True,
            "workspace_id": "automation-11",
            "network_enabled": False,
            "memory_mb": 768,
            "cpus": 1,
            "pids_limit": 64,
        },
        now=datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
    )

    result = service.queue_due_hosted(hosted, now=DUE)

    assert result["status"] == "PASS"
    assert result["dispatch_count"] == 1
    hosted_job_id = result["runs"][0]["result"]["hosted_job_id"]
    job = hosted.job(hosted_job_id)
    assert job["tool_name"] == "hosted_probe"
    assert job["args"] == {"value": 11}
    assert job["actor_mode"] == "builder"
    assert job["interaction_mode"] == "code"
    assert job["environment"] == "dev"
    assert job["approved"] is True
    assert job["workspace_policy"]["sandbox_required"] is True
    assert job["workspace_policy"]["workspace_id"] == "automation-11"

    stored = service.get(automation["automation_id"])
    assert stored["last_status"] == "QUEUED_HOSTED"
    assert stored["run_count"] == 1
    assert stored["enabled"] is False
    assert stored["last_result"]["hosted_job_id"] == hosted_job_id


def test_recurring_hosted_automation_advances_schedule_after_dispatch(tmp_path):
    service = AutomationService(tmp_path / "automations.db")
    hosted = HostedRunnerStore(tmp_path / "hosted.db")
    automation = service.create(
        name="hosted-hourly",
        tool_name="hosted_probe",
        args={},
        schedule={"type": "interval", "minutes": 60},
        execution_backend="hosted",
        workspace_policy={"sandbox_required": False},
        now=datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
    )

    result = service.queue_due_hosted(
        hosted,
        now=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
    )

    assert result["dispatch_count"] == 1
    stored = service.get(automation["automation_id"])
    assert stored["enabled"] is True
    assert stored["next_run_at"] == "2026-09-10T05:00:00+00:00"


def test_isolated_hosted_automation_cannot_lease_to_unattested_runner(tmp_path):
    service = AutomationService(tmp_path / "automations.db")
    hosted = HostedRunnerStore(tmp_path / "hosted.db")
    plain = hosted.register_runner(name="plain", capabilities=["hosted_probe"])
    isolated = hosted.register_runner(
        name="isolated",
        capabilities=["hosted_probe"],
        metadata=_isolation_metadata(),
    )
    service.create(
        name="protected",
        tool_name="hosted_probe",
        args={},
        schedule={"type": "once", "at": DUE.isoformat()},
        execution_backend="hosted",
        workspace_policy={
            "sandbox_required": True,
            "network_enabled": False,
            "memory_mb": 512,
            "cpus": 1,
            "pids_limit": 64,
        },
        now=datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
    )
    dispatched = service.queue_due_hosted(hosted, now=DUE)
    job_id = dispatched["runs"][0]["result"]["hosted_job_id"]

    assert hosted.lease(plain["runner_id"]) is None
    readiness = hosted.workspace_readiness(job_id)
    assert readiness["status"] == "PASS"
    assert readiness["compatible_runner_ids"] == [isolated["runner_id"]]
    assert hosted.lease(isolated["runner_id"])["job_id"] == job_id


def test_hosted_automation_does_not_invent_approval(tmp_path):
    service = AutomationService(tmp_path / "automations.db")
    hosted = HostedRunnerStore(tmp_path / "hosted.db")
    service.create(
        name="unapproved",
        tool_name="hosted_probe",
        args={"value": 3},
        schedule={"type": "once", "at": DUE.isoformat()},
        actor_mode=ActorMode.BUILDER,
        approved=False,
        execution_backend="hosted",
        workspace_policy={"sandbox_required": False},
        now=datetime(2026, 9, 10, 3, 0, tzinfo=UTC),
    )

    dispatched = service.queue_due_hosted(hosted, now=DUE)
    job = hosted.job(dispatched["runs"][0]["result"]["hosted_job_id"])

    assert job["approved"] is False


def test_hosted_automation_surfaces_are_exposed():
    registry = build_tool_registry()
    names = {definition.name for definition in registry.definitions()}
    assert {"automation_create", "automation_queue_hosted"} <= names

    assert DOMAIN_CLI_TOOLS["automation"]["queue-hosted"] == "automation_queue_hosted"

    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert (
        domains.json()["automations"]["queue-hosted"]
        == "automation_queue_hosted"
        or domains.json()["automations"]["queue-hosted"]["tool"]
        == "automation_queue_hosted"
    )
