"""Durable hostable ADE runner control plane with leases and policy-safe execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from agentic_data_platform.models import ActorMode, Environment, ToolRequest, new_id
from agentic_data_platform.tools.registry import ToolInvocation, ToolRegistry


_SCHEMA = """
CREATE TABLE IF NOT EXISTS hosted_jobs (
  job_id TEXT PRIMARY KEY,
  tool_name TEXT NOT NULL,
  args_json TEXT NOT NULL,
  actor_mode TEXT NOT NULL,
  environment TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  available_at TEXT NOT NULL,
  lease_owner TEXT,
  lease_until TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  result_json TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_hosted_jobs_ready
ON hosted_jobs(status, available_at, lease_until);

CREATE TABLE IF NOT EXISTS hosted_runners (
  runner_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


class HostedRunnerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def register_runner(
        self,
        *,
        name: str,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        runner_id: str | None = None,
    ) -> dict[str, Any]:
        runner_id = runner_id or new_id("runner")
        timestamp = _iso()
        self.connection.execute(
            """
            INSERT INTO hosted_runners(
              runner_id,name,capabilities_json,registered_at,heartbeat_at,metadata_json
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(runner_id) DO UPDATE SET
              name=excluded.name,
              capabilities_json=excluded.capabilities_json,
              heartbeat_at=excluded.heartbeat_at,
              metadata_json=excluded.metadata_json
            """,
            (
                runner_id,
                str(name),
                json.dumps(capabilities or ["*"], sort_keys=True),
                timestamp,
                timestamp,
                json.dumps(metadata or {}, sort_keys=True, default=str),
            ),
        )
        self.connection.commit()
        return self.runner(runner_id)

    def heartbeat(self, runner_id: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM hosted_runners WHERE runner_id=?", (runner_id,)).fetchone()
        if row is None:
            raise KeyError(f"runner not found: {runner_id}")
        merged = json.loads(row["metadata_json"])
        merged.update(metadata or {})
        self.connection.execute(
            "UPDATE hosted_runners SET heartbeat_at=?, metadata_json=? WHERE runner_id=?",
            (_iso(), json.dumps(merged, sort_keys=True, default=str), runner_id),
        )
        self.connection.commit()
        return self.runner(runner_id)

    def runner(self, runner_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM hosted_runners WHERE runner_id=?", (runner_id,)).fetchone()
        if row is None:
            raise KeyError(f"runner not found: {runner_id}")
        return self._runner(row)

    def runners(self) -> list[dict[str, Any]]:
        return [self._runner(row) for row in self.connection.execute(
            "SELECT * FROM hosted_runners ORDER BY heartbeat_at DESC"
        ).fetchall()]

    def submit(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        actor_mode: ActorMode = ActorMode.ANALYST,
        environment: Environment = Environment.DEV,
        approved: bool = False,
        delay_seconds: int = 0,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        job_id = new_id("hosted_job")
        current = _now()
        self.connection.execute(
            """
            INSERT INTO hosted_jobs(
              job_id,tool_name,args_json,actor_mode,environment,approved,status,
              created_at,updated_at,available_at,max_attempts
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                str(tool_name),
                json.dumps(args, sort_keys=True, default=str),
                actor_mode.value,
                environment.value,
                int(bool(approved)),
                "QUEUED",
                _iso(current),
                _iso(current),
                _iso(current + timedelta(seconds=max(0, int(delay_seconds)))),
                max(1, int(max_attempts)),
            ),
        )
        self.connection.commit()
        return self.job(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM hosted_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"hosted job not found: {job_id}")
        return self._job(row)

    def jobs(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM hosted_jobs"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(str(status).upper())
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return [self._job(row) for row in self.connection.execute(sql, tuple(params)).fetchall()]

    def cancel(self, job_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT status FROM hosted_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"hosted job not found: {job_id}")
        if row["status"] in {"SUCCESS", "FAIL", "CANCELLED"}:
            return self.job(job_id)
        self.connection.execute(
            """
            UPDATE hosted_jobs
            SET status='CANCELLED', updated_at=?, lease_owner=NULL, lease_until=NULL
            WHERE job_id=?
            """,
            (_iso(), job_id),
        )
        self.connection.commit()
        return self.job(job_id)

    def recover_expired_leases(self, *, now: datetime | None = None) -> int:
        current = _iso(now or _now())
        cursor = self.connection.execute(
            """
            UPDATE hosted_jobs
            SET status='QUEUED', lease_owner=NULL, lease_until=NULL, updated_at=?
            WHERE status='RUNNING' AND lease_until IS NOT NULL AND lease_until < ?
            """,
            (current, current),
        )
        self.connection.commit()
        return int(cursor.rowcount)

    def lease(
        self,
        runner_id: str,
        *,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        runner = self.runner(runner_id)
        current = now or _now()
        self.recover_expired_leases(now=current)
        capabilities = set(runner["capabilities"])
        rows = self.connection.execute(
            """
            SELECT * FROM hosted_jobs
            WHERE status='QUEUED' AND available_at <= ?
            ORDER BY created_at
            """,
            (_iso(current),),
        ).fetchall()
        selected = None
        for row in rows:
            if "*" in capabilities or row["tool_name"] in capabilities:
                selected = row
                break
        if selected is None:
            return None
        until = current + timedelta(seconds=max(5, int(lease_seconds)))
        cursor = self.connection.execute(
            """
            UPDATE hosted_jobs
            SET status='RUNNING', lease_owner=?, lease_until=?, attempts=attempts+1, updated_at=?
            WHERE job_id=? AND status='QUEUED'
            """,
            (runner_id, _iso(until), _iso(current), selected["job_id"]),
        )
        self.connection.commit()
        if not cursor.rowcount:
            return None
        return self.job(selected["job_id"])

    def complete(self, job_id: str, runner_id: str, *, status: str, result: dict[str, Any], error: str | None = None) -> dict[str, Any]:
        job = self.job(job_id)
        if job["status"] != "RUNNING" or job["lease_owner"] != runner_id:
            raise PermissionError("runner does not own active job lease")
        final = str(status).upper()
        if final not in {"SUCCESS", "FAIL", "BLOCKED_APPROVAL"}:
            raise ValueError("invalid hosted runner terminal status")
        if final == "FAIL" and job["attempts"] < job["max_attempts"]:
            final = "QUEUED"
        self.connection.execute(
            """
            UPDATE hosted_jobs
            SET status=?, result_json=?, error=?, updated_at=?,
                lease_owner=NULL, lease_until=NULL,
                available_at=CASE WHEN ?='QUEUED' THEN ? ELSE available_at END
            WHERE job_id=?
            """,
            (
                final,
                json.dumps(result, sort_keys=True, default=str),
                error,
                _iso(),
                final,
                _iso(_now() + timedelta(seconds=5)),
                job_id,
            ),
        )
        self.connection.commit()
        return self.job(job_id)

    def run_once(self, registry: ToolRegistry, runner_id: str, *, lease_seconds: int = 120) -> dict[str, Any]:
        self.heartbeat(runner_id)
        job = self.lease(runner_id, lease_seconds=lease_seconds)
        if job is None:
            return {"status": "IDLE", "runner_id": runner_id}
        try:
            definition = registry.describe(job["tool_name"])
            request = ToolRequest(
                tool=job["tool_name"],
                operation=job["tool_name"],
                environment=Environment(job["environment"]),
                risk=definition.risk,
                args=dict(job["args"]),
            )
            result = registry.invoke(
                ToolInvocation(
                    request,
                    run_id=job["job_id"],
                    approved=bool(job["approved"]),
                    actor_mode=ActorMode(job["actor_mode"]),
                )
            )
            status = "SUCCESS" if str(result.get("status") or "PASS") not in {"FAIL", "ERROR"} else "FAIL"
            return self.complete(job["job_id"], runner_id, status=status, result=result)
        except PermissionError as exc:
            result = {"status": "BLOCKED_APPROVAL", "error": str(exc)}
            return self.complete(
                job["job_id"],
                runner_id,
                status="BLOCKED_APPROVAL",
                result=result,
                error=str(exc),
            )
        except Exception as exc:
            result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
            return self.complete(
                job["job_id"],
                runner_id,
                status="FAIL",
                result=result,
                error=result["error"],
            )

    @staticmethod
    def _runner(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "runner_id": row["runner_id"],
            "name": row["name"],
            "capabilities": json.loads(row["capabilities_json"]),
            "registered_at": row["registered_at"],
            "heartbeat_at": row["heartbeat_at"],
            "metadata": json.loads(row["metadata_json"]),
        }

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "tool_name": row["tool_name"],
            "args": json.loads(row["args_json"]),
            "actor_mode": row["actor_mode"],
            "environment": row["environment"],
            "approved": bool(row["approved"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "available_at": row["available_at"],
            "lease_owner": row["lease_owner"],
            "lease_until": row["lease_until"],
            "attempts": int(row["attempts"]),
            "max_attempts": int(row["max_attempts"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
        }
