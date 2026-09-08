from __future__ import annotations
import json, sqlite3, threading
from pathlib import Path
from typing import Any
from agentic_data_platform.models import new_id, utc_now
from agentic_data_platform.security.redaction import redact, redact_string

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
 session_id TEXT PRIMARY KEY, project_id TEXT, title TEXT, provider TEXT, model TEXT, status TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
 message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
 metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS generations (
 generation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 finish_reason TEXT, usage_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tool_calls (
 tool_call_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, generation_id TEXT, tool TEXT NOT NULL,
 args_json TEXT NOT NULL, result_json TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS context_snapshots (
 snapshot_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, token_count INTEGER NOT NULL,
 metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
"""

class RuntimeStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:": Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False); self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock(); self._conn.executescript(_SCHEMA); self._conn.commit()
    def create_session(self, *, project_id: str | None = None, title: str = "New session", provider: str = "", model: str = "") -> str:
        session_id, now = new_id("session"), utc_now()
        with self._lock:
            self._conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)",
                               (session_id, project_id, title, provider, model, now, now)); self._conn.commit()
        return session_id
    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None
    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (max(1,min(limit,1000)),)).fetchall()
        return [dict(row) for row in rows]
    def add_message(self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> str:
        message_id, now = new_id("message"), utc_now()
        with self._lock:
            self._conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                               (message_id, session_id, role, redact_string(content), json.dumps(redact(metadata or {}), default=str), now))
            self._conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id)); self._conn.commit()
        return message_id
    def messages(self, session_id: str) -> list[dict[str, Any]]:
        rows=self._conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY created_at,rowid",(session_id,)).fetchall()
        return [{"message_id":r["message_id"],"role":r["role"],"content":r["content"],
                 "metadata":json.loads(r["metadata_json"] or "{}"),"created_at":r["created_at"]} for r in rows]
    def add_generation(self, session_id: str, provider: str, model: str, finish_reason: str | None, usage: dict[str, Any]) -> str:
        gid=new_id("generation")
        with self._lock:
            self._conn.execute("INSERT INTO generations VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (gid,session_id,provider,model,finish_reason,json.dumps(redact(usage),default=str),utc_now())); self._conn.commit()
        return gid
    def start_tool_call(self, session_id: str, generation_id: str | None, tool: str, args: dict[str, Any], call_id: str | None=None) -> str:
        cid=call_id or new_id("tool_call")
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO tool_calls VALUES (?, ?, ?, ?, ?, NULL, 'RUNNING', ?)",
                               (cid,session_id,generation_id,tool,json.dumps(redact(args),default=str),utc_now())); self._conn.commit()
        return cid
    def finish_tool_call(self, tool_call_id: str, result: dict[str, Any], status: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tool_calls SET result_json=?,status=? WHERE tool_call_id=?",
                               (json.dumps(redact(result),default=str),status,tool_call_id)); self._conn.commit()
    def add_context_snapshot(self, session_id: str, token_count: int, metadata: dict[str, Any]) -> str:
        sid=new_id("context")
        with self._lock:
            self._conn.execute("INSERT INTO context_snapshots VALUES (?, ?, ?, ?, ?)",
                               (sid,session_id,token_count,json.dumps(metadata,default=str),utc_now())); self._conn.commit()
        return sid

    def generations(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM generations WHERE session_id=? ORDER BY created_at,rowid", (session_id,)).fetchall()
        return [{**dict(row), "usage": redact(json.loads(row["usage_json"] or "{}"))} for row in rows]

    def tool_calls(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM tool_calls WHERE session_id=? ORDER BY created_at,rowid", (session_id,)).fetchall()
        values = []
        for row in rows:
            item = dict(row)
            item["args"] = redact(json.loads(item.pop("args_json") or "{}"))
            raw_result = item.pop("result_json")
            item["result"] = redact(json.loads(raw_result or "{}")) if raw_result else None
            values.append(item)
        return values
