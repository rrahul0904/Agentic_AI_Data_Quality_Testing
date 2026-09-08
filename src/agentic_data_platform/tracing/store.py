from __future__ import annotations
import html, json, sqlite3, threading, time
from pathlib import Path
from typing import Any
from agentic_data_platform.models import new_id, utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_events (
 event_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, session_id TEXT, parent_id TEXT,
 kind TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
 ended_at TEXT, duration_ms REAL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, started_at);
"""

class TraceStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:": Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._started: dict[str, float] = {}
        self._conn.executescript(_SCHEMA); self._conn.commit()
    def start(self, kind: str, name: str, *, trace_id: str | None = None, session_id: str | None = None,
              parent_id: str | None = None, payload: dict[str, Any] | None = None) -> str:
        event_id, trace = new_id("trace_event"), trace_id or new_id("trace")
        with self._lock:
            self._started[event_id] = time.perf_counter()
            self._conn.execute("INSERT INTO trace_events VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, NULL, NULL, ?)",
                               (event_id, trace, session_id, parent_id, kind, name, utc_now(), json.dumps(payload or {}, default=str)))
            self._conn.commit()
        return event_id
    def finish(self, event_id: str, status: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            started = self._started.pop(event_id, None)
            duration = (time.perf_counter() - started) * 1000 if started is not None else None
            row = self._conn.execute("SELECT payload_json FROM trace_events WHERE event_id = ?", (event_id,)).fetchone()
            if row is None: raise KeyError(f"trace event not found: {event_id}")
            merged = json.loads(row["payload_json"] or "{}"); merged.update(payload or {})
            self._conn.execute("UPDATE trace_events SET status=?, ended_at=?, duration_ms=?, payload_json=? WHERE event_id=?",
                               (status, utc_now(), duration, json.dumps(merged, default=str), event_id))
            self._conn.commit()
    def list(self, *, trace_id: str | None = None, session_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        sql, params, conditions = "SELECT * FROM trace_events", [], []
        if trace_id: conditions.append("trace_id = ?"); params.append(trace_id)
        if session_id: conditions.append("session_id = ?"); params.append(session_id)
        if conditions: sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY started_at LIMIT ?"; params.append(max(1, min(limit, 5000)))
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"] or "{}")} for row in rows]
    def export_html(self, trace_id: str) -> str:
        rows = []
        for event in self.list(trace_id=trace_id, limit=5000):
            rows.append("<tr>" + "".join([
                f"<td>{html.escape(str(event['kind']))}</td>",
                f"<td>{html.escape(str(event['name']))}</td>",
                f"<td>{html.escape(str(event['status']))}</td>",
                f"<td>{event['duration_ms'] if event['duration_ms'] is not None else ''}</td>",
                f"<td><pre>{html.escape(json.dumps(event['payload'], indent=2, default=str))}</pre></td>"
            ]) + "</tr>")
        return "<!doctype html><html><body><h1>Trace " + html.escape(trace_id) + "</h1><table>" + "".join(rows) + "</table></body></html>"


    def show(self, event_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM trace_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"trace event not found: {event_id}")
        return {
            **dict(row),
            "payload": json.loads(row["payload_json"] or "{}"),
        }

    def traces(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT trace_id,
                   MIN(started_at) AS started_at,
                   MAX(COALESCE(ended_at, started_at)) AS ended_at,
                   COUNT(*) AS event_count,
                   SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS error_count,
                   SUM(CASE WHEN kind='tool' THEN 1 ELSE 0 END) AS tool_count,
                   SUM(CASE WHEN kind='generation' THEN 1 ELSE 0 END) AS generation_count,
                   MAX(session_id) AS session_id
            FROM trace_events
            GROUP BY trace_id
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def tree(self, trace_id: str) -> dict[str, Any]:
        events = self.list(trace_id=trace_id, limit=5000)
        if not events:
            raise KeyError(f"trace not found: {trace_id}")
        by_id = {str(item["event_id"]): {**item, "children": []} for item in events}
        roots: list[dict[str, Any]] = []
        for item in by_id.values():
            parent_id = item.get("parent_id")
            if parent_id and str(parent_id) in by_id:
                by_id[str(parent_id)]["children"].append(item)
            else:
                roots.append(item)

        def sort_children(node: dict[str, Any]) -> None:
            node["children"].sort(key=lambda child: str(child.get("started_at") or ""))
            for child in node["children"]:
                sort_children(child)

        for root in roots:
            sort_children(root)
        roots.sort(key=lambda item: str(item.get("started_at") or ""))
        return {
            "trace_id": trace_id,
            "event_count": len(events),
            "roots": roots,
        }

    def export_json(self, trace_id: str) -> str:
        payload = {
            "trace_id": trace_id,
            "events": self.list(trace_id=trace_id, limit=5000),
        }
        if not payload["events"]:
            raise KeyError(f"trace not found: {trace_id}")
        return json.dumps(payload, indent=2, default=str)

    def replay(self, trace_id: str) -> dict[str, Any]:
        """Reconstruct the recorded execution timeline without re-running side effects."""

        events = self.list(trace_id=trace_id, limit=5000)
        if not events:
            raise KeyError(f"trace not found: {trace_id}")
        timeline = []
        for event in events:
            payload = event["payload"]
            step = {
                "event_id": event["event_id"],
                "parent_id": event["parent_id"],
                "kind": event["kind"],
                "name": event["name"],
                "status": event["status"],
                "started_at": event["started_at"],
                "ended_at": event["ended_at"],
                "duration_ms": event["duration_ms"],
            }
            if event["kind"] == "generation":
                step["provider_model"] = event["name"]
                step["usage"] = payload.get("usage")
                step["finish_reason"] = payload.get("finish_reason")
            elif event["kind"] == "tool":
                step["args"] = payload.get("args")
                step["risk"] = payload.get("risk")
                step["result"] = payload.get("result")
            elif event["kind"] == "session":
                step["context_sources"] = payload.get("context_sources")
            timeline.append(step)
        return {
            "trace_id": trace_id,
            "mode": "RECORDED_REPLAY",
            "reexecuted": False,
            "timeline": timeline,
            "event_count": len(timeline),
        }
