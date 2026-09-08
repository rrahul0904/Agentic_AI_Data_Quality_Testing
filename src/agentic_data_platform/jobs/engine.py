from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from agentic_data_platform.models import new_id, utc_now


_SCHEMA = """
CREATE TABLE IF NOT EXISTS background_jobs (
  job_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT
);
"""


class BackgroundJobEngine:
    def __init__(self, path: str | Path = ":memory:", max_workers: int = 4) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ade-job")
        self._futures: dict[str, Future[Any]] = {}

    def submit(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        job_id = new_id("job")
        with self._lock:
            self._conn.execute(
                "INSERT INTO background_jobs VALUES (?, ?, 'QUEUED', NULL, NULL, ?, NULL, NULL)",
                (job_id, name, utc_now()),
            )
            self._conn.commit()

        def runner() -> Any:
            with self._lock:
                self._conn.execute(
                    "UPDATE background_jobs SET status='RUNNING', started_at=? WHERE job_id=?",
                    (utc_now(), job_id),
                )
                self._conn.commit()
            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    self._conn.execute(
                        "UPDATE background_jobs SET status='SUCCESS', result_json=?, completed_at=? WHERE job_id=?",
                        (json.dumps(result, default=str), utc_now(), job_id),
                    )
                    self._conn.commit()
                return result
            except Exception as exc:
                with self._lock:
                    self._conn.execute(
                        "UPDATE background_jobs SET status='FAILED', error=?, completed_at=? WHERE job_id=?",
                        (f"{type(exc).__name__}: {exc}", utc_now(), job_id),
                    )
                    self._conn.commit()
                raise

        self._futures[job_id] = self._pool.submit(runner)
        return job_id

    def cancel(self, job_id: str) -> bool:
        future = self._futures.get(job_id)
        if future is None or not future.cancel():
            return False
        with self._lock:
            self._conn.execute(
                "UPDATE background_jobs SET status='CANCELLED', completed_at=? WHERE job_id=?",
                (utc_now(), job_id),
            )
            self._conn.commit()
        return True

    def get(self, job_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM background_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        return {
            **dict(row),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM background_jobs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
        return [
            {**dict(row), "result": json.loads(row["result_json"]) if row["result_json"] else None}
            for row in rows
        ]

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=False)
