from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from agentic_data_platform.api.app import create_app
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.models import ActorMode, Capability, Environment, Platform, Risk
from agentic_data_platform.runners import HostedRunnerStore
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry


def _registry(calls: list[dict]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read_probe",
            capability=Capability.DISCOVER,
            risk=Risk.READ_ONLY,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: calls.append(dict(args)) or {"status": "PASS", "value": 42},
            description="read probe",
        )
    )
    registry.register(
        ToolDefinition(
            name="write_probe",
            capability=Capability.EXECUTE,
            risk=Risk.MUTATING,
            supported_platforms=frozenset({Platform.LOCAL}),
            handler=lambda args: calls.append(dict(args)) or {"status": "PASS", "changed": True},
            requires_approval=True,
            description="write probe",
        )
    )
    return registry


def test_hosted_runner_persists_jobs_and_executes_read_only_work(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    path = tmp_path / "hosted.db"
    store = HostedRunnerStore(path)
    runner = store.register_runner(name="runner-a", capabilities=["read_probe"])
    job = store.submit(
        tool_name="read_probe",
        args={"asset": "reservations"},
        actor_mode=ActorMode.ANALYST,
        environment=Environment.DEV,
    )

    restarted = HostedRunnerStore(path)
    result = restarted.run_once(registry, runner["runner_id"])

    assert result["status"] == "SUCCESS"
    stored = restarted.job(job["job_id"])
    assert stored["status"] == "SUCCESS"
    assert stored["attempts"] == 1
    assert stored["lease_owner"] is None
    assert stored["result"]["value"] == 42
    assert calls[0]["asset"] == "reservations"
    assert calls[0]["_actor_mode"] == "analyst"


def test_hosted_runner_preserves_mutation_approval_boundary(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(name="runner-a", capabilities=["write_probe"])
    job = store.submit(
        tool_name="write_probe",
        args={"value": 7},
        actor_mode=ActorMode.BUILDER,
        environment=Environment.DEV,
        approved=False,
    )

    result = store.run_once(registry, runner["runner_id"])

    assert result["status"] == "BLOCKED_APPROVAL"
    assert calls == []
    assert store.job(job["job_id"])["status"] == "BLOCKED_APPROVAL"


def test_hosted_runner_can_execute_explicitly_approved_mutation(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(name="runner-a", capabilities=["write_probe"])
    job = store.submit(
        tool_name="write_probe",
        args={"value": 9},
        actor_mode=ActorMode.BUILDER,
        environment=Environment.DEV,
        approved=True,
    )

    result = store.run_once(registry, runner["runner_id"])

    assert result["status"] == "SUCCESS"
    assert store.job(job["job_id"])["approved"] is True
    assert calls[0]["value"] == 9


def test_hosted_runner_capability_scoping_prevents_wrong_worker_from_leasing(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    read_runner = store.register_runner(name="read-only", capabilities=["read_probe"])
    write_runner = store.register_runner(name="writer", capabilities=["write_probe"])
    job = store.submit(
        tool_name="write_probe",
        args={},
        actor_mode=ActorMode.BUILDER,
        approved=True,
    )

    assert store.lease(read_runner["runner_id"]) is None
    leased = store.lease(write_runner["runner_id"])
    assert leased["job_id"] == job["job_id"]
    assert leased["lease_owner"] == write_runner["runner_id"]


def test_expired_lease_is_recovered(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    first = store.register_runner(name="first", capabilities=["*"])
    second = store.register_runner(name="second", capabilities=["*"])
    job = store.submit(tool_name="read_probe", args={})

    leased = store.lease(first["runner_id"], lease_seconds=5)
    assert leased["status"] == "RUNNING"

    expired = datetime.now(timezone.utc) + timedelta(seconds=10)
    recovered = store.recover_expired_leases(now=expired)
    assert recovered == 1

    leased_again = store.lease(second["runner_id"], now=expired)
    assert leased_again["job_id"] == job["job_id"]
    assert leased_again["attempts"] == 2


def test_hosted_runner_cancel_prevents_leasing(tmp_path):
    store = HostedRunnerStore(tmp_path / "hosted.db")
    runner = store.register_runner(name="runner", capabilities=["*"])
    job = store.submit(tool_name="read_probe", args={})

    cancelled = store.cancel(job["job_id"])

    assert cancelled["status"] == "CANCELLED"
    assert store.lease(runner["runner_id"]) is None


def test_hosted_runner_surfaces_are_exposed():
    assert set(DOMAIN_CLI_TOOLS["runner"]) == {
        "submit",
        "jobs",
        "job",
        "cancel",
        "register",
        "runners",
        "heartbeat",
        "run-once",
    }
    client = TestClient(create_app())
    domains = client.get("/api/v1/domains")
    assert domains.status_code == 200
    assert set(domains.json()["runner"]) == set(DOMAIN_CLI_TOOLS["runner"])
