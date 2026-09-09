from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from agentic_data_platform.models import new_id, utc_now

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b"
        r"\s*[:=]\s*[\"']?[^\s\"']{8,}"
    ),
)


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def _scope(scope: str) -> str:
    value = str(scope).casefold().strip()
    if value not in {"global", "project"}:
        raise ValueError("memory scope must be global or project")
    return value


def _settings_project_id(scope: str, project_id: str | None) -> str:
    return "" if scope == "global" else str(project_id or "")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
 memory_id TEXT PRIMARY KEY, scope TEXT NOT NULL, project_id TEXT, content TEXT NOT NULL,
 tags_json TEXT NOT NULL, citations_json TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training (
 training_id TEXT PRIMARY KEY, scope TEXT NOT NULL, project_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
 content TEXT NOT NULL, source TEXT, citations_json TEXT NOT NULL, applied_count INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_preferences (
 scope TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
 instructions TEXT NOT NULL DEFAULT '', tool_preferences_json TEXT NOT NULL DEFAULT '{}',
 runtime_preferences_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
 PRIMARY KEY(scope, project_id));
"""

class MemoryStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(training)").fetchall()
        }
        if "name" not in columns:
            self._conn.execute(
                "ALTER TABLE training ADD COLUMN name TEXT NOT NULL DEFAULT ''"
            )
        memory_columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "kind" not in memory_columns:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN kind TEXT NOT NULL DEFAULT 'durable'"
            )
        self._conn.commit()

    def save_memory(self, content: str, *, scope: str = "project", project_id: str | None = None,
                    tags: list[str] | None = None, citations: list[str] | None = None,
                    expires_at: str | None = None, kind: str = "durable") -> str:
        scope = _scope(scope)
        kind = str(kind).casefold().strip()
        if kind != "durable":
            raise ValueError("temporary task state is not persisted as memory")
        if not self.memory_settings(scope=scope, project_id=project_id)["enabled"]:
            raise PermissionError(f"{scope} memory is disabled")
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        if _contains_secret(content):
            raise ValueError("secret-like content cannot be persisted in memory")
        row = self._conn.execute(
            "SELECT memory_id FROM memories WHERE scope=? AND project_id IS ? AND content=?",
            (scope, project_id, content),
        ).fetchone()
        now = utc_now()
        if row:
            self._conn.execute(
                "UPDATE memories SET tags_json=?, citations_json=?, expires_at=?, kind=?, updated_at=? WHERE memory_id=?",
                (
                    json.dumps(tags or []),
                    json.dumps(citations or []),
                    expires_at,
                    kind,
                    now,
                    row["memory_id"],
                ),
            )
            self._conn.commit()
            return str(row["memory_id"])
        memory_id = new_id("memory")
        self._conn.execute(
            """
            INSERT INTO memories(
              memory_id,scope,project_id,content,tags_json,citations_json,
              expires_at,created_at,updated_at,kind
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                memory_id,
                scope,
                project_id,
                content,
                json.dumps(tags or []),
                json.dumps(citations or []),
                expires_at,
                now,
                now,
                kind,
            ),
        )
        self._conn.commit()
        return memory_id

    def list_memories(self, *, scope: str | None = None, project_id: str | None = None,
                      limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM memories WHERE (expires_at IS NULL OR expires_at > ?)"
        params: list[Any] = [utc_now()]
        if scope:
            sql += " AND scope=?"
            params.append(scope)
        if project_id:
            sql += " AND (project_id=? OR project_id IS NULL)"
            params.append(project_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [{**dict(r), "tags": json.loads(r["tags_json"] or "[]"),
                 "citations": json.loads(r["citations_json"] or "[]")} for r in rows]

    def search(self, query: str, *, project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        needle = query.casefold()
        return [m for m in self.list_memories(project_id=project_id, limit=1000)
                if needle in m["content"].casefold() or any(needle in tag.casefold() for tag in m["tags"])][:limit]

    def remove_memory(self, memory_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
        self._conn.commit()
        return cur.rowcount == 1

    def memory_settings(
        self,
        *,
        scope: str = "project",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        scope = _scope(scope)
        key = _settings_project_id(scope, project_id)
        row = self._conn.execute(
            "SELECT * FROM memory_preferences WHERE scope=? AND project_id=?",
            (scope, key),
        ).fetchone()
        if row is None:
            return {
                "scope": scope,
                "project_id": project_id if scope == "project" else None,
                "enabled": True,
                "instructions": "",
                "tool_preferences": {},
                "runtime_preferences": {},
            }
        return {
            "scope": scope,
            "project_id": project_id if scope == "project" else None,
            "enabled": bool(row["enabled"]),
            "instructions": str(row["instructions"] or ""),
            "tool_preferences": json.loads(row["tool_preferences_json"] or "{}"),
            "runtime_preferences": json.loads(row["runtime_preferences_json"] or "{}"),
            "updated_at": row["updated_at"],
        }

    def configure_memory(
        self,
        *,
        scope: str = "project",
        project_id: str | None = None,
        enabled: bool | None = None,
        instructions: str | None = None,
        tool_preferences: dict[str, Any] | None = None,
        runtime_preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = _scope(scope)
        key = _settings_project_id(scope, project_id)
        current = self.memory_settings(scope=scope, project_id=project_id)
        next_instructions = current["instructions"] if instructions is None else str(instructions).strip()
        if next_instructions and _contains_secret(next_instructions):
            raise ValueError("secret-like content cannot be persisted in personalization")
        next_tools = current["tool_preferences"] if tool_preferences is None else dict(tool_preferences)
        next_runtime = current["runtime_preferences"] if runtime_preferences is None else dict(runtime_preferences)
        serialized_preferences = json.dumps(
            {"tool_preferences": next_tools, "runtime_preferences": next_runtime},
            sort_keys=True,
            default=str,
        )
        if _contains_secret(serialized_preferences):
            raise ValueError("secret-like content cannot be persisted in personalization")
        next_enabled = current["enabled"] if enabled is None else bool(enabled)
        now = utc_now()
        self._conn.execute(
            """
            INSERT INTO memory_preferences(
              scope,project_id,enabled,instructions,tool_preferences_json,
              runtime_preferences_json,updated_at
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(scope,project_id) DO UPDATE SET
              enabled=excluded.enabled,
              instructions=excluded.instructions,
              tool_preferences_json=excluded.tool_preferences_json,
              runtime_preferences_json=excluded.runtime_preferences_json,
              updated_at=excluded.updated_at
            """,
            (
                scope,
                key,
                int(next_enabled),
                next_instructions,
                json.dumps(next_tools, sort_keys=True, default=str),
                json.dumps(next_runtime, sort_keys=True, default=str),
                now,
            ),
        )
        self._conn.commit()
        return self.memory_settings(scope=scope, project_id=project_id)

    def personalization(self, *, project_id: str | None = None) -> dict[str, Any]:
        global_settings = self.memory_settings(scope="global")
        project_settings = (
            self.memory_settings(scope="project", project_id=project_id)
            if project_id is not None
            else None
        )
        tool_preferences = dict(global_settings["tool_preferences"])
        runtime_preferences = dict(global_settings["runtime_preferences"])
        instructions = [global_settings["instructions"]] if global_settings["instructions"] else []
        if project_settings is not None:
            tool_preferences.update(project_settings["tool_preferences"])
            runtime_preferences.update(project_settings["runtime_preferences"])
            if project_settings["instructions"]:
                instructions.append(project_settings["instructions"])
        return {
            "global": global_settings,
            "project": project_settings,
            "effective": {
                "enabled": global_settings["enabled"] and (
                    project_settings["enabled"] if project_settings is not None else True
                ),
                "instructions": instructions,
                "tool_preferences": tool_preferences,
                "runtime_preferences": runtime_preferences,
            },
        }

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        citations: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"memory not found: {memory_id}")
        next_content = str(row["content"]) if content is None else str(content).strip()
        if not next_content:
            raise ValueError("memory content cannot be empty")
        if _contains_secret(next_content):
            raise ValueError("secret-like content cannot be persisted in memory")
        next_tags = json.loads(row["tags_json"] or "[]") if tags is None else list(tags)
        next_citations = (
            json.loads(row["citations_json"] or "[]")
            if citations is None
            else list(citations)
        )
        next_expires = row["expires_at"] if expires_at is None else expires_at
        self._conn.execute(
            """
            UPDATE memories
            SET content=?, tags_json=?, citations_json=?, expires_at=?, updated_at=?
            WHERE memory_id=?
            """,
            (
                next_content,
                json.dumps(next_tags),
                json.dumps(next_citations),
                next_expires,
                utc_now(),
                memory_id,
            ),
        )
        self._conn.commit()
        updated = self._conn.execute(
            "SELECT * FROM memories WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        value = dict(updated)
        value["tags"] = json.loads(value.pop("tags_json") or "[]")
        value["citations"] = json.loads(value.pop("citations_json") or "[]")
        return value

    def reset_memories(
        self,
        *,
        scope: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        scope = _scope(scope)
        if scope == "global":
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE scope='global'"
            )
        else:
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE scope='project' AND project_id IS ?",
                (project_id,),
            )
        self._conn.commit()
        return {
            "scope": scope,
            "project_id": project_id if scope == "project" else None,
            "removed": int(cursor.rowcount),
        }

    def save_training(self, kind: str, content: str, *, scope: str = "project", project_id: str | None = None,
                      source: str | None = None, citations: list[str] | None = None) -> str:
        content = content.strip()
        if not content:
            raise ValueError("training content cannot be empty")
        row = self._conn.execute(
            "SELECT training_id FROM training WHERE scope=? AND project_id IS ? AND kind=? AND content=?",
            (scope, project_id, kind, content),
        ).fetchone()
        now = utc_now()
        if row:
            self._conn.execute("UPDATE training SET updated_at=? WHERE training_id=?", (now, row["training_id"]))
            self._conn.commit()
            return str(row["training_id"])
        training_id = new_id("training")
        self._conn.execute(
            """
            INSERT INTO training(
              training_id, scope, project_id, kind, name, content,
              source, citations_json, applied_count, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,0,?,?)
            """,
            (
                training_id,
                scope,
                project_id,
                kind,
                "",
                content,
                source,
                json.dumps(citations or []),
                now,
                now,
            ),
        )
        self._conn.commit()
        return training_id

    def list_training(self, *, project_id: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM training WHERE 1=1"
        params: list[Any] = []
        if project_id:
            sql += " AND (project_id=? OR project_id IS NULL)"
            params.append(project_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC"
        return [{**dict(r), "citations": json.loads(r["citations_json"] or "[]")}
                for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def mark_training_applied(self, training_id: str) -> None:
        self._conn.execute(
            "UPDATE training SET applied_count=applied_count+1, updated_at=? WHERE training_id=?",
            (utc_now(), training_id),
        )
        self._conn.commit()

    def remove_training(self, training_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM training WHERE training_id=?", (training_id,))
        self._conn.commit()
        return cur.rowcount == 1


    @staticmethod
    def normalize_training_name(name: str) -> str:
        value = re.sub(r"[^a-z0-9_-]+", "-", name.casefold().strip())
        value = value.strip("-_")[:64]
        if not value or not re.fullmatch(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?", value):
            raise ValueError("invalid training name")
        return value

    def save_named_training(
        self,
        kind: str,
        name: str,
        content: str,
        *,
        scope: str = "project",
        project_id: str | None = None,
        source: str | None = None,
        citations: list[str] | None = None,
        max_per_kind: int = 50,
    ) -> dict[str, Any]:
        allowed = {"pattern", "rule", "glossary", "standard", "context", "playbook"}
        if kind not in allowed:
            raise ValueError(f"invalid training kind: {kind}")
        if scope not in {"project", "global"}:
            raise ValueError("training scope must be project or global")
        normalized = self.normalize_training_name(name)
        text = content.strip()
        if not text:
            raise ValueError("training content cannot be empty")
        if len(text) > 1800:
            raise ValueError("training content exceeds 1800 characters")
        existing = self._conn.execute(
            """
            SELECT * FROM training
            WHERE scope=? AND project_id IS ? AND kind=? AND name=?
            """,
            (scope, project_id, kind, normalized),
        ).fetchone()
        now = utc_now()
        if existing:
            self._conn.execute(
                """
                UPDATE training
                SET content=?, source=?, citations_json=?, updated_at=?
                WHERE training_id=?
                """,
                (
                    text,
                    source,
                    json.dumps(citations or []),
                    now,
                    existing["training_id"],
                ),
            )
            self._conn.commit()
            return {
                "action": "updated",
                "training_id": str(existing["training_id"]),
                "kind": kind,
                "name": normalized,
                "scope": scope,
                "applied_count": int(existing["applied_count"]),
            }

        count = int(
            self._conn.execute(
                """
                SELECT COUNT(*) AS count FROM training
                WHERE scope=? AND project_id IS ? AND kind=? AND name!=''
                """,
                (scope, project_id, kind),
            ).fetchone()["count"]
        )
        if count >= max_per_kind:
            raise RuntimeError(
                f"training limit reached for {kind}: {count}/{max_per_kind}"
            )
        training_id = new_id("training")
        self._conn.execute(
            """
            INSERT INTO training(
              training_id, scope, project_id, kind, name, content,
              source, citations_json, applied_count, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,0,?,?)
            """,
            (
                training_id,
                scope,
                project_id,
                kind,
                normalized,
                text,
                source,
                json.dumps(citations or []),
                now,
                now,
            ),
        )
        self._conn.commit()
        return {
            "action": "saved",
            "training_id": training_id,
            "kind": kind,
            "name": normalized,
            "scope": scope,
            "applied_count": 0,
        }

    def get_named_training(
        self,
        scope: str,
        kind: str,
        name: str,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = self.normalize_training_name(name)
        row = self._conn.execute(
            """
            SELECT * FROM training
            WHERE scope=? AND project_id IS ? AND kind=? AND name=?
            """,
            (scope, project_id, kind, normalized),
        ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "citations": json.loads(row["citations_json"] or "[]"),
        }

    def list_named_training(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM training WHERE name!=''"
        params: list[Any] = []
        if scope:
            sql += " AND scope=?"
            params.append(scope)
        if project_id:
            sql += " AND (project_id=? OR project_id IS NULL)"
            params.append(project_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        sql += " ORDER BY applied_count DESC, updated_at DESC, name"
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                **dict(row),
                "citations": json.loads(row["citations_json"] or "[]"),
            }
            for row in rows
        ]

    def remove_named_training(
        self,
        scope: str,
        kind: str,
        name: str,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        entry = self.get_named_training(
            scope,
            kind,
            name,
            project_id=project_id,
        )
        if entry is None:
            return {
                "action": "not_found",
                "kind": kind,
                "name": self.normalize_training_name(name),
                "scope": scope,
            }
        self._conn.execute(
            "DELETE FROM training WHERE training_id=?",
            (entry["training_id"],),
        )
        self._conn.commit()
        return {
            "action": "removed",
            "kind": kind,
            "name": entry["name"],
            "scope": scope,
            "applied_count": int(entry["applied_count"]),
        }

    def named_training_counts(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, int]:
        counts = {
            "pattern": 0,
            "rule": 0,
            "glossary": 0,
            "standard": 0,
            "context": 0,
            "playbook": 0,
        }
        for item in self.list_named_training(
            scope=scope,
            project_id=project_id,
        ):
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        return counts

    def named_training_budget(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        budget: int = 48000,
    ) -> dict[str, Any]:
        used = sum(
            len(str(item["content"]))
            for item in self.list_named_training(
                scope=scope,
                project_id=project_id,
            )
        )
        return {
            "used": used,
            "budget": budget,
            "percent": round((used / budget) * 100, 1) if budget else 0.0,
        }
