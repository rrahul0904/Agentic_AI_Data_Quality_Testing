"""Batch, load, quality, watermark, and error persistence.

Local mode writes an equivalent SQLite audit trail. Live mode writes the
Snowflake AUDIT objects. Neither mode reports work performed by the other.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
_SECRET = re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*[^\s,;]+")


def execution_mode() -> str:
    configured = os.environ.get("HOSPITALITY_EXECUTION_MODE", "local").strip().lower()
    if configured in {"live", "snowflake"}:
        return "snowflake"
    if configured in {"local", "static", "simulation", "simulated"}:
        return "local"
    raise ValueError(f"Unsupported HOSPITALITY_EXECUTION_MODE: {configured!r}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _database_path() -> Path:
    return Path(os.environ.get("LOCAL_AUDIT_DB", "/opt/airflow/data/local_audit.sqlite"))


def _connect() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS batch_control (
          batch_id TEXT PRIMARY KEY, dag_id TEXT NOT NULL, run_id TEXT,
          source_system TEXT NOT NULL, started_at TEXT NOT NULL,
          completed_at TEXT, batch_status TEXT NOT NULL, error_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS load_history (
          load_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, source_object TEXT NOT NULL,
          target_object TEXT NOT NULL, source_row_count INTEGER, target_row_count INTEGER,
          rejected_row_count INTEGER NOT NULL DEFAULT 0, load_status TEXT NOT NULL,
          details TEXT, recorded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS data_quality_results (
          result_id TEXT PRIMARY KEY, batch_id TEXT, check_id TEXT NOT NULL,
          system TEXT NOT NULL, layer TEXT NOT NULL, asset TEXT NOT NULL,
          check_type TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
          observed_value TEXT, expected_value TEXT, details TEXT, checked_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pipeline_errors (
          error_id TEXT PRIMARY KEY, batch_id TEXT, dag_id TEXT, task_id TEXT,
          error_class TEXT, error_message TEXT, error_context TEXT, occurred_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS table_watermarks (
          source_system TEXT NOT NULL, source_object TEXT NOT NULL,
          watermark_value TEXT, last_successful_batch_id TEXT, updated_at TEXT NOT NULL,
          PRIMARY KEY (source_system, source_object)
        );
        """
    )
    return connection


def _snowflake_hook():
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    return SnowflakeHook(snowflake_conn_id="snowflake_hospitality")


def begin_batch(batch: dict[str, Any]) -> None:
    if execution_mode() == "local":
        with _connect() as connection:
            connection.execute(
                """INSERT INTO batch_control
                   (batch_id, dag_id, run_id, source_system, started_at, batch_status)
                   VALUES (?, ?, ?, ?, ?, 'RUNNING')""",
                (batch["batch_id"], batch["dag_id"], batch.get("run_id"), batch["source"], _now()),
            )
        return
    _snowflake_hook().run(
        """
        MERGE INTO HOSPITALITY_DW.AUDIT.BATCH_CONTROL target
        USING (SELECT %s BATCH_ID, %s DAG_ID, %s RUN_ID, %s SOURCE_SYSTEM) source
        ON target.BATCH_ID = source.BATCH_ID
        WHEN NOT MATCHED THEN INSERT
          (BATCH_ID, DAG_ID, RUN_ID, SOURCE_SYSTEM, STARTED_AT, BATCH_STATUS)
          VALUES (source.BATCH_ID, source.DAG_ID, source.RUN_ID, source.SOURCE_SYSTEM, CURRENT_TIMESTAMP(), 'RUNNING')
        """,
        parameters=(batch["batch_id"], batch["dag_id"], batch.get("run_id"), batch["source"]),
    )


def get_local_watermark(source: str, entity: str) -> str | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT watermark_value FROM table_watermarks WHERE source_system = ? AND source_object = ?",
            (source, entity),
        ).fetchone()
    return row[0] if row else None


def set_local_watermark(source: str, entity: str, value: str, batch_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO table_watermarks
               (source_system, source_object, watermark_value, last_successful_batch_id, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source_system, source_object) DO UPDATE SET
                 watermark_value = excluded.watermark_value,
                 last_successful_batch_id = excluded.last_successful_batch_id,
                 updated_at = excluded.updated_at""",
            (source, entity, value, batch_id, _now()),
        )


def persist_quality_results(results: list[dict[str, Any]]) -> None:
    if not results:
        return
    if execution_mode() == "local":
        with _connect() as connection:
            connection.executemany(
                """INSERT INTO data_quality_results
                   (result_id, batch_id, check_id, system, layer, asset, check_type, severity,
                    status, observed_value, expected_value, details, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        result["result_id"], result.get("batch_id"), result["check_id"], result["system"],
                        result["layer"], result["asset"], result["check_type"], result["severity"],
                        result["status"], json.dumps(result.get("observed_value")),
                        json.dumps(result.get("expected_value")), json.dumps(result.get("details", {})),
                        result["timestamp"],
                    )
                    for result in results
                ],
            )
        return
    hook = _snowflake_hook()
    for result in results:
        hook.run(
            """
            INSERT INTO HOSPITALITY_DW.AUDIT.DATA_QUALITY_RESULTS
              (RESULT_ID, BATCH_ID, CHECK_NAME, CHECK_LAYER, TARGET_OBJECT, EXPECTED_VALUE,
               ACTUAL_VALUE, CHECK_STATUS, SEVERITY, DETAILS, CHECKED_AT)
            SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), %s, %s, PARSE_JSON(%s), %s
            """,
            parameters=(
                result["result_id"], result.get("batch_id"), result["check_id"], result["layer"],
                result["asset"], json.dumps(result.get("expected_value")),
                json.dumps(result.get("observed_value")), result["status"], result["severity"],
                json.dumps(result.get("details", {})), result["timestamp"],
            ),
        )


def finalize_batch(batch: dict[str, Any], loads: list[dict[str, Any]]) -> None:
    if execution_mode() == "local":
        with _connect() as connection:
            for index, load in enumerate(loads):
                connection.execute(
                    """INSERT INTO load_history
                       (load_id, batch_id, source_object, target_object, source_row_count,
                        target_row_count, rejected_row_count, load_status, details, recorded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"{batch['batch_id']}:{index}", batch["batch_id"], load["entity"],
                        load["target_object"], load["source_row_count"], load["target_row_count"],
                        load.get("rejected_row_count", 0), "LOADED", json.dumps(load), _now(),
                    ),
                )
            connection.execute(
                "UPDATE batch_control SET batch_status = 'SUCCESS', completed_at = ? WHERE batch_id = ?",
                (_now(), batch["batch_id"]),
            )
        return
    hook = _snowflake_hook()
    for load in loads:
        hook.run(
            """
            INSERT INTO HOSPITALITY_DW.AUDIT.LOAD_HISTORY
              (LOAD_ID, BATCH_ID, DAG_ID, SOURCE_SYSTEM, SOURCE_OBJECT, TARGET_OBJECT,
               LOAD_STRATEGY, LOAD_STATUS, SOURCE_ROW_COUNT, TARGET_ROW_COUNT,
               REJECTED_ROW_COUNT, STARTED_AT, COMPLETED_AT)
            SELECT UUID_STRING(), %s, %s, %s, %s, %s, %s, 'LOADED', %s, %s, %s,
                   CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
            """,
            parameters=(
                batch["batch_id"], batch["dag_id"], batch["source"], load["entity"],
                load["target_object"], batch["load_strategy"], load["source_row_count"],
                load["target_row_count"], load.get("rejected_row_count", 0),
            ),
        )
    hook.run(
        """UPDATE HOSPITALITY_DW.AUDIT.BATCH_CONTROL
           SET BATCH_STATUS = 'SUCCESS', COMPLETED_AT = CURRENT_TIMESTAMP()
           WHERE BATCH_ID = %s""",
        parameters=(batch["batch_id"],),
    )


def audit_batch(ti: Any, **_: Any) -> dict[str, Any]:
    batch = ti.xcom_pull(task_ids="create_batch")
    copy_result = ti.xcom_pull(task_ids="copy_raw")
    finalize_batch(batch, copy_result["loads"])
    return {"batch_id": batch["batch_id"], "status": "SUCCESS", "load_count": len(copy_result["loads"])}


def _redact(value: str) -> str:
    return _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)[:4000]


def record_pipeline_error(context: dict[str, Any]) -> None:
    """Airflow failure callback; persistence errors are logged without masking the task error."""
    try:
        ti = context.get("task_instance") or context.get("ti")
        batch = ti.xcom_pull(task_ids="create_batch") if ti else None
        exception = context.get("exception")
        error = {
            "error_id": f"error-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
            "batch_id": batch.get("batch_id") if isinstance(batch, dict) else None,
            "dag_id": getattr(ti, "dag_id", None) or context.get("dag", {}).get("dag_id")
            if isinstance(context.get("dag"), dict)
            else getattr(context.get("dag"), "dag_id", None),
            "task_id": getattr(ti, "task_id", None),
            "error_class": type(exception).__name__ if exception else "TaskFailure",
            "error_message": _redact(str(exception or "task failed")),
            "error_context": {"run_id": getattr(ti, "run_id", None), "try_number": getattr(ti, "try_number", None)},
        }
        if execution_mode() == "local":
            with _connect() as connection:
                connection.execute(
                    """INSERT INTO pipeline_errors
                       (error_id, batch_id, dag_id, task_id, error_class, error_message, error_context, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        error["error_id"], error["batch_id"], error["dag_id"], error["task_id"],
                        error["error_class"], error["error_message"], json.dumps(error["error_context"]), _now(),
                    ),
                )
                if error["batch_id"]:
                    connection.execute(
                        """UPDATE batch_control SET batch_status = 'FAILED', completed_at = ?,
                           error_count = error_count + 1 WHERE batch_id = ?""",
                        (_now(), error["batch_id"]),
                    )
            return
        _snowflake_hook().run(
            """
            INSERT INTO HOSPITALITY_DW.AUDIT.PIPELINE_ERRORS
              (ERROR_ID, BATCH_ID, DAG_ID, TASK_ID, ERROR_CLASS, ERROR_MESSAGE, ERROR_CONTEXT, OCCURRED_AT)
            SELECT %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), CURRENT_TIMESTAMP()
            """,
            parameters=(
                error["error_id"], error["batch_id"], error["dag_id"], error["task_id"],
                error["error_class"], error["error_message"], json.dumps(error["error_context"]),
            ),
        )
    except Exception:
        LOGGER.exception("Could not persist pipeline failure metadata")
