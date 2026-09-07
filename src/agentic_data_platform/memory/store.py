from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any
from agentic_data_platform.models import new_id, utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
 memory_id TEXT PRIMARY KEY, scope TEXT NOT NULL, project_id TEXT, content TEXT NOT NULL,
 tags_json TEXT NOT NULL, citations_json TEXT NOT NULL, expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS training (
 training_id TEXT PRIMARY KEY, scope TEXT NOT NULL, project_id TEXT, kind TEXT NOT NULL, content TEXT NOT NULL,
 source TEXT, citations_json TEXT NOT NULL, applied_count INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

class MemoryStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
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
            "INSERT INTO training VALUES (?,?,?,?,?,?,?,0,?,?)",
            (training_id, scope, project_id, kind, content, source, json.dumps(citations or []), now, now),
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
