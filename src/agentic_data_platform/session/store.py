"""Persistent session, message, todo, reminder and run-state storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from agentic_data_platform.models import new_id, utc_now


class SessionStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              title TEXT,
              status TEXT NOT NULL,
              provider TEXT,
              model TEXT,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_messages (
              message_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              sequence INTEGER NOT NULL,
              role TEXT NOT NULL,
              content_json TEXT NOT NULL,
              error_json TEXT,
              metadata_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(session_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS session_todos (
              todo_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              text TEXT NOT NULL,
              status TEXT NOT NULL,
              priority INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_reminders (
              reminder_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              text TEXT NOT NULL,
              trigger_json TEXT NOT NULL,
              delivered INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_state (
              session_id TEXT PRIMARY KEY,
              state_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON session_messages(session_id, sequence);
            CREATE INDEX IF NOT EXISTS idx_todos_session ON session_todos(session_id, status);
            """
        )
        todo_columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(session_todos)").fetchall()
        }
        todo_migrations = {
            "position": "INTEGER NOT NULL DEFAULT 0",
            "dependencies_json": "TEXT NOT NULL DEFAULT '[]'",
            "evidence_json": "TEXT NOT NULL DEFAULT '[]'",
            "plan_fingerprint": "TEXT",
            "subagent_id": "TEXT",
            "progress": "REAL NOT NULL DEFAULT 0",
            "verified": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, ddl in todo_migrations.items():
            if column not in todo_columns:
                self.connection.execute(
                    f"ALTER TABLE session_todos ADD COLUMN {column} {ddl}"
                )
        self.connection.commit()

    def create(
        self,
        *,
        session_id: str | None = None,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = session_id or new_id("session")
        now = utc_now()
        self.connection.execute(
            "INSERT INTO sessions VALUES (?, ?, 'IDLE', ?, ?, ?, ?, ?)",
            (value, title, provider, model, json.dumps(dict(metadata or {}), sort_keys=True), now, now),
        )
        self.connection.execute(
            "INSERT INTO session_state VALUES (?, '{}', ?)",
            (value, now),
        )
        self.connection.commit()
        return self.get(value)

    def get(self, session_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"session not found: {session_id}")
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        value["message_count"] = int(
            self.connection.execute(
                "SELECT COUNT(*) AS count FROM session_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()["count"]
        )
        value["open_todos"] = int(
            self.connection.execute(
                "SELECT COUNT(*) AS count FROM session_todos WHERE session_id = ? AND status != 'DONE'",
                (session_id,),
            ).fetchone()["count"]
        )
        return value

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [self.get(str(row["session_id"])) for row in rows]

    def set_status(self, session_id: str, status: str) -> dict[str, Any]:
        allowed = {"IDLE", "RUNNING", "WAITING", "COMPACTING", "RETRYING", "COMPLETED", "FAILED", "CANCELLED"}
        if status not in allowed:
            raise ValueError(f"invalid session status: {status}")
        self.connection.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (status, utc_now(), session_id),
        )
        self.connection.commit()
        return self.get(session_id)

    def append_message(
        self,
        session_id: str,
        role: str,
        content: Any,
        *,
        error: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"invalid message role: {role}")
        self.get(session_id)
        sequence = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS seq FROM session_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()["seq"]
        )
        message_id = new_id("msg")
        self.connection.execute(
            "INSERT INTO session_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                sequence,
                role,
                json.dumps(content, default=str),
                json.dumps(dict(error), default=str) if error else None,
                json.dumps(dict(metadata or {}), sort_keys=True, default=str),
                utc_now(),
            ),
        )
        self.connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (utc_now(), session_id),
        )
        self.connection.commit()
        return self.message(message_id)

    def message(self, message_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM session_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"message not found: {message_id}")
        value = dict(row)
        value["content"] = json.loads(value.pop("content_json"))
        value["error"] = json.loads(value.pop("error_json")) if value["error_json"] else None
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        return value

    def messages(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT message_id FROM session_messages WHERE session_id = ? ORDER BY sequence"
        params: list[Any] = [session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        rows = self.connection.execute(sql, tuple(params)).fetchall()
        return [self.message(str(row["message_id"])) for row in rows]

    def revert_last(self, session_id: str, *, roles: tuple[str, ...] = ("assistant", "tool")) -> dict[str, Any]:
        placeholders = ",".join("?" for _ in roles)
        row = self.connection.execute(
            f"SELECT message_id FROM session_messages WHERE session_id = ? AND role IN ({placeholders}) ORDER BY sequence DESC LIMIT 1",
            (session_id, *roles),
        ).fetchone()
        if row is None:
            return {"session_id": session_id, "reverted": False}
        message = self.message(str(row["message_id"]))
        self.connection.execute(
            "DELETE FROM session_messages WHERE message_id = ?",
            (message["message_id"],),
        )
        self.connection.commit()
        return {"session_id": session_id, "reverted": True, "message": message}

    def add_todo(
        self,
        session_id: str,
        text: str,
        *,
        priority: int = 0,
        position: int | None = None,
        dependencies: list[str] | None = None,
        plan_fingerprint: str | None = None,
        subagent_id: str | None = None,
    ) -> dict[str, Any]:
        self.get(session_id)
        value = str(text).strip()
        if not value:
            raise ValueError("todo text cannot be empty")
        dependency_ids = [str(item) for item in dependencies or []]
        if dependency_ids:
            rows = self.connection.execute(
                f"SELECT todo_id, session_id FROM session_todos WHERE todo_id IN ({','.join('?' for _ in dependency_ids)})",
                tuple(dependency_ids),
            ).fetchall()
            if len(rows) != len(set(dependency_ids)) or any(row["session_id"] != session_id for row in rows):
                raise ValueError("todo dependencies must exist in the same session")
        if position is None:
            position = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 AS next_position FROM session_todos WHERE session_id=?",
                    (session_id,),
                ).fetchone()["next_position"]
            )
        todo_id = new_id("todo")
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO session_todos(
              todo_id,session_id,text,status,priority,created_at,updated_at,
              position,dependencies_json,evidence_json,plan_fingerprint,
              subagent_id,progress,verified
            ) VALUES (?,?,?,'OPEN',?,?,?,?,?,'[]',?,?,0,0)
            """,
            (
                todo_id,
                session_id,
                value,
                int(priority),
                now,
                now,
                int(position),
                json.dumps(dependency_ids, sort_keys=True),
                plan_fingerprint,
                subagent_id,
            ),
        )
        self.connection.commit()
        return self.todo(todo_id)

    def todo(self, todo_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM session_todos WHERE todo_id = ?",
            (todo_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"todo not found: {todo_id}")
        value = dict(row)
        value["dependencies"] = json.loads(value.pop("dependencies_json", "[]") or "[]")
        value["evidence"] = json.loads(value.pop("evidence_json", "[]") or "[]")
        value["verified"] = bool(value.get("verified"))
        value["progress"] = float(value.get("progress") or 0)
        return value

    def _dependencies_complete(self, todo: Mapping[str, Any]) -> bool:
        dependencies = list(todo.get("dependencies") or [])
        if not dependencies:
            return True
        rows = [self.todo(todo_id) for todo_id in dependencies]
        return all(item["status"] == "DONE" and item["verified"] for item in rows)

    def update_todo(
        self,
        todo_id: str,
        status: str,
        *,
        progress: float | None = None,
        evidence: list[Mapping[str, Any] | str] | None = None,
        verified: bool | None = None,
    ) -> dict[str, Any]:
        if status not in {"OPEN", "IN_PROGRESS", "DONE", "BLOCKED"}:
            raise ValueError(f"invalid todo status: {status}")
        current = self.todo(todo_id)
        next_verified = current["verified"] if verified is None else bool(verified)
        next_evidence = current["evidence"] if evidence is None else list(evidence)
        next_progress = current["progress"] if progress is None else max(0.0, min(float(progress), 100.0))
        if status == "DONE":
            if not next_verified:
                raise PermissionError("todo cannot be DONE until verification passes")
            if not next_evidence:
                raise PermissionError("todo cannot be DONE without verification evidence")
            if not self._dependencies_complete(current):
                raise PermissionError("todo dependencies must be verified DONE before completion")
            next_progress = 100.0
        elif status == "OPEN":
            next_verified = False
            next_progress = 0.0 if progress is None else next_progress
        self.connection.execute(
            """
            UPDATE session_todos
            SET status=?, progress=?, evidence_json=?, verified=?, updated_at=?
            WHERE todo_id=?
            """,
            (
                status,
                next_progress,
                json.dumps(next_evidence, sort_keys=True, default=str),
                int(next_verified),
                utc_now(),
                todo_id,
            ),
        )
        self.connection.commit()
        return self.todo(todo_id)

    def complete_todo(
        self,
        todo_id: str,
        *,
        evidence: list[Mapping[str, Any] | str],
        verification: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        verification_payload = dict(verification or {})
        if verification_payload and verification_payload.get("status") not in {"PASS", "VERIFIED", True}:
            raise PermissionError("todo verification did not pass")
        combined: list[Mapping[str, Any] | str] = list(evidence)
        if verification_payload:
            combined.append({"verification": verification_payload})
        return self.update_todo(
            todo_id,
            "DONE",
            progress=100,
            evidence=combined,
            verified=True,
        )

    def reopen_todo(self, todo_id: str) -> dict[str, Any]:
        return self.update_todo(todo_id, "OPEN", verified=False)

    def remove_todo(self, todo_id: str) -> dict[str, Any]:
        current = self.todo(todo_id)
        dependents = self.connection.execute(
            "SELECT todo_id, dependencies_json FROM session_todos WHERE session_id=? AND todo_id!=?",
            (current["session_id"], todo_id),
        ).fetchall()
        blocking = [
            str(row["todo_id"])
            for row in dependents
            if todo_id in json.loads(row["dependencies_json"] or "[]")
        ]
        if blocking:
            raise PermissionError(f"todo is required by dependent tasks: {', '.join(blocking)}")
        cursor = self.connection.execute(
            "DELETE FROM session_todos WHERE todo_id=?",
            (todo_id,),
        )
        self.connection.commit()
        return {"todo_id": todo_id, "removed": cursor.rowcount == 1}

    def reorder_todo(self, todo_id: str, position: int) -> dict[str, Any]:
        self.todo(todo_id)
        self.connection.execute(
            "UPDATE session_todos SET position=?, updated_at=? WHERE todo_id=?",
            (max(0, int(position)), utc_now(), todo_id),
        )
        self.connection.commit()
        return self.todo(todo_id)

    def set_todo_dependencies(self, todo_id: str, dependencies: list[str]) -> dict[str, Any]:
        current = self.todo(todo_id)
        dependency_ids = [str(item) for item in dependencies]
        if todo_id in dependency_ids:
            raise ValueError("todo cannot depend on itself")
        for dependency_id in dependency_ids:
            dependency = self.todo(dependency_id)
            if dependency["session_id"] != current["session_id"]:
                raise ValueError("todo dependencies must belong to the same session")
        self.connection.execute(
            "UPDATE session_todos SET dependencies_json=?, updated_at=? WHERE todo_id=?",
            (json.dumps(dependency_ids, sort_keys=True), utc_now(), todo_id),
        )
        self.connection.commit()
        return self.todo(todo_id)

    def todos(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT todo_id FROM session_todos
            WHERE session_id=?
            ORDER BY position, priority DESC, created_at
            """,
            (session_id,),
        ).fetchall()
        return [self.todo(str(row["todo_id"])) for row in rows]

    def todos_from_plan(
        self,
        session_id: str,
        plan: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        fingerprint = str(plan.get("plan_fingerprint") or "")
        if not fingerprint:
            raise ValueError("approved plan_fingerprint is required")
        steps = list(plan.get("steps") or [])
        created: list[dict[str, Any]] = []
        previous_id: str | None = None
        for index, step in enumerate(steps, start=1):
            text = str(
                step.get("description")
                or step.get("name")
                or step.get("tool")
                or f"Plan step {index}"
            )
            todo = self.add_todo(
                session_id,
                text,
                position=index,
                dependencies=[previous_id] if previous_id else [],
                plan_fingerprint=fingerprint,
            )
            created.append(todo)
            previous_id = todo["todo_id"]
        return created

    def add_reminder(
        self,
        session_id: str,
        text: str,
        trigger: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.get(session_id)
        reminder_id = new_id("reminder")
        self.connection.execute(
            "INSERT INTO session_reminders VALUES (?, ?, ?, ?, 0, ?)",
            (reminder_id, session_id, text, json.dumps(dict(trigger), sort_keys=True), utc_now()),
        )
        self.connection.commit()
        return self.reminder(reminder_id)

    def reminder(self, reminder_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM session_reminders WHERE reminder_id = ?",
            (reminder_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"reminder not found: {reminder_id}")
        value = dict(row)
        value["trigger"] = json.loads(value.pop("trigger_json") or "{}")
        value["delivered"] = bool(value["delivered"])
        return value

    def reminders(self, session_id: str, *, undelivered_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT reminder_id FROM session_reminders WHERE session_id = ?"
        if undelivered_only:
            sql += " AND delivered = 0"
        sql += " ORDER BY created_at"
        rows = self.connection.execute(sql, (session_id,)).fetchall()
        return [self.reminder(str(row["reminder_id"])) for row in rows]

    def mark_reminder_delivered(self, reminder_id: str) -> dict[str, Any]:
        self.connection.execute(
            "UPDATE session_reminders SET delivered = 1 WHERE reminder_id = ?",
            (reminder_id,),
        )
        self.connection.commit()
        return self.reminder(reminder_id)

    def state(self, session_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT state_json FROM session_state WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            self.get(session_id)
            return {}
        return json.loads(row["state_json"] or "{}")

    def patch_state(self, session_id: str, patch: Mapping[str, Any]) -> dict[str, Any]:
        state = self.state(session_id)
        state.update(dict(patch))
        self.connection.execute(
            """
            INSERT INTO session_state VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at
            """,
            (session_id, json.dumps(state, sort_keys=True, default=str), utc_now()),
        )
        self.connection.commit()
        return state
