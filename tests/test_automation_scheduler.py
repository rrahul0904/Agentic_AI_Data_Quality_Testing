from __future__ import annotations

from datetime import datetime, timezone

from agentic_data_platform.automations import AutomationService, next_run
from agentic_data_platform.cli import DOMAIN_CLI_TOOLS
from agentic_data_platform.models import ActorMode, Capability, Environment, Platform, Risk
from agentic_data_platform.tools.registry import ToolDefinition, ToolRegistry


UTC = timezone.utc


def _registry(calls: list[dict]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_probe",
        capability=Capability.DISCOVER,
        risk=Risk.READ_ONLY,
        supported_platforms=frozenset({Platform.LOCAL}),
        handler=lambda args: calls.append(dict(args)) or {"status": "PASS", "value": 42},
        description="read probe",
    ))
    registry.register(ToolDefinition(
        name="write_probe",
        capability=Capability.EXECUTE,
        risk=Risk.MUTATING,
        supported_platforms=frozenset({Platform.LOCAL}),
        handler=lambda args: calls.append(dict(args)) or {"status": "PASS", "changed": True},
        requires_approval=True,
        description="write probe",
    ))
    return registry


def test_schedule_supports_interval_daily_hourly_and_cron():
    after = datetime(2026, 9, 9, 17, 30, tzinfo=UTC)

    assert next_run({"type": "interval", "minutes": 15}, after=after) == datetime(
        2026, 9, 9, 17, 45, tzinfo=UTC
    )
    assert next_run({"type": "hourly", "minute": 45}, after=after) == datetime(
        2026, 9, 9, 17, 45, tzinfo=UTC
    )
    assert next_run(
        {"type": "daily", "time": "09:00", "timezone": "America/New_York"},
        after=after,
    ) == datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
    assert next_run(
        {"type": "cron", "expression": "*/15 * * * *", "timezone": "UTC"},
        after=after,
    ) == datetime(2026, 9, 9, 17, 45, tzinfo=UTC)


def test_automation_persists_across_service_restarts(tmp_path):
    path = tmp_path / "automations.db"
    first = AutomationService(path)
    created = first.create(
        name="hourly-health",
        tool_name="read_probe",
        args={"asset": "reservations"},
        schedule={"type": "hourly", "minute": 5, "timezone": "UTC"},
        actor_mode=ActorMode.ANALYST,
        environment=Environment.DEV,
        now=datetime(2026, 9, 9, 17, 0, tzinfo=UTC),
    )

    second = AutomationService(path)
    restored = second.get(created["automation_id"])

    assert restored["name"] == "hourly-health"
    assert restored["tool_name"] == "read_probe"
    assert restored["args"] == {"asset": "reservations"}
    assert restored["next_run_at"] == "2026-09-09T17:05:00+00:00"


def test_due_read_only_automation_executes_and_records_evidence(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    service = AutomationService(tmp_path / "automations.db")
    created = service.create(
        name="one-shot-read",
        tool_name="read_probe",
        args={"query": "health"},
        schedule={"type": "once", "at": "2026-09-09T18:00:00+00:00"},
        actor_mode=ActorMode.ANALYST,
        environment=Environment.DEV,
        now=datetime(2026, 9, 9, 17, 0, tzinfo=UTC),
    )

    result = service.run_due(
        registry,
        now=datetime(2026, 9, 9, 18, 0, tzinfo=UTC),
    )

    assert result["status"] == "PASS"
    assert result["run_count"] == 1
    assert calls and calls[0]["query"] == "health"
    stored = service.get(created["automation_id"])
    assert stored["last_status"] == "PASS"
    assert stored["run_count"] == 1
    assert stored["enabled"] is False
    assert stored["last_result"]["value"] == 42


def test_mutating_automation_does_not_bypass_approval(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    service = AutomationService(tmp_path / "automations.db")
    created = service.create(
        name="scheduled-write",
        tool_name="write_probe",
        args={"value": 1},
        schedule={"type": "once", "at": "2026-09-09T18:00:00+00:00"},
        actor_mode=ActorMode.BUILDER,
        environment=Environment.DEV,
        approved=False,
        now=datetime(2026, 9, 9, 17, 0, tzinfo=UTC),
    )

    blocked = service.run_due(
        registry,
        now=datetime(2026, 9, 9, 18, 0, tzinfo=UTC),
    )

    assert blocked["status"] == "BLOCKED_APPROVAL"
    assert blocked["blocked_count"] == 1
    assert calls == []
    assert service.get(created["automation_id"])["last_status"] == "BLOCKED_APPROVAL"


def test_explicitly_approved_mutating_automation_can_run(tmp_path):
    calls: list[dict] = []
    registry = _registry(calls)
    service = AutomationService(tmp_path / "automations.db")
    created = service.create(
        name="approved-write",
        tool_name="write_probe",
        args={"value": 7},
        schedule={"type": "once", "at": "2026-09-09T18:00:00+00:00"},
        actor_mode=ActorMode.BUILDER,
        environment=Environment.DEV,
        approved=False,
        now=datetime(2026, 9, 9, 17, 0, tzinfo=UTC),
    )
    service.set_approved(created["automation_id"], True)

    result = service.run_due(
        registry,
        now=datetime(2026, 9, 9, 18, 0, tzinfo=UTC),
    )

    assert result["status"] == "PASS"
    assert calls and calls[0]["value"] == 7
    stored = service.get(created["automation_id"])
    assert stored["approved"] is True
    assert stored["last_status"] == "PASS"


def test_cli_exposes_automation_control_plane():
    assert DOMAIN_CLI_TOOLS["automation"] == {
        "create": "automation_create",
        "list": "automation_list",
        "show": "automation_show",
        "enable": "automation_enable",
        "approve": "automation_approve",
        "run-due": "automation_run_due",
        "queue-hosted": "automation_queue_hosted",
        "delete": "automation_delete",
    }
