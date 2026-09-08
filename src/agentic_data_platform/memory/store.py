from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from agentic_data_platform.models import new_id, utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
 memory_id TEXT PRIMARY KEY, scope TEXT NOT NULL, project_id TEXT, content TEXT NOT NULL,
 tags_json TEXT NOT NULL, citations_json TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training (
 training_id TEXT PRIMARY KEY, scope TEXT NOT NULL, project_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
 content TEXT NOT NULL, source TEXT, citations_json TEXT NOT NULL, applied_count INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
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
        self._conn.commit()

    def save_memory(self, content: str, *, scope: str = "project", project_id: str | None = None,
                    tags: list[str] | None = None, citations: list[str] | None = None,
                    expires_at: str | None = None) -> str:
        content = content.strip()
        if not content:
            raise ValueError("memory content cannot be empty")
        row = self._conn.execute(
            "SELECT memory_id FROM memories WHERE scope=? AND project_id IS ? AND content=?",
            (scope, project_id, content),
        ).fetchone()
        now = utc_now()
        if row:
            self._conn.execute("UPDATE memories SET updated_at=? WHERE memory_id=?", (now, row["memory_id"]))
            self._conn.commit()
            return str(row["memory_id"])
        memory_id = new_id("memory")
        self._conn.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?)",
            (memory_id, scope, project_id, content, json.dumps(tags or []), json.dumps(citations or []), expires_at, now, now),
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
