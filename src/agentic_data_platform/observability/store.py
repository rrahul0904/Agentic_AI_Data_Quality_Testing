"""Persistent local tracing for sessions, tools, providers and approvals."""

from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from agentic_data_platform.connections.store import redact
from agentic_data_platform.models import new_id, utc_now


_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
  trace_id TEXT PRIMARY KEY,
  session_id TEXT,
  title TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_events (
  event_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms REAL,
  provider TEXT,
  model TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL,
  error TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(trace_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events(trace_id, sequence);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events(event_type, created_at);
"""


class TraceStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def start(
        self,
        *,
        trace_id: str | None = None,
        session_id: str | None = None,
        title: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        value = trace_id or new_id("trace")
        self.connection.execute(
            "INSERT INTO traces VALUES (?, ?, ?, 'RUNNING', ?, NULL, ?)",
            (
                value,
                session_id,
                title,
                utc_now(),
                json.dumps(redact(dict(metadata or {})), sort_keys=True, default=str),
            ),
        )
        self.connection.commit()
        return value

    def ensure(
        self,
        trace_id: str,
        *,
        session_id: str | None = None,
        title: str | None = None,
    ) -> str:
        row = self.connection.execute(
            "SELECT trace_id FROM traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if row is None:
            return self.start(trace_id=trace_id, session_id=session_id, title=title)
        return trace_id

    def event(
        self,
        trace_id: str,
        event_type: str,
        name: str,
        *,
        status: str = "PASS",
        duration_ms: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        usage: Mapping[str, Any] | None = None,
        cost_usd: float | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure(trace_id)
        sequence = int(
            self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS seq FROM trace_events WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()["seq"]
        )
        usage_value = dict(usage or {})
        event_id = new_id("event")
        self.connection.execute(
            """
            INSERT INTO trace_events VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                event_id,
                trace_id,
                sequence,
                event_type,
                name,
                status,
                duration_ms,
                provider,
                model,
                int(usage_value.get("input_tokens") or 0),
                int(usage_value.get("output_tokens") or 0),
                int(usage_value.get("reasoning_tokens") or 0),
                int(usage_value.get("cache_read_tokens") or 0),
                int(usage_value.get("cache_write_tokens") or 0),
                cost_usd if cost_usd is not None else usage_value.get("cost_usd"),
                error,
                json.dumps(redact(dict(metadata or {})), sort_keys=True, default=str),
                utc_now(),
            ),
        )
        self.connection.commit()
        return self.event_by_id(event_id)

    def complete(self, trace_id: str, status: str = "PASS") -> dict[str, Any]:
        self.connection.execute(
            "UPDATE traces SET status = ?, completed_at = ? WHERE trace_id = ?",
            (status, utc_now(), trace_id),
        )
        self.connection.commit()
        return self.show(trace_id)

    def event_by_id(self, event_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM trace_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"trace event not found: {event_id}")
        return self._event(row)

    def show(self, trace_id: str) -> dict[str, Any]:
        trace = self.connection.execute(
            "SELECT * FROM traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if trace is None:
            raise KeyError(f"trace not found: {trace_id}")
        events = self.connection.execute(
            "SELECT * FROM trace_events WHERE trace_id = ? ORDER BY sequence",
            (trace_id,),
        ).fetchall()
        totals = {
            "input_tokens": sum(int(row["input_tokens"] or 0) for row in events),
            "output_tokens": sum(int(row["output_tokens"] or 0) for row in events),
            "reasoning_tokens": sum(int(row["reasoning_tokens"] or 0) for row in events),
            "cache_read_tokens": sum(int(row["cache_read_tokens"] or 0) for row in events),
            "cache_write_tokens": sum(int(row["cache_write_tokens"] or 0) for row in events),
            "cost_usd": sum(float(row["cost_usd"] or 0) for row in events),
        }
        value = dict(trace)
        value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        value["events"] = [self._event(row) for row in events]
        value["totals"] = totals
        return value

    def list(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM traces"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        result = []
        for row in self.connection.execute(sql, tuple(params)).fetchall():
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            result.append(item)
        return result

    def replay(self, trace_id: str) -> dict[str, Any]:
        trace = self.show(trace_id)
        return {
            "trace_id": trace_id,
            "session_id": trace.get("session_id"),
            "events": [
                {
                    "sequence": item["sequence"],
                    "event_type": item["event_type"],
                    "name": item["name"],
                    "status": item["status"],
                    "metadata": item["metadata"],
                }
                for item in trace["events"]
            ],
            "replay_is_read_only": True,
        }

    def export_json(self, trace_id: str) -> str:
        return json.dumps(self.show(trace_id), indent=2, default=str) + "\n"

    def export_html(self, trace_id: str) -> str:
        trace = self.show(trace_id)
        rows = []
        for event in trace["events"]:
            rows.append(
                "<tr>"
                f"<td>{event['sequence']}</td>"
                f"<td>{html.escape(str(event['event_type']))}</td>"
                f"<td>{html.escape(str(event['name']))}</td>"
                f"<td>{html.escape(str(event['status']))}</td>"
                f"<td>{html.escape(str(event.get('duration_ms') or ''))}</td>"
                f"<td>{html.escape(str(event.get('provider') or ''))}</td>"
                f"<td>{html.escape(str(event.get('model') or ''))}</td>"
                f"<td>{html.escape(str(event.get('error') or ''))}</td>"
                "</tr>"
            )
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Trace "
            + html.escape(trace_id)
            + "</title></head><body><h1>Trace "
            + html.escape(trace_id)
            + "</h1><p>Status: "
            + html.escape(str(trace["status"]))
            + "</p><table border='1'><thead><tr>"
            "<th>#</th><th>Type</th><th>Name</th><th>Status</th><th>Duration ms</th>"
            "<th>Provider</th><th>Model</th><th>Error</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></body></html>"
        )

    def _event(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item
