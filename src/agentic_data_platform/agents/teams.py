"""Persistent, dependency-aware agent-team orchestration for ADE."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping

from agentic_data_platform.agents.parallel import (
    ParallelSubagentCoordinator,
    SubagentDefinition,
    SubagentTask,
)
from agentic_data_platform.models import ActorMode, new_id, utc_now
from agentic_data_platform.teammates import TeammateStore


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_teams (
  team_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  supervisor_prompt TEXT NOT NULL DEFAULT '',
  max_parallel INTEGER NOT NULL DEFAULT 4,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_team_members (
  team_id TEXT NOT NULL,
  teammate_id TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  PRIMARY KEY(team_id, teammate_id)
);
CREATE TABLE IF NOT EXISTS agent_team_runs (
  run_id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL,
  status TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  result_json TEXT,
  evidence_fingerprint TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_team_runs_team
ON agent_team_runs(team_id, created_at);
"""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class TeamStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def create(
        self,
        name: str,
        *,
        description: str | None = None,
        supervisor_prompt: str = "",
        max_parallel: int = 4,
    ) -> dict[str, Any]:
        if not str(name).strip():
            raise ValueError("team name is required")
        team_id = new_id("team")
        now = utc_now()
        self.connection.execute(
            "INSERT INTO agent_teams VALUES (?,?,?,?,?,?,?)",
            (
                team_id,
                str(name).strip(),
                description,
                str(supervisor_prompt or ""),
                max(1, min(int(max_parallel), 32)),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.get(team_id)

    def get(self, team_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM agent_teams WHERE team_id=?",
            (team_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"team not found: {team_id}")
        value = dict(row)
        value["members"] = self.members(team_id)
        value["team_fingerprint"] = _digest(
            {
                "team_id": team_id,
                "name": value["name"],
                "description": value["description"],
                "supervisor_prompt": value["supervisor_prompt"],
                "max_parallel": value["max_parallel"],
                "members": value["members"],
            }
        )
        return value

    def list(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT team_id FROM agent_teams ORDER BY name, team_id"
        ).fetchall()
        return [self.get(str(row["team_id"])) for row in rows]

    def edit(
        self,
        team_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        supervisor_prompt: str | None = None,
        max_parallel: int | None = None,
    ) -> dict[str, Any]:
        current = self.get(team_id)
        self.connection.execute(
            """
            UPDATE agent_teams
            SET name=?, description=?, supervisor_prompt=?, max_parallel=?, updated_at=?
            WHERE team_id=?
            """,
            (
                str(name).strip() if name is not None else current["name"],
                description if description is not None else current["description"],
                supervisor_prompt if supervisor_prompt is not None else current["supervisor_prompt"],
                max(1, min(int(max_parallel), 32))
                if max_parallel is not None
                else current["max_parallel"],
                utc_now(),
                team_id,
            ),
        )
        self.connection.commit()
        return self.get(team_id)

    def delete(self, team_id: str) -> dict[str, Any]:
        current = self.get(team_id)
        self.connection.execute("DELETE FROM agent_team_members WHERE team_id=?", (team_id,))
        cursor = self.connection.execute("DELETE FROM agent_teams WHERE team_id=?", (team_id,))
        self.connection.commit()
        return {
            "status": "PASS",
            "removed": cursor.rowcount == 1,
            "team": current,
        }

    def set_members(self, team_id: str, teammate_ids: Iterable[str]) -> dict[str, Any]:
        self.get(team_id)
        values = list(dict.fromkeys(str(item) for item in teammate_ids))
        self.connection.execute("DELETE FROM agent_team_members WHERE team_id=?", (team_id,))
        now = utc_now()
        for position, teammate_id in enumerate(values, start=1):
            self.connection.execute(
                "INSERT INTO agent_team_members VALUES (?,?,?,?)",
                (team_id, teammate_id, position, now),
            )
        self.connection.execute(
            "UPDATE agent_teams SET updated_at=? WHERE team_id=?",
            (now, team_id),
        )
        self.connection.commit()
        return self.get(team_id)

    def members(self, team_id: str) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT teammate_id FROM agent_team_members
            WHERE team_id=?
            ORDER BY position, teammate_id
            """,
            (team_id,),
        ).fetchall()
        return [str(row["teammate_id"]) for row in rows]

    def start_run(self, team_id: str, plan: Mapping[str, Any]) -> dict[str, Any]:
        self.get(team_id)
        run_id = new_id("team_run")
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO agent_team_runs(
              run_id,team_id,status,plan_json,result_json,evidence_fingerprint,
              created_at,completed_at
            ) VALUES (?,?,'RUNNING',?,NULL,NULL,?,NULL)
            """,
            (run_id, team_id, json.dumps(dict(plan), sort_keys=True, default=str), now),
        )
        self.connection.commit()
        return self.run(run_id)

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        result: Mapping[str, Any],
        evidence_fingerprint: str,
    ) -> dict[str, Any]:
        self.connection.execute(
            """
            UPDATE agent_team_runs
            SET status=?, result_json=?, evidence_fingerprint=?, completed_at=?
            WHERE run_id=?
            """,
            (
                str(status),
                json.dumps(dict(result), sort_keys=True, default=str),
                evidence_fingerprint,
                utc_now(),
                run_id,
            ),
        )
        self.connection.commit()
        return self.run(run_id)

    def run(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM agent_team_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"team run not found: {run_id}")
        value = dict(row)
        value["plan"] = json.loads(value.pop("plan_json") or "{}")
        value["result"] = json.loads(value.pop("result_json")) if value["result_json"] else None
        return value

    def runs(self, team_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self.get(team_id)
        rows = self.connection.execute(
            """
            SELECT run_id FROM agent_team_runs
            WHERE team_id=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (team_id, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [self.run(str(row["run_id"])) for row in rows]


TeamExecutor = Callable[[SubagentTask], dict[str, Any]]


@dataclass(frozen=True)
class TeamTask:
    task_id: str
    teammate_id: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    metadata: Mapping[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "teammate_id": self.teammate_id,
            "prompt": self.prompt,
            "depends_on": list(self.depends_on),
            "metadata": dict(self.metadata or {}),
        }


class TeamCoordinator:
    def __init__(
        self,
        teams: TeamStore,
        teammates: TeammateStore,
        executor: TeamExecutor,
    ) -> None:
        self.teams = teams
        self.teammates = teammates
        self.executor = executor

    def _definition(self, teammate_id: str) -> SubagentDefinition:
        teammate = self.teammates.get(teammate_id)
        budgets = dict(teammate.get("budgets") or {})
        try:
            actor_mode = ActorMode(str(teammate.get("actor_mode") or "analyst"))
        except ValueError as exc:
            raise ValueError(
                f"invalid actor_mode for teammate {teammate_id}: {teammate.get('actor_mode')}"
            ) from exc
        prompt_parts = [
            f"Team role: {teammate.get('role') or 'specialist'}.",
            str(teammate.get("system_prompt") or "").strip(),
        ]
        system_prompt = "\n".join(item for item in prompt_parts if item)
        return SubagentDefinition(
            name=str(teammate["name"]),
            description=str(teammate.get("description") or teammate.get("role") or "team member"),
            allowed_tools=tuple(str(item) for item in teammate.get("allowed_tools") or ()),
            model=str(teammate.get("model") or "inherit"),
            system_prompt=system_prompt,
            actor_mode=actor_mode,
            max_steps=max(1, min(int(budgets.get("max_steps", 8)), 50)),
            timeout_seconds=max(1, min(int(budgets.get("timeout_seconds", 120)), 3600)),
            source=f"teammate:{teammate_id}",
        )

    def _normalize_tasks(
        self,
        team_id: str,
        tasks: Iterable[Mapping[str, Any] | TeamTask],
    ) -> list[TeamTask]:
        team = self.teams.get(team_id)
        members = set(team["members"])
        normalized: list[TeamTask] = []
        ids: set[str] = set()
        for index, raw in enumerate(tasks, start=1):
            if isinstance(raw, TeamTask):
                task = raw
            else:
                task_id = str(raw.get("task_id") or f"task-{index}")
                teammate_id = str(raw.get("teammate_id") or "")
                prompt = str(raw.get("prompt") or "").strip()
                task = TeamTask(
                    task_id=task_id,
                    teammate_id=teammate_id,
                    prompt=prompt,
                    depends_on=tuple(str(item) for item in raw.get("depends_on") or ()),
                    metadata=dict(raw.get("metadata") or {}),
                )
            if not task.task_id or task.task_id in ids:
                raise ValueError(f"duplicate/invalid task_id: {task.task_id}")
            if task.teammate_id not in members:
                raise ValueError(f"teammate is not a member of team: {task.teammate_id}")
            if not task.prompt:
                raise ValueError(f"task prompt is required: {task.task_id}")
            ids.add(task.task_id)
            normalized.append(task)

        for task in normalized:
            missing = sorted(set(task.depends_on) - ids)
            if missing:
                raise ValueError(
                    f"task {task.task_id} has unknown dependencies: {', '.join(missing)}"
                )
            if task.task_id in task.depends_on:
                raise ValueError(f"task cannot depend on itself: {task.task_id}")

        pending = {task.task_id: set(task.depends_on) for task in normalized}
        resolved: set[str] = set()
        while pending:
            ready = sorted(task_id for task_id, deps in pending.items() if deps <= resolved)
            if not ready:
                raise ValueError("team task graph contains a dependency cycle")
            for task_id in ready:
                pending.pop(task_id)
                resolved.add(task_id)
        return normalized

    def plan(
        self,
        team_id: str,
        tasks: Iterable[Mapping[str, Any] | TeamTask],
    ) -> dict[str, Any]:
        team = self.teams.get(team_id)
        normalized = self._normalize_tasks(team_id, tasks)
        members = {
            teammate_id: self.teammates.get(teammate_id)
            for teammate_id in team["members"]
        }
        payload = {
            "team_id": team_id,
            "team_fingerprint": team["team_fingerprint"],
            "max_parallel": int(team["max_parallel"]),
            "tasks": [task.public() for task in normalized],
            "member_contracts": {
                teammate_id: {
                    "role": member.get("role"),
                    "allowed_tools": member.get("allowed_tools"),
                    "budgets": member.get("budgets"),
                    "verification": member.get("verification"),
                    "model": member.get("model"),
                    "actor_mode": member.get("actor_mode"),
                }
                for teammate_id, member in sorted(members.items())
            },
        }
        return {
            "status": "PASS",
            "mode": "PLAN_ONLY",
            **payload,
            "approval_fingerprint": _digest(payload),
        }

    @staticmethod
    def _verification(
        contract: Iterable[Mapping[str, Any] | str],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        findings = []
        for item in contract:
            if isinstance(item, str):
                value = result.get(item)
                findings.append(
                    {
                        "rule": item,
                        "passed": bool(value),
                        "actual": value,
                    }
                )
                continue
            rule = dict(item)
            field = str(rule.get("field") or "")
            value = result.get(field) if field else None
            if "equals" in rule:
                passed = value == rule["equals"]
            elif "in" in rule:
                passed = value in list(rule["in"])
            else:
                passed = bool(value)
            findings.append(
                {
                    "rule": rule,
                    "passed": passed,
                    "actual": value,
                }
            )
        return {
            "status": "PASS" if all(item["passed"] for item in findings) else "FAIL",
            "findings": findings,
            "verification_fingerprint": _digest(findings),
        }

    def run(
        self,
        plan: Mapping[str, Any],
        *,
        approval_fingerprint: str,
    ) -> dict[str, Any]:
        expected = str(plan.get("approval_fingerprint") or "")
        if approval_fingerprint != expected:
            return {
                "status": "STALE_APPROVAL",
                "approval_fingerprint": expected,
            }
        team_id = str(plan["team_id"])
        current_team = self.teams.get(team_id)
        if current_team["team_fingerprint"] != plan.get("team_fingerprint"):
            return {
                "status": "STALE_TEAM",
                "team_id": team_id,
                "current_team_fingerprint": current_team["team_fingerprint"],
            }

        tasks = self._normalize_tasks(team_id, list(plan.get("tasks") or []))
        run_record = self.teams.start_run(team_id, plan)
        remaining = {task.task_id: task for task in tasks}
        outcomes: dict[str, dict[str, Any]] = {}
        waves: list[list[str]] = []

        while remaining:
            blocked = []
            for task_id, task in remaining.items():
                failed_dependencies = [
                    dependency
                    for dependency in task.depends_on
                    if dependency in outcomes and outcomes[dependency]["status"] != "PASS"
                ]
                if failed_dependencies:
                    blocked.append((task_id, failed_dependencies))
            for task_id, failed_dependencies in blocked:
                task = remaining.pop(task_id)
                outcomes[task_id] = {
                    "task_id": task_id,
                    "teammate_id": task.teammate_id,
                    "status": "BLOCKED_DEPENDENCY",
                    "failed_dependencies": failed_dependencies,
                }

            ready = [
                task
                for task in remaining.values()
                if all(
                    dependency in outcomes and outcomes[dependency]["status"] == "PASS"
                    for dependency in task.depends_on
                )
            ]
            if not ready:
                if remaining:
                    raise RuntimeError("validated team plan reached an impossible dependency state")
                break

            wave_ids = [task.task_id for task in ready]
            waves.append(wave_ids)
            subagent_tasks = []
            for task in ready:
                teammate = self.teammates.get(task.teammate_id)
                subagent_tasks.append(
                    SubagentTask(
                        self._definition(task.teammate_id),
                        task.prompt,
                        metadata={
                            **dict(task.metadata or {}),
                            "task_id": task.task_id,
                            "teammate_id": task.teammate_id,
                            "team_id": team_id,
                            "budgets": teammate.get("budgets") or {},
                            "verification": teammate.get("verification") or [],
                        },
                    )
                )

            wave = ParallelSubagentCoordinator(
                self.executor,
                max_workers=int(plan.get("max_parallel") or current_team["max_parallel"]),
            ).run(subagent_tasks)
            for task, result in zip(ready, wave["results"], strict=True):
                teammate = self.teammates.get(task.teammate_id)
                verification = self._verification(
                    teammate.get("verification") or [],
                    result.get("result") or result,
                )
                status = str(result.get("status") or "PASS")
                if status == "PASS" and verification["status"] != "PASS":
                    status = "FAIL_VERIFICATION"
                outcomes[task.task_id] = {
                    "task_id": task.task_id,
                    "teammate_id": task.teammate_id,
                    "status": status,
                    "summary": result.get("summary"),
                    "session_id": result.get("session_id"),
                    "trace_id": result.get("trace_id"),
                    "duration_ms": result.get("duration_ms"),
                    "result": result.get("result") or {},
                    "error": result.get("error"),
                    "verification": verification,
                }
                remaining.pop(task.task_id, None)

        ordered = [outcomes[task.task_id] for task in tasks]
        failed = [
            item
            for item in ordered
            if item["status"] not in {"PASS"}
        ]
        result = {
            "team_id": team_id,
            "run_id": run_record["run_id"],
            "status": "FAIL" if failed else "PASS",
            "waves": waves,
            "task_count": len(ordered),
            "failed_count": len(failed),
            "results": ordered,
        }
        evidence_fingerprint = _digest(result)
        result["evidence_fingerprint"] = evidence_fingerprint
        self.teams.complete_run(
            run_record["run_id"],
            status=result["status"],
            result=result,
            evidence_fingerprint=evidence_fingerprint,
        )
        return result
