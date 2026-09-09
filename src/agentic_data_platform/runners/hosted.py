"""Durable hostable ADE runner control plane with leases and policy-safe execution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from agentic_data_platform.models import ActorMode, Environment, InteractionMode, ToolRequest, new_id
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


def _fingerprint(value: Any) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def normalize_workspace_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(policy or {})
    forbidden_keys = {"credentials", "secrets", "tokens", "api_keys", "passwords"}
    forbidden = sorted(forbidden_keys & set(raw))
    if forbidden:
        raise ValueError(
            "hosted workspace policy accepts credential references only; forbidden keys: "
            + ", ".join(forbidden)
        )
    filesystem_scope = str(raw.get("filesystem_scope") or "workspace").casefold()
    if filesystem_scope not in {"workspace", "read_only_workspace"}:
        raise ValueError("filesystem_scope must be workspace or read_only_workspace")
    result = {
        "execution_class": "HOSTED_ISOLATED_WORKSPACE",
        "sandbox_required": bool(raw.get("sandbox_required", False)),
        "workspace_id": str(raw.get("workspace_id") or "default"),
        "filesystem_scope": filesystem_scope,
        "network_enabled": bool(raw.get("network_enabled", False)),
        "memory_mb": max(64, min(int(raw.get("memory_mb", 512)), 32768)),
        "cpus": max(0.1, min(float(raw.get("cpus", 1.0)), 64.0)),
        "pids_limit": max(16, min(int(raw.get("pids_limit", 256)), 4096)),
        "credential_refs": sorted(set(str(item) for item in raw.get("credential_refs") or [])),
    }
    result["policy_fingerprint"] = _fingerprint(result)
    return result


def runner_satisfies_workspace_policy(
    runner: dict[str, Any],
    policy: dict[str, Any],
) -> bool:
    if not policy.get("sandbox_required"):
        return True
    isolation = dict(runner.get("metadata", {}).get("workspace_isolation") or {})
    if not bool(isolation.get("enforced", False)):
        return False
    if str(isolation.get("execution_class") or "") != "HOSTED_ISOLATED_WORKSPACE":
        return False
    if not policy.get("network_enabled", False) and bool(isolation.get("network_enabled", True)):
        return False
    if float(isolation.get("memory_mb", 0) or 0) < float(policy.get("memory_mb", 0) or 0):
        return False
    if float(isolation.get("cpus", 0) or 0) < float(policy.get("cpus", 0) or 0):
        return False
    if int(isolation.get("pids_limit", 0) or 0) < int(policy.get("pids_limit", 0) or 0):
        return False
    supported_scopes = set(isolation.get("filesystem_scopes") or [])
    return policy.get("filesystem_scope") in supported_scopes


class HostedRunnerStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        job_columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(hosted_jobs)").fetchall()
        }
        migrations = {
            "interaction_mode": "TEXT NOT NULL DEFAULT 'agent'",
            "workspace_policy_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, ddl in migrations.items():
            if column not in job_columns:
                self.connection.execute(f"ALTER TABLE hosted_jobs ADD COLUMN {column} {ddl}")
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
        interaction_mode: InteractionMode = InteractionMode.AGENT,
        environment: Environment = Environment.DEV,
        approved: bool = False,
        delay_seconds: int = 0,
        max_attempts: int = 3,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = new_id("hosted_job")
        current = _now()
        policy = normalize_workspace_policy(workspace_policy)
        self.connection.execute(
            """
            INSERT INTO hosted_jobs(
              job_id,tool_name,args_json,actor_mode,environment,approved,status,
              created_at,updated_at,available_at,max_attempts,
              interaction_mode,workspace_policy_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                interaction_mode.value,
                json.dumps(policy, sort_keys=True, default=str),
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

    def workspace_readiness(
        self,
        job_id: str,
        *,
        runner_id: str | None = None,
    ) -> dict[str, Any]:
        job = self.job(job_id)
        policy = job["workspace_policy"]
        candidates = (
            [self.runner(runner_id)]
            if runner_id is not None
            else self.runners()
        )
        compatible = [
            runner["runner_id"]
            for runner in candidates
            if ("*" in set(runner["capabilities"]) or job["tool_name"] in set(runner["capabilities"]))
            and runner_satisfies_workspace_policy(runner, policy)
        ]
        if compatible:
            status = "PASS"
            reason = "at least one runner satisfies capability and workspace isolation policy"
        elif policy.get("sandbox_required"):
            status = "BLOCKED_ISOLATION"
            reason = "no runner satisfies the required hosted workspace isolation contract"
        else:
            status = "NO_COMPATIBLE_RUNNER"
            reason = "no runner advertises the required tool capability"
        return {
            "status": status,
            "job_id": job_id,
            "workspace_policy": policy,
            "compatible_runner_ids": compatible,
            "runner_count_checked": len(candidates),
            "reason": reason,
        }

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
            if "*" not in capabilities and row["tool_name"] not in capabilities:
                continue
            candidate = self._job(row)
            if not runner_satisfies_workspace_policy(
                runner,
                candidate["workspace_policy"],
            ):
                continue
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
        if final not in {
            "SUCCESS",
            "FAIL",
            "BLOCKED_APPROVAL",
            "BLOCKED_POLICY",
            "BLOCKED_ISOLATION",
        }:
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
            runner = self.runner(runner_id)
            capabilities = set(runner["capabilities"])
            queued = self.connection.execute(
                """
                SELECT job_id FROM hosted_jobs
                WHERE status='QUEUED' AND available_at <= ?
                ORDER BY created_at
                """,
                (_iso(),),
            ).fetchall()
            for row in queued:
                candidate = self.job(str(row["job_id"]))
                if "*" not in capabilities and candidate["tool_name"] not in capabilities:
                    continue
                readiness = self.workspace_readiness(
                    candidate["job_id"],
                    runner_id=runner_id,
                )
                if readiness["status"] == "BLOCKED_ISOLATION":
                    return {
                        **readiness,
                        "runner_id": runner_id,
                    }
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
                    interaction_mode=InteractionMode(job["interaction_mode"]),
                )
            )
            status = "SUCCESS" if str(result.get("status") or "PASS") not in {"FAIL", "ERROR"} else "FAIL"
            return self.complete(job["job_id"], runner_id, status=status, result=result)
        except PermissionError as exc:
            message = str(exc)
            blocked_status = (
                "BLOCKED_APPROVAL"
                if "approval" in message.casefold()
                else "BLOCKED_POLICY"
            )
            result = {"status": blocked_status, "error": message}
            return self.complete(
                job["job_id"],
                runner_id,
                status=blocked_status,
                result=result,
                error=message,
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
            "interaction_mode": (
                row["interaction_mode"]
                if "interaction_mode" in row.keys()
                else "agent"
            ),
            "environment": row["environment"],
            "approved": bool(row["approved"]),
            "workspace_policy": normalize_workspace_policy(
                json.loads(row["workspace_policy_json"])
                if "workspace_policy_json" in row.keys() and row["workspace_policy_json"]
                else {}
            ),
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
