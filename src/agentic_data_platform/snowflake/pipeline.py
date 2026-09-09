"""Read-only Snowflake pipeline testing for Snowpipe, Streams, COPY and DQ."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Iterable

from agentic_data_platform.connectors._common import identifier
from agentic_data_platform.connectors.snowflake import SnowflakeConnector


def _qualified_identifier(value: str) -> str:
    parts = [part.strip() for part in str(value).split(".") if part.strip()]
    if not parts:
        raise ValueError("Snowflake identifier is required")
    return ".".join(identifier(part) for part in parts)


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _value(row: dict[str, Any], key: str, default: Any = None) -> Any:
    target = key.casefold()
    for name, value in row.items():
        if str(name).casefold() == target:
            return value
    return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y"}


def analyze_copy_command(sql: str) -> dict[str, Any]:
    """Statically assess a Snowflake COPY INTO statement without executing it."""
    text = str(sql or "").strip().rstrip(";")
    compact = re.sub(r"\s+", " ", text)
    if not re.match(r"(?is)^COPY\s+INTO\s+", compact):
        return {
            "status": "FAIL",
            "command": "COPY_INTO",
            "findings": [{"severity": "ERROR", "code": "NOT_COPY_INTO", "message": "SQL is not a COPY INTO command."}],
        }

    target_match = re.search(r"(?is)^COPY\s+INTO\s+([^\s(]+)", compact)
    source_match = re.search(r"(?is)\sFROM\s+(@[^\s;]+|'[^']+'|[^\s;]+)", compact)
    target = target_match.group(1) if target_match else None
    source = source_match.group(1) if source_match else None
    findings: list[dict[str, str]] = []

    if target is None:
        findings.append({"severity": "ERROR", "code": "TARGET_MISSING", "message": "COPY target could not be identified."})
    if source is None:
        findings.append({"severity": "ERROR", "code": "SOURCE_MISSING", "message": "COPY source could not be identified."})
    elif not source.startswith("@") and not source.startswith("'"):
        findings.append({"severity": "WARN", "code": "SOURCE_REVIEW", "message": "COPY source is not an obvious stage or location literal."})

    if not re.search(r"(?is)\bON_ERROR\s*=", compact):
        findings.append({"severity": "WARN", "code": "ON_ERROR_IMPLICIT", "message": "ON_ERROR is not explicit; verify the intended failure policy."})
    if not re.search(r"(?is)\bFILE_FORMAT\s*=", compact):
        findings.append({"severity": "INFO", "code": "FILE_FORMAT_IMPLICIT", "message": "FILE_FORMAT is not explicit; a stage-level format may be in use."})
    if re.search(r"(?is)\bPURGE\s*=\s*TRUE\b", compact):
        findings.append({"severity": "WARN", "code": "PURGE_ENABLED", "message": "PURGE=TRUE removes successfully loaded staged files."})
    if re.search(r"(?is)\bFORCE\s*=\s*TRUE\b", compact):
        findings.append({"severity": "WARN", "code": "FORCE_ENABLED", "message": "FORCE=TRUE can reload previously loaded files and create duplicates."})

    validation_match = re.search(r"(?is)\bVALIDATION_MODE\s*=\s*([^\s;]+)", compact)
    if validation_match:
        findings.append({"severity": "INFO", "code": "VALIDATION_MODE", "message": f"Validation mode requested: {validation_match.group(1)}"})

    errors = sum(1 for item in findings if item["severity"] == "ERROR")
    warnings = sum(1 for item in findings if item["severity"] == "WARN")
    return {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "command": "COPY_INTO",
        "target": target,
        "source": source,
        "options": {
            "on_error_explicit": bool(re.search(r"(?is)\bON_ERROR\s*=", compact)),
            "file_format_explicit": bool(re.search(r"(?is)\bFILE_FORMAT\s*=", compact)),
            "purge": bool(re.search(r"(?is)\bPURGE\s*=\s*TRUE\b", compact)),
            "force": bool(re.search(r"(?is)\bFORCE\s*=\s*TRUE\b", compact)),
            "validation_mode": validation_match.group(1) if validation_match else None,
        },
        "finding_count": len(findings),
        "findings": findings,
    }


class SnowflakePipelineTester:
    """Runs bounded, read-only verification against a Snowflake connector."""

    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("SnowflakePipelineTester requires SnowflakeConnector")
        self.connector = connector

    def _rows(self, sql: str) -> list[dict[str, Any]]:
        # Pipeline verification requires Snowflake metadata commands (SHOW) in
        # addition to SELECT. The connector's private read primitive is used
        # intentionally here; this module never exposes mutation SQL.
        return list(self.connector._read(sql).rows)

    def pipe_inventory(self, *, schema: str | None = None) -> dict[str, Any]:
        sql = "SHOW PIPES" + (f" IN SCHEMA {_qualified_identifier(schema)}" if schema else "")
        rows = self._rows(sql)
        pipes = [{
            "name": _value(row, "name"),
            "database": _value(row, "database_name"),
            "schema": _value(row, "schema_name"),
            "owner": _value(row, "owner"),
            "definition": _value(row, "definition"),
            "notification_channel": _value(row, "notification_channel"),
            "comment": _value(row, "comment"),
        } for row in rows]
        return {"status": "PASS", "pipe_count": len(pipes), "pipes": pipes}

    def pipe_status(self, pipe_name: str) -> dict[str, Any]:
        qualified = _qualified_identifier(pipe_name)
        rows = self._rows(f"SELECT SYSTEM$PIPE_STATUS({_literal(qualified)}) AS PIPE_STATUS")
        raw = _value(rows[0], "pipe_status") if rows else None
        try:
            detail = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (json.JSONDecodeError, TypeError, ValueError):
            detail = {"raw": raw}
        state = str(detail.get("executionState") or detail.get("execution_state") or "").upper()
        error = detail.get("error") or detail.get("lastError") or detail.get("last_error")
        status = "FAIL" if error else ("PASS" if state in {"RUNNING", ""} else "WARN")
        return {"status": status, "pipe": qualified, "execution_state": state or None, "detail": detail}

    def stream_inventory(self, *, schema: str | None = None) -> dict[str, Any]:
        sql = "SHOW STREAMS" + (f" IN SCHEMA {_qualified_identifier(schema)}" if schema else "")
        rows = self._rows(sql)
        streams = []
        stale_count = 0
        for row in rows:
            stale = _truthy(_value(row, "stale"))
            stale_count += int(stale)
            streams.append({
                "name": _value(row, "name"),
                "database": _value(row, "database_name"),
                "schema": _value(row, "schema_name"),
                "table": _value(row, "table_name"),
                "source_type": _value(row, "source_type"),
                "mode": _value(row, "mode"),
                "stale": stale,
                "stale_after": _value(row, "stale_after"),
            })
        return {
            "status": "FAIL" if stale_count else "PASS",
            "stream_count": len(streams),
            "stale_count": stale_count,
            "streams": streams,
        }

    def stream_status(self, stream_name: str) -> dict[str, Any]:
        qualified = _qualified_identifier(stream_name)
        has_data_rows = self._rows(f"SELECT SYSTEM$STREAM_HAS_DATA({_literal(qualified)}) AS HAS_DATA")
        has_data = _truthy(_value(has_data_rows[0], "has_data")) if has_data_rows else False
        leaf = qualified.split(".")[-1]
        show_rows = self._rows(f"SHOW STREAMS LIKE {_literal(leaf)}")
        row = show_rows[0] if show_rows else {}
        stale = _truthy(_value(row, "stale"))
        return {
            "status": "FAIL" if stale else "PASS",
            "stream": qualified,
            "has_data": has_data,
            "stale": stale,
            "stale_after": _value(row, "stale_after"),
            "source_table": _value(row, "table_name"),
            "mode": _value(row, "mode"),
        }

    def copy_history(self, table_name: str, *, hours: int = 24, limit: int = 100) -> dict[str, Any]:
        hours = max(1, min(int(hours), 24 * 14))
        limit = max(1, min(int(limit), 1000))
        table_literal = _literal(_qualified_identifier(table_name))
        sql = (
            "SELECT FILE_NAME, STAGE_LOCATION, LAST_LOAD_TIME, STATUS, ROW_COUNT, ROW_PARSED, "
            "ERROR_COUNT, FIRST_ERROR_MESSAGE, FIRST_ERROR_LINE_NUMBER, FIRST_ERROR_COLUMN_NAME "
            "FROM TABLE(INFORMATION_SCHEMA.COPY_HISTORY("
            f"TABLE_NAME => {table_literal}, START_TIME => DATEADD('hour', -{hours}, CURRENT_TIMESTAMP()))) "
            "ORDER BY LAST_LOAD_TIME DESC "
            f"LIMIT {limit}"
        )
        rows = self._rows(sql)
        failed = [row for row in rows if str(_value(row, "status") or "").upper() not in {"LOADED", "LOAD IN PROGRESS"}]
        errors = sum(int(_value(row, "error_count", 0) or 0) for row in rows)
        loaded_rows = sum(int(_value(row, "row_count", 0) or 0) for row in rows)
        return {
            "status": "FAIL" if failed or errors else "PASS",
            "table": _qualified_identifier(table_name),
            "hours": hours,
            "file_count": len(rows),
            "failed_file_count": len(failed),
            "error_count": errors,
            "loaded_row_count": loaded_rows,
            "history": rows,
        }

    def validate_copy(self, table_name: str, *, job_id: str = "_last", limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        table = _qualified_identifier(table_name)
        sql = f"SELECT * FROM TABLE(VALIDATE({table}, JOB_ID => {_literal(job_id)})) LIMIT {limit}"
        rows = self._rows(sql)
        return {
            "status": "FAIL" if rows else "PASS",
            "table": table,
            "job_id": job_id,
            "error_count": len(rows),
            "errors": rows,
        }

    def table_quality(
        self,
        table_name: str,
        *,
        key_columns: Iterable[str] = (),
        not_null_columns: Iterable[str] = (),
        freshness_column: str | None = None,
        max_age_minutes: float | None = None,
        min_rows: int = 1,
    ) -> dict[str, Any]:
        table = _qualified_identifier(table_name)
        keys = [identifier(column) for column in key_columns]
        not_null = [identifier(column) for column in not_null_columns]
        select_parts = ["COUNT(*) AS ROW_COUNT"]
        for index, column in enumerate(not_null):
            select_parts.append(f"SUM(IFF({column} IS NULL, 1, 0)) AS NULL_COUNT_{index}")
        if freshness_column:
            select_parts.append(f"DATEDIFF('minute', MAX({identifier(freshness_column)}), CURRENT_TIMESTAMP()) AS FRESHNESS_LAG_MINUTES")
        rows = self._rows(f"SELECT {', '.join(select_parts)} FROM {table}")
        row = rows[0] if rows else {}
        row_count = int(_value(row, "row_count", 0) or 0)
        checks: list[dict[str, Any]] = [{
            "check": "minimum_rows",
            "status": "PASS" if row_count >= int(min_rows) else "FAIL",
            "observed": row_count,
            "expected_min": int(min_rows),
        }]
        for index, original in enumerate(not_null_columns):
            count = int(_value(row, f"null_count_{index}", 0) or 0)
            checks.append({"check": "not_null", "column": original, "status": "PASS" if count == 0 else "FAIL", "null_count": count})

        duplicate_rows = 0
        if keys:
            key_sql = ", ".join(keys)
            duplicate_result = self._rows(
                "SELECT COALESCE(SUM(CNT - 1), 0) AS DUPLICATE_ROWS FROM "
                f"(SELECT {key_sql}, COUNT(*) AS CNT FROM {table} GROUP BY {key_sql} HAVING COUNT(*) > 1)"
            )
            duplicate_rows = int(_value(duplicate_result[0], "duplicate_rows", 0) or 0) if duplicate_result else 0
            checks.append({"check": "unique_key", "columns": list(key_columns), "status": "PASS" if duplicate_rows == 0 else "FAIL", "duplicate_rows": duplicate_rows})

        freshness_lag = _value(row, "freshness_lag_minutes") if freshness_column else None
        if freshness_column and max_age_minutes is not None:
            numeric_lag = float(freshness_lag) if freshness_lag is not None else float("inf")
            checks.append({
                "check": "freshness",
                "column": freshness_column,
                "status": "PASS" if numeric_lag <= float(max_age_minutes) else "FAIL",
                "lag_minutes": freshness_lag,
                "max_age_minutes": float(max_age_minutes),
            })

        failures = [check for check in checks if check["status"] == "FAIL"]
        return {
            "status": "FAIL" if failures else "PASS",
            "table": table,
            "row_count": row_count,
            "duplicate_rows": duplicate_rows,
            "freshness_lag_minutes": freshness_lag,
            "checks": checks,
            "failed_check_count": len(failures),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def pipeline_health(
        self,
        *,
        pipe_name: str | None = None,
        stream_name: str | None = None,
        target_table: str | None = None,
        key_columns: Iterable[str] = (),
        not_null_columns: Iterable[str] = (),
        freshness_column: str | None = None,
        max_age_minutes: float | None = None,
        history_hours: int = 24,
    ) -> dict[str, Any]:
        components: dict[str, Any] = {}
        if pipe_name:
            components["pipe"] = self.pipe_status(pipe_name)
        if stream_name:
            components["stream"] = self.stream_status(stream_name)
        if target_table:
            components["copy_history"] = self.copy_history(target_table, hours=history_hours)
            components["quality"] = self.table_quality(
                target_table,
                key_columns=key_columns,
                not_null_columns=not_null_columns,
                freshness_column=freshness_column,
                max_age_minutes=max_age_minutes,
            )
        statuses = [str(value.get("status", "PASS")) for value in components.values()]
        overall = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
        return {"status": overall, "component_count": len(components), "components": components}
