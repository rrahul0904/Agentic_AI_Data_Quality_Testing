"""Persistent unattended automation scheduler for ADE tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from agentic_data_platform.models import ActorMode, Environment, InteractionMode, ToolRequest, new_id, utc_now
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry
from agentic_data_platform.runners import HostedRunnerStore


_SCHEMA = """
CREATE TABLE IF NOT EXISTS automations (
  automation_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  args_json TEXT NOT NULL,
  schedule_json TEXT NOT NULL,
  actor_mode TEXT NOT NULL,
  environment TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_run_at TEXT,
  next_run_at TEXT,
  last_status TEXT,
  last_result_json TEXT,
  run_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_automation_due ON automations(enabled, next_run_at);
"""


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc(parsed)


def _parse_clock(value: str) -> tuple[int, int]:
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError("daily time must use HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("daily time is outside 00:00-23:59")
    return hour, minute


def _cron_values(field: str, minimum: int, maximum: int) -> set[int]:
    result: set[int] = set()
    for item in str(field).split(","):
        item = item.strip()
        if not item:
            continue
        if item == "*":
            result.update(range(minimum, maximum + 1))
            continue
        if item.startswith("*/"):
            step = int(item[2:])
            if step <= 0:
                raise ValueError("cron step must be positive")
            result.update(range(minimum, maximum + 1, step))
            continue
        if "-" in item:
            left, right = item.split("-", 1)
            start, end = int(left), int(right)
            if start > end:
                raise ValueError("cron range start must not exceed end")
            result.update(range(start, end + 1))
            continue
        result.add(int(item))
    if not result or min(result) < minimum or max(result) > maximum:
        raise ValueError(f"cron field must be within {minimum}-{maximum}")
    return result


def _next_cron(expression: str, after: datetime, tz: ZoneInfo) -> datetime:
    parts = str(expression).split()
    if len(parts) != 5:
        raise ValueError("cron expression must have five fields: minute hour day month weekday")
    minutes = _cron_values(parts[0], 0, 59)
    hours = _cron_values(parts[1], 0, 23)
    days = _cron_values(parts[2], 1, 31)
    months = _cron_values(parts[3], 1, 12)
    weekdays = _cron_values(parts[4].replace("7", "0"), 0, 6)

    candidate = _utc(after).astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = candidate + timedelta(days=366)
    while candidate <= limit:
        cron_weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in minutes
            and candidate.hour in hours
            and candidate.day in days
            and candidate.month in months
            and cron_weekday in weekdays
        ):
            return candidate.astimezone(timezone.utc)
        candidate += timedelta(minutes=1)
    raise ValueError("cron schedule produced no run within one year")


def next_run(schedule: dict[str, Any], *, after: datetime | None = None) -> datetime | None:
    current = _utc(after)
    kind = str(schedule.get("type") or "").casefold()
    timezone_name = str(schedule.get("timezone") or "UTC")
    tz = ZoneInfo(timezone_name)

    if kind == "interval":
        minutes = int(schedule.get("minutes") or 0)
        if minutes < 1:
            raise ValueError("interval schedule requires minutes >= 1")
        return current + timedelta(minutes=minutes)

    if kind == "hourly":
        minute = int(schedule.get("minute", 0))
        if not 0 <= minute <= 59:
            raise ValueError("hourly minute must be 0-59")
        local = current.astimezone(tz)
        candidate = local.replace(minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(hours=1)
        return candidate.astimezone(timezone.utc)

    if kind == "daily":
        hour, minute = _parse_clock(str(schedule.get("time") or "00:00"))
        local = current.astimezone(tz)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)

    if kind == "cron":
        return _next_cron(str(schedule.get("expression") or ""), current, tz)

    if kind == "once":
        target = _parse_iso(str(schedule.get("at") or ""))
        if target is None:
            raise ValueError("once schedule requires at")
        return target if target > current else None

    raise ValueError("schedule type must be interval, hourly, daily, cron, or once")


@dataclass(frozen=True)
class AutomationRun:
    automation_id: str
    status: str
    result: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "automation_id": self.automation_id,
            "status": self.status,
            "result": self.result,
        }


class AutomationService:
    """Store schedules and run due ADE tool invocations with normal policy controls."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(automations)").fetchall()
        }
        migrations = {
            "execution_backend": "TEXT NOT NULL DEFAULT 'local'",
            "interaction_mode": "TEXT NOT NULL DEFAULT 'agent'",
            "workspace_policy_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, ddl in migrations.items():
            if column not in columns:
                self.connection.execute(f"ALTER TABLE automations ADD COLUMN {column} {ddl}")
        self.connection.commit()

    def create(
        self,
        *,
        name: str,
        tool_name: str,
        args: dict[str, Any],
        schedule: dict[str, Any],
        actor_mode: ActorMode = ActorMode.ANALYST,
        interaction_mode: InteractionMode = InteractionMode.AGENT,
        environment: Environment = Environment.DEV,
        approved: bool = False,
        enabled: bool = True,
        execution_backend: str = "local",
        workspace_policy: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _utc(now)
        backend = str(execution_backend).casefold()
        if backend not in {"local", "hosted"}:
            raise ValueError("execution_backend must be local or hosted")
        policy = dict(workspace_policy or {})
        if backend == "hosted":
            from agentic_data_platform.runners.hosted import normalize_workspace_policy

            policy = normalize_workspace_policy(policy)
        elif policy:
            raise ValueError("workspace_policy is only valid for hosted automations")
        scheduled = next_run(schedule, after=current - timedelta(seconds=1)) if enabled else None
        automation_id = new_id("automation")
        timestamp = _iso(current) or utc_now()
        self.connection.execute(
            """
            INSERT INTO automations(
              automation_id,name,tool_name,args_json,schedule_json,actor_mode,environment,
              approved,enabled,created_at,updated_at,next_run_at,
              execution_backend,interaction_mode,workspace_policy_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                automation_id,
                str(name).strip() or tool_name,
                tool_name,
                json.dumps(args, sort_keys=True, default=str),
                json.dumps(schedule, sort_keys=True, default=str),
                actor_mode.value,
                environment.value,
                int(bool(approved)),
                int(bool(enabled)),
                timestamp,
                timestamp,
                _iso(scheduled),
                backend,
                interaction_mode.value,
                json.dumps(policy, sort_keys=True, default=str),
            ),
        )
        self.connection.commit()
        return self.get(automation_id)

    def get(self, automation_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM automations WHERE automation_id=?",
            (automation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"automation not found: {automation_id}")
        return self._public(row)

    def list(self, *, limit: int = 100, enabled: bool | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM automations"
        params: list[Any] = []
        if enabled is not None:
            sql += " WHERE enabled=?"
            params.append(int(enabled))
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return [self._public(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def set_approved(self, automation_id: str, approved: bool) -> dict[str, Any]:
        if self.connection.execute(
            "SELECT 1 FROM automations WHERE automation_id=?",
            (automation_id,),
        ).fetchone() is None:
            raise KeyError(f"automation not found: {automation_id}")
        self.connection.execute(
            "UPDATE automations SET approved=?, updated_at=? WHERE automation_id=?",
            (int(bool(approved)), utc_now(), automation_id),
        )
        self.connection.commit()
        return self.get(automation_id)

    def set_enabled(self, automation_id: str, enabled: bool, *, now: datetime | None = None) -> dict[str, Any]:
        current = _utc(now)
        existing = self.get(automation_id)
        schedule = existing["schedule"]
        scheduled = next_run(schedule, after=current - timedelta(seconds=1)) if enabled else None
        self.connection.execute(
            "UPDATE automations SET enabled=?, next_run_at=?, updated_at=? WHERE automation_id=?",
            (int(enabled), _iso(scheduled), _iso(current), automation_id),
        )
        self.connection.commit()
        return self.get(automation_id)

    def delete(self, automation_id: str) -> bool:
        cursor = self.connection.execute("DELETE FROM automations WHERE automation_id=?", (automation_id,))
        self.connection.commit()
        return bool(cursor.rowcount)

    def due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
        execution_backend: str | None = None,
    ) -> list[dict[str, Any]]:
        current = _iso(_utc(now))
        sql = """
            SELECT * FROM automations
            WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= ?
        """
        params: list[Any] = [current]
        if execution_backend is not None:
            backend = str(execution_backend).casefold()
            if backend not in {"local", "hosted"}:
                raise ValueError("execution_backend must be local or hosted")
            sql += " AND execution_backend=?"
            params.append(backend)
        sql += " ORDER BY next_run_at, automation_id LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        rows = self.connection.execute(sql, tuple(params)).fetchall()
        return [self._public(row) for row in rows]

    def run_due(
        self,
        registry: ToolRegistry,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        current = _utc(now)
        runs: list[AutomationRun] = []
        for automation in self.due(
            now=current,
            limit=limit,
            execution_backend="local",
        ):
            definition = registry.describe(automation["tool_name"])
            approved = bool(automation["approved"])
            request = ToolRequest(
                tool=automation["tool_name"],
                operation=automation["tool_name"],
                environment=Environment(automation["environment"]),
                risk=definition.risk,
                args=dict(automation["args"]),
            )
            try:
                result = registry.invoke(ToolInvocation(
                    request,
                    run_id=automation["automation_id"],
                    approved=approved,
                    actor_mode=ActorMode(automation["actor_mode"]),
                    interaction_mode=InteractionMode(automation["interaction_mode"]),
                ))
                status = str(result.get("status") or "PASS") if isinstance(result, dict) else "PASS"
                payload = dict(result) if isinstance(result, dict) else {"value": result}
            except PermissionError as exc:
                status = "BLOCKED_APPROVAL"
                payload = {"status": status, "error": str(exc)}
            except Exception as exc:
                status = "FAIL"
                payload = {"status": status, "error": f"{type(exc).__name__}: {exc}"}

            schedule = automation["schedule"]
            next_at = next_run(schedule, after=current)
            enabled = not (str(schedule.get("type")).casefold() == "once" and next_at is None)
            self.connection.execute(
                """
                UPDATE automations
                SET last_run_at=?, next_run_at=?, last_status=?, last_result_json=?,
                    run_count=run_count+1, enabled=?, updated_at=?
                WHERE automation_id=?
                """,
                (
                    _iso(current),
                    _iso(next_at),
                    status,
                    json.dumps(payload, default=str),
                    int(enabled),
                    _iso(current),
                    automation["automation_id"],
                ),
            )
            self.connection.commit()
            runs.append(AutomationRun(automation["automation_id"], status, payload))

        failed = [item for item in runs if item.status in {"FAIL", "ERROR"}]
        blocked = [item for item in runs if item.status == "BLOCKED_APPROVAL"]
        return {
            "status": "FAIL" if failed else ("BLOCKED_APPROVAL" if blocked and not failed else "PASS"),
            "run_count": len(runs),
            "failed_count": len(failed),
            "blocked_count": len(blocked),
            "runs": [item.public() for item in runs],
        }

    def _advance_after_dispatch(
        self,
        automation: dict[str, Any],
        *,
        current: datetime,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        schedule = automation["schedule"]
        next_at = next_run(schedule, after=current)
        enabled = not (
            str(schedule.get("type")).casefold() == "once"
            and next_at is None
        )
        self.connection.execute(
            """
            UPDATE automations
            SET last_run_at=?, next_run_at=?, last_status=?, last_result_json=?,
                run_count=run_count+1, enabled=?, updated_at=?
            WHERE automation_id=?
            """,
            (
                _iso(current),
                _iso(next_at),
                status,
                json.dumps(payload, sort_keys=True, default=str),
                int(enabled),
                _iso(current),
                automation["automation_id"],
            ),
        )
        self.connection.commit()

    def queue_due_hosted(
        self,
        hosted: HostedRunnerStore,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        current = _utc(now)
        runs: list[AutomationRun] = []
        for automation in self.due(
            now=current,
            limit=limit,
            execution_backend="hosted",
        ):
            try:
                job = hosted.submit(
                    tool_name=str(automation["tool_name"]),
                    args=dict(automation["args"]),
                    actor_mode=ActorMode(automation["actor_mode"]),
                    interaction_mode=InteractionMode(automation["interaction_mode"]),
                    environment=Environment(automation["environment"]),
                    approved=bool(automation["approved"]),
                    workspace_policy=dict(automation["workspace_policy"]),
                )
                status = "QUEUED_HOSTED"
                payload = {
                    "status": status,
                    "hosted_job_id": job["job_id"],
                    "workspace_policy": job["workspace_policy"],
                    "interaction_mode": job["interaction_mode"],
                    "approved": job["approved"],
                }
            except Exception as exc:
                status = "FAIL"
                payload = {
                    "status": status,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            self._advance_after_dispatch(
                automation,
                current=current,
                status=status,
                payload=payload,
            )
            runs.append(
                AutomationRun(
                    automation["automation_id"],
                    status,
                    payload,
                )
            )
        failed = [item for item in runs if item.status == "FAIL"]
        return {
            "status": "FAIL" if failed else "PASS",
            "dispatch_count": len(runs),
            "failed_count": len(failed),
            "runs": [item.public() for item in runs],
        }

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["args"] = json.loads(value.pop("args_json"))
        value["schedule"] = json.loads(value.pop("schedule_json"))
        value["last_result"] = json.loads(value.pop("last_result_json")) if value.get("last_result_json") else None
        value["workspace_policy"] = json.loads(value.pop("workspace_policy_json", "{}") or "{}")
        value["execution_backend"] = str(value.get("execution_backend") or "local")
        value["interaction_mode"] = str(value.get("interaction_mode") or "agent")
        value["approved"] = bool(value["approved"])
        value["enabled"] = bool(value["enabled"])
        return value
