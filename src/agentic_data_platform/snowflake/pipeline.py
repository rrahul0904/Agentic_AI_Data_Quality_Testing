"""Read-only Snowflake ingestion testing for stages, Snowpipe, Streams, COPY and DQ."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
from typing import Any, Iterable

from agentic_data_platform.connectors._common import identifier
from agentic_data_platform.connectors.snowflake import SnowflakeConnector


def _qualified_identifier(value: str) -> str:
    parts = [part.strip() for part in str(value).split(".") if part.strip()]
    if not parts:
        raise ValueError("Snowflake identifier is required")
    return ".".join(identifier(part) for part in parts)


def _stage_reference(value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if not raw:
        raise ValueError("Snowflake stage name is required")
    return "@" + _qualified_identifier(raw)


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _information_schema(object_name: str) -> str:
    parts = [part.strip() for part in str(object_name).split(".") if part.strip()]
    if len(parts) == 3:
        return f"{identifier(parts[0])}.INFORMATION_SCHEMA"
    return "INFORMATION_SCHEMA"


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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(text)
            except (TypeError, ValueError):
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * max(0.0, min(float(fraction), 1.0))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _basename(value: Any) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _extension(value: Any) -> str:
    name = _basename(value)
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].casefold()


def _type_family(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").upper())
    base = text.split("(", 1)[0]
    aliases = {
        "DECIMAL": "NUMBER",
        "NUMERIC": "NUMBER",
        "INT": "NUMBER",
        "INTEGER": "NUMBER",
        "BIGINT": "NUMBER",
        "SMALLINT": "NUMBER",
        "FLOAT": "FLOAT",
        "DOUBLE": "FLOAT",
        "REAL": "FLOAT",
        "TEXT": "TEXT",
        "VARCHAR": "TEXT",
        "CHAR": "TEXT",
        "CHARACTER": "TEXT",
        "STRING": "TEXT",
        "TIMESTAMP": "TIMESTAMP",
        "TIMESTAMP_NTZ": "TIMESTAMP",
        "TIMESTAMP_LTZ": "TIMESTAMP",
        "TIMESTAMP_TZ": "TIMESTAMP",
        "DATETIME": "TIMESTAMP",
        "BOOL": "BOOLEAN",
    }
    return aliases.get(base, base)


def _status(findings: Iterable[dict[str, Any]]) -> str:
    severities = [str(item.get("severity", "")).upper() for item in findings]
    if "ERROR" in severities:
        return "FAIL"
    if "WARN" in severities:
        return "WARN"
    return "PASS"


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

    on_error_match = re.search(r"(?is)\bON_ERROR\s*=\s*('?[^'\s;]+'?|'.*?')", compact)
    on_error = on_error_match.group(1).strip("'\"") if on_error_match else None
    if on_error is None:
        findings.append({"severity": "WARN", "code": "ON_ERROR_IMPLICIT", "message": "ON_ERROR is not explicit; verify the intended failure policy."})
    elif on_error.upper() == "CONTINUE":
        findings.append({"severity": "WARN", "code": "PARTIAL_LOAD_ALLOWED", "message": "ON_ERROR=CONTINUE permits partially accepted files; reconcile parsed, loaded and rejected rows."})
    elif on_error.upper().startswith("SKIP_FILE"):
        findings.append({"severity": "WARN", "code": "FILE_SKIP_ALLOWED", "message": "ON_ERROR skips files; monitor rejected-file counts and freshness."})

    file_format_match = re.search(r"(?is)\bFILE_FORMAT\s*=\s*(\([^)]*\)|[^\s;]+)", compact)
    if not file_format_match:
        findings.append({"severity": "INFO", "code": "FILE_FORMAT_IMPLICIT", "message": "FILE_FORMAT is not explicit; a stage-level format may be in use."})
    if re.search(r"(?is)\bPURGE\s*=\s*TRUE\b", compact):
        findings.append({"severity": "WARN", "code": "PURGE_ENABLED", "message": "PURGE=TRUE removes successfully loaded staged files and reduces after-the-fact file inspection."})
    if re.search(r"(?is)\bFORCE\s*=\s*TRUE\b", compact):
        findings.append({"severity": "WARN", "code": "FORCE_ENABLED", "message": "FORCE=TRUE can reload previously loaded files and create duplicates."})

    validation_match = re.search(r"(?is)\bVALIDATION_MODE\s*=\s*([^\s;]+)", compact)
    if validation_match:
        findings.append({"severity": "INFO", "code": "VALIDATION_MODE", "message": f"Validation mode requested: {validation_match.group(1)}"})

    return {
        "status": _status(findings),
        "command": "COPY_INTO",
        "target": target,
        "source": source,
        "options": {
            "on_error": on_error,
            "on_error_explicit": on_error is not None,
            "file_format_explicit": file_format_match is not None,
            "file_format": file_format_match.group(1) if file_format_match else None,
            "purge": bool(re.search(r"(?is)\bPURGE\s*=\s*TRUE\b", compact)),
            "force": bool(re.search(r"(?is)\bFORCE\s*=\s*TRUE\b", compact)),
            "validation_mode": validation_match.group(1) if validation_match else None,
        },
        "finding_count": len(findings),
        "findings": findings,
    }


class SnowflakePipelineTester:
    """Runs bounded, read-only ingestion verification against a Snowflake connector."""

    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("SnowflakePipelineTester requires SnowflakeConnector")
        self.connector = connector

    def _rows(self, sql: str) -> list[dict[str, Any]]:
        # Ingestion verification requires Snowflake metadata commands such as
        # SHOW, DESC and LIST in addition to SELECT. This module deliberately
        # has no mutation primitive and never executes COPY/ALTER/CREATE/DML.
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

    def validate_pipe_load(self, pipe_name: str, *, hours: int = 24, limit: int = 100) -> dict[str, Any]:
        hours = max(1, min(int(hours), 24 * 14))
        limit = max(1, min(int(limit), 1000))
        pipe = _qualified_identifier(pipe_name)
        sql = (
            f"SELECT * FROM TABLE({_information_schema(pipe)}.VALIDATE_PIPE_LOAD("
            f"PIPE_NAME => {_literal(pipe)}, START_TIME => DATEADD('hour', -{hours}, CURRENT_TIMESTAMP()))) "
            f"LIMIT {limit}"
        )
        rows = self._rows(sql)
        return {
            "status": "FAIL" if rows else "PASS",
            "pipe": pipe,
            "hours": hours,
            "error_count": len(rows),
            "errors": rows,
        }

    def stage_inventory(self, *, schema: str | None = None) -> dict[str, Any]:
        sql = "SHOW STAGES" + (f" IN SCHEMA {_qualified_identifier(schema)}" if schema else "")
        rows = self._rows(sql)
        stages = [{
            "name": _value(row, "name"),
            "database": _value(row, "database_name"),
            "schema": _value(row, "schema_name"),
            "type": _value(row, "type"),
            "url": _value(row, "url"),
            "owner": _value(row, "owner"),
            "directory_enabled": _truthy(_value(row, "directory_enabled")),
            "comment": _value(row, "comment"),
        } for row in rows]
        return {"status": "PASS", "stage_count": len(stages), "stages": stages}

    def stage_files(
        self,
        stage_name: str,
        *,
        pattern: str | None = None,
        expected_extensions: Iterable[str] = (),
        max_age_minutes: float | None = None,
        min_files: int = 1,
        limit: int = 1000,
    ) -> dict[str, Any]:
        stage = _stage_reference(stage_name)
        sql = f"LIST {stage}"
        if pattern:
            sql += f" PATTERN = {_literal(pattern)}"
        rows = self._rows(sql)[: max(1, min(int(limit), 10000))]
        expected = {
            value.casefold() if str(value).startswith(".") else "." + str(value).casefold()
            for value in expected_extensions
        }
        now = datetime.now(timezone.utc)
        files: list[dict[str, Any]] = []
        zero_byte = 0
        stale = 0
        unexpected = 0
        for row in rows:
            name = _value(row, "name")
            size = int(_value(row, "size", 0) or 0)
            modified = _parse_datetime(_value(row, "last_modified"))
            age_minutes = (now - modified).total_seconds() / 60.0 if modified else None
            extension = _extension(name)
            is_zero = size == 0
            is_stale = max_age_minutes is not None and age_minutes is not None and age_minutes > float(max_age_minutes)
            is_unexpected = bool(expected) and extension not in expected
            zero_byte += int(is_zero)
            stale += int(is_stale)
            unexpected += int(is_unexpected)
            files.append({
                "name": name,
                "size": size,
                "md5": _value(row, "md5"),
                "last_modified": _value(row, "last_modified"),
                "age_minutes": round(age_minutes, 3) if age_minutes is not None else None,
                "extension": extension,
                "zero_byte": is_zero,
                "stale": is_stale,
                "unexpected_extension": is_unexpected,
            })
        findings: list[dict[str, Any]] = []
        if len(files) < int(min_files):
            findings.append({"severity": "ERROR", "code": "STAGE_FILE_COUNT_LOW", "observed": len(files), "expected_min": int(min_files)})
        if zero_byte:
            findings.append({"severity": "ERROR", "code": "ZERO_BYTE_FILES", "count": zero_byte})
        if stale:
            findings.append({"severity": "ERROR", "code": "STALE_STAGE_FILES", "count": stale, "max_age_minutes": max_age_minutes})
        if unexpected:
            findings.append({"severity": "WARN", "code": "UNEXPECTED_FILE_EXTENSIONS", "count": unexpected, "expected_extensions": sorted(expected)})
        return {
            "status": _status(findings),
            "stage": stage,
            "pattern": pattern,
            "file_count": len(files),
            "zero_byte_file_count": zero_byte,
            "stale_file_count": stale,
            "unexpected_extension_count": unexpected,
            "findings": findings,
            "files": files,
        }

    def file_format_status(
        self,
        file_format_name: str,
        *,
        expected: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        qualified = _qualified_identifier(file_format_name)
        rows = self._rows(f"DESC FILE FORMAT {qualified}")
        properties: dict[str, Any] = {}
        for row in rows:
            name = _value(row, "property_name", _value(row, "property"))
            if name is None:
                continue
            properties[str(name).upper()] = _value(row, "property_value", _value(row, "value"))
        findings: list[dict[str, Any]] = []
        if not properties:
            findings.append({"severity": "ERROR", "code": "FILE_FORMAT_NOT_FOUND", "message": "No file-format properties were returned."})
        for raw_key, wanted in (expected or {}).items():
            key = str(raw_key).upper()
            actual = properties.get(key)
            if actual is None:
                findings.append({"severity": "ERROR", "code": "FILE_FORMAT_PROPERTY_MISSING", "property": key, "expected": wanted})
            elif str(actual).strip().casefold() != str(wanted).strip().casefold():
                findings.append({
                    "severity": "ERROR",
                    "code": "FILE_FORMAT_PROPERTY_MISMATCH",
                    "property": key,
                    "expected": wanted,
                    "actual": actual,
                })
        return {
            "status": _status(findings),
            "file_format": qualified,
            "properties": properties,
            "findings": findings,
        }

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

    def stream_backlog(self, stream_name: str, *, max_pending_rows: int | None = None) -> dict[str, Any]:
        stream = _qualified_identifier(stream_name)
        status = self.stream_status(stream_name)
        rows = self._rows(
            "SELECT COUNT(*) AS PENDING_ROWS, "
            "COUNT_IF(METADATA$ACTION = 'INSERT') AS INSERT_ROWS, "
            "COUNT_IF(METADATA$ACTION = 'DELETE') AS DELETE_ROWS, "
            "COUNT_IF(METADATA$ISUPDATE) AS UPDATE_MARKER_ROWS "
            f"FROM {stream}"
        )
        row = rows[0] if rows else {}
        pending = int(_value(row, "pending_rows", 0) or 0)
        threshold_exceeded = max_pending_rows is not None and pending > int(max_pending_rows)
        verdict = "FAIL" if status["stale"] else ("WARN" if threshold_exceeded else "PASS")
        return {
            "status": verdict,
            "stream": stream,
            "has_data": status["has_data"],
            "stale": status["stale"],
            "pending_rows": pending,
            "insert_rows": int(_value(row, "insert_rows", 0) or 0),
            "delete_rows": int(_value(row, "delete_rows", 0) or 0),
            "update_marker_rows": int(_value(row, "update_marker_rows", 0) or 0),
            "max_pending_rows": max_pending_rows,
            "threshold_exceeded": threshold_exceeded,
        }

    def copy_history(
        self,
        table_name: str,
        *,
        pipe_name: str | None = None,
        hours: int = 24,
        limit: int = 100,
    ) -> dict[str, Any]:
        hours = max(1, min(int(hours), 24 * 14))
        limit = max(1, min(int(limit), 1000))
        qualified_table = _qualified_identifier(table_name)
        table_literal = _literal(qualified_table)
        pipe_arg = f", PIPE_NAME => {_literal(_qualified_identifier(pipe_name))}" if pipe_name else ""
        sql = (
            "SELECT FILE_NAME, STAGE_LOCATION, LAST_LOAD_TIME, STATUS, ROW_COUNT, ROW_PARSED, "
            "ERROR_COUNT, FIRST_ERROR_MESSAGE, FIRST_ERROR_LINE_NUMBER, FIRST_ERROR_COLUMN_NAME, "
            "PIPE_CATALOG_NAME, PIPE_SCHEMA_NAME, PIPE_NAME, BYTES_BILLED "
            f"FROM TABLE({_information_schema(qualified_table)}.COPY_HISTORY("
            f"TABLE_NAME => {table_literal}, START_TIME => DATEADD('hour', -{hours}, CURRENT_TIMESTAMP()){pipe_arg})) "
            "ORDER BY LAST_LOAD_TIME DESC "
            f"LIMIT {limit}"
        )
        rows = self._rows(sql)
        failed = [row for row in rows if str(_value(row, "status") or "").upper() not in {"LOADED", "LOAD IN PROGRESS"}]
        errors = sum(int(_value(row, "error_count", 0) or 0) for row in rows)
        loaded_rows = sum(int(_value(row, "row_count", 0) or 0) for row in rows)
        parsed_rows = sum(int(_value(row, "row_parsed", _value(row, "row_count", 0)) or 0) for row in rows)
        return {
            "status": "FAIL" if failed or errors else "PASS",
            "table": qualified_table,
            "pipe": _qualified_identifier(pipe_name) if pipe_name else None,
            "hours": hours,
            "file_count": len(rows),
            "failed_file_count": len(failed),
            "error_count": errors,
            "parsed_row_count": parsed_rows,
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

    def schema_drift(
        self,
        stage_name: str,
        target_table: str,
        file_format_name: str,
        *,
        pattern: str | None = None,
        ignore_target_columns: Iterable[str] = (),
    ) -> dict[str, Any]:
        stage = _stage_reference(stage_name)
        table = _qualified_identifier(target_table)
        file_format = _qualified_identifier(file_format_name)
        pattern_arg = f", PATTERN => {_literal(pattern)}" if pattern else ""
        source_rows = self._rows(
            "SELECT COLUMN_NAME, TYPE, NULLABLE, ORDER_ID "
            "FROM TABLE(INFER_SCHEMA("
            f"LOCATION => {_literal(stage)}, FILE_FORMAT => {_literal(file_format)}{pattern_arg}, IGNORE_CASE => TRUE)) "
            "ORDER BY ORDER_ID"
        )
        target_rows = self._rows(f"DESC TABLE {table}")
        ignored = {str(item).casefold() for item in ignore_target_columns}
        source = {
            str(_value(row, "column_name")).casefold(): {
                "name": _value(row, "column_name"),
                "type": _value(row, "type"),
                "nullable": _truthy(_value(row, "nullable")),
                "order": _value(row, "order_id"),
            }
            for row in source_rows
            if _value(row, "column_name") is not None
        }
        target: dict[str, dict[str, Any]] = {}
        for row in target_rows:
            name = _value(row, "name")
            if name is None:
                continue
            key = str(name).casefold()
            if key in ignored:
                continue
            nullable_raw = _value(row, "null?", _value(row, "nullable", "Y"))
            target[key] = {
                "name": name,
                "type": _value(row, "type"),
                "nullable": str(nullable_raw).strip().upper() not in {"N", "NO", "FALSE", "0"},
                "default": _value(row, "default"),
            }

        findings: list[dict[str, Any]] = []
        for key, source_col in source.items():
            target_col = target.get(key)
            if target_col is None:
                findings.append({"severity": "ERROR", "code": "SOURCE_COLUMN_NOT_IN_TARGET", "column": source_col["name"], "source_type": source_col["type"]})
                continue
            if _type_family(source_col["type"]) != _type_family(target_col["type"]):
                findings.append({
                    "severity": "ERROR",
                    "code": "TYPE_MISMATCH",
                    "column": source_col["name"],
                    "source_type": source_col["type"],
                    "target_type": target_col["type"],
                })
            if source_col["nullable"] and not target_col["nullable"] and target_col["default"] in {None, ""}:
                findings.append({
                    "severity": "ERROR",
                    "code": "NULLABILITY_RISK",
                    "column": source_col["name"],
                    "message": "Source can contain NULL while the target is NOT NULL with no default.",
                })

        for key, target_col in target.items():
            if key in source:
                continue
            severity = "ERROR" if not target_col["nullable"] and target_col["default"] in {None, ""} else "INFO"
            findings.append({
                "severity": severity,
                "code": "TARGET_COLUMN_NOT_IN_SOURCE",
                "column": target_col["name"],
                "target_type": target_col["type"],
            })

        return {
            "status": _status(findings),
            "stage": stage,
            "file_format": file_format,
            "target_table": table,
            "source_column_count": len(source),
            "target_column_count": len(target),
            "findings": findings,
            "source_columns": list(source.values()),
            "target_columns": list(target.values()),
        }

    def ingestion_latency(
        self,
        stage_name: str,
        table_name: str,
        *,
        pipe_name: str | None = None,
        hours: int = 24,
        max_latency_minutes: float = 15.0,
        pattern: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        hours = max(1, min(int(hours), 24 * 14))
        max_latency = max(0.0, float(max_latency_minutes))
        stage = self.stage_files(stage_name, pattern=pattern, min_files=0, limit=limit)
        history = self.copy_history(table_name, pipe_name=pipe_name, hours=hours, limit=limit)
        now = datetime.now(timezone.utc)
        history_by_file = {_basename(_value(row, "file_name")): row for row in history["history"]}
        latencies: list[float] = []
        matched: list[dict[str, Any]] = []
        stuck: list[dict[str, Any]] = []
        for item in stage["files"]:
            modified = _parse_datetime(item.get("last_modified"))
            if modified is None:
                continue
            age = (now - modified).total_seconds() / 60.0
            if age > hours * 60:
                continue
            name = _basename(item.get("name"))
            load = history_by_file.get(name)
            if load is None:
                if age > max_latency:
                    stuck.append({"file_name": item.get("name"), "age_minutes": round(age, 3)})
                continue
            loaded_at = _parse_datetime(_value(load, "last_load_time"))
            if loaded_at is None:
                continue
            latency = max(0.0, (loaded_at - modified).total_seconds() / 60.0)
            latencies.append(latency)
            matched.append({
                "file_name": item.get("name"),
                "last_modified": item.get("last_modified"),
                "last_load_time": _value(load, "last_load_time"),
                "latency_minutes": round(latency, 3),
            })
        p50 = _percentile(latencies, 0.50)
        p95 = _percentile(latencies, 0.95)
        p99 = _percentile(latencies, 0.99)
        sla_breach = p95 is not None and p95 > max_latency
        verdict = "FAIL" if stuck or sla_breach else ("WARN" if not matched else "PASS")
        return {
            "status": verdict,
            "stage": _stage_reference(stage_name),
            "table": _qualified_identifier(table_name),
            "pipe": _qualified_identifier(pipe_name) if pipe_name else None,
            "hours": hours,
            "max_latency_minutes": max_latency,
            "matched_file_count": len(matched),
            "stuck_file_count": len(stuck),
            "p50_minutes": round(p50, 3) if p50 is not None else None,
            "p95_minutes": round(p95, 3) if p95 is not None else None,
            "p99_minutes": round(p99, 3) if p99 is not None else None,
            "sla_breach": sla_breach,
            "stuck_files": stuck,
            "files": matched,
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
        key_columns = tuple(key_columns)
        not_null_columns = tuple(not_null_columns)
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

    def reconcile_load(
        self,
        table_name: str,
        *,
        pipe_name: str | None = None,
        hours: int = 24,
        expected_loaded_rows: int | None = None,
        max_rejected_rows: int = 0,
        limit: int = 1000,
    ) -> dict[str, Any]:
        history = self.copy_history(table_name, pipe_name=pipe_name, hours=hours, limit=limit)
        table = _qualified_identifier(table_name)
        rows = self._rows(f"SELECT COUNT(*) AS TARGET_ROW_COUNT FROM {table}")
        target_rows = int(_value(rows[0], "target_row_count", 0) or 0) if rows else 0
        parsed = int(history["parsed_row_count"])
        loaded = int(history["loaded_row_count"])
        rejected = max(0, parsed - loaded, int(history["error_count"]))
        findings: list[dict[str, Any]] = []
        if history["failed_file_count"]:
            findings.append({"severity": "ERROR", "code": "FAILED_COPY_FILES", "count": history["failed_file_count"]})
        if rejected > int(max_rejected_rows):
            findings.append({
                "severity": "ERROR",
                "code": "REJECTED_ROWS_EXCEEDED",
                "rejected_rows": rejected,
                "max_rejected_rows": int(max_rejected_rows),
            })
        if expected_loaded_rows is not None and loaded != int(expected_loaded_rows):
            findings.append({
                "severity": "ERROR",
                "code": "LOADED_ROW_COUNT_MISMATCH",
                "observed": loaded,
                "expected": int(expected_loaded_rows),
            })
        acceptance = (loaded / parsed * 100.0) if parsed else (100.0 if loaded == 0 else 0.0)
        return {
            "status": _status(findings),
            "table": table,
            "pipe": _qualified_identifier(pipe_name) if pipe_name else None,
            "hours": history["hours"],
            "history_file_count": history["file_count"],
            "parsed_rows": parsed,
            "loaded_rows": loaded,
            "rejected_rows": rejected,
            "acceptance_pct": round(acceptance, 4),
            "target_total_rows": target_rows,
            "expected_loaded_rows": expected_loaded_rows,
            "findings": findings,
        }

    def pipeline_health(
        self,
        *,
        stage_name: str | None = None,
        stage_pattern: str | None = None,
        expected_extensions: Iterable[str] = (),
        max_stage_file_age_minutes: float | None = None,
        file_format_name: str | None = None,
        file_format_expected: dict[str, Any] | None = None,
        pipe_name: str | None = None,
        stream_name: str | None = None,
        max_stream_backlog_rows: int | None = None,
        target_table: str | None = None,
        schema_ignore_target_columns: Iterable[str] = (),
        key_columns: Iterable[str] = (),
        not_null_columns: Iterable[str] = (),
        freshness_column: str | None = None,
        max_age_minutes: float | None = None,
        max_latency_minutes: float = 15.0,
        expected_loaded_rows: int | None = None,
        max_rejected_rows: int = 0,
        history_hours: int = 24,
    ) -> dict[str, Any]:
        components: dict[str, Any] = {}
        if stage_name:
            components["stage_files"] = self.stage_files(
                stage_name,
                pattern=stage_pattern,
                expected_extensions=expected_extensions,
                max_age_minutes=max_stage_file_age_minutes,
            )
        if file_format_name:
            components["file_format"] = self.file_format_status(file_format_name, expected=file_format_expected)
        if pipe_name:
            components["pipe"] = self.pipe_status(pipe_name)
        if stream_name:
            components["stream"] = self.stream_status(stream_name)
            components["stream_backlog"] = self.stream_backlog(stream_name, max_pending_rows=max_stream_backlog_rows)
        if target_table:
            components["copy_history"] = self.copy_history(target_table, pipe_name=pipe_name, hours=history_hours)
            if pipe_name:
                components["pipe_validation"] = self.validate_pipe_load(pipe_name, hours=history_hours)
            if stage_name:
                components["latency"] = self.ingestion_latency(
                    stage_name,
                    target_table,
                    pipe_name=pipe_name,
                    hours=history_hours,
                    max_latency_minutes=max_latency_minutes,
                    pattern=stage_pattern,
                )
            if stage_name and file_format_name:
                components["schema_drift"] = self.schema_drift(
                    stage_name,
                    target_table,
                    file_format_name,
                    pattern=stage_pattern,
                    ignore_target_columns=schema_ignore_target_columns,
                )
            components["quality"] = self.table_quality(
                target_table,
                key_columns=key_columns,
                not_null_columns=not_null_columns,
                freshness_column=freshness_column,
                max_age_minutes=max_age_minutes,
            )
            components["reconciliation"] = self.reconcile_load(
                target_table,
                pipe_name=pipe_name,
                hours=history_hours,
                expected_loaded_rows=expected_loaded_rows,
                max_rejected_rows=max_rejected_rows,
            )
        statuses = [str(value.get("status", "PASS")) for value in components.values()]
        overall = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
        failed = [name for name, value in components.items() if value.get("status") == "FAIL"]
        warned = [name for name, value in components.items() if value.get("status") == "WARN"]
        return {
            "status": overall,
            "component_count": len(components),
            "failed_components": failed,
            "warned_components": warned,
            "components": components,
        }

    def pipeline_rca(self, **kwargs: Any) -> dict[str, Any]:
        """Produce deterministic first-divergence evidence suitable for an agent."""
        health = self.pipeline_health(**kwargs)
        order = [
            ("stage_files", "STAGE"),
            ("file_format", "FILE_FORMAT"),
            ("pipe", "SNOWPIPE_CONTROL"),
            ("pipe_validation", "SNOWPIPE_LOAD"),
            ("copy_history", "COPY_HISTORY"),
            ("latency", "INGESTION_LATENCY"),
            ("stream", "STREAM"),
            ("stream_backlog", "STREAM_BACKLOG"),
            ("schema_drift", "SCHEMA_DRIFT"),
            ("quality", "TARGET_DQ"),
            ("reconciliation", "RECONCILIATION"),
        ]
        first_component: str | None = None
        first_divergence: str | None = None
        for component, label in order:
            if health["components"].get(component, {}).get("status") == "FAIL":
                first_component = component
                first_divergence = label
                break
        if first_divergence is None:
            for component, label in order:
                if health["components"].get(component, {}).get("status") == "WARN":
                    first_component = component
                    first_divergence = label
                    break

        evidence: list[dict[str, Any]] = []
        recommendations: list[str] = []
        if first_component:
            detail = health["components"][first_component]
            evidence.append({"component": first_component, "status": detail.get("status"), "detail": detail})
            recommendations_by_component = {
                "stage_files": "Inspect missing, stale, zero-byte or unexpected staged files before retrying ingestion.",
                "file_format": "Align the Snowflake file format with the producer contract before loading more files.",
                "pipe": "Inspect Snowpipe execution state and notification integration before downstream remediation.",
                "pipe_validation": "Correct the rejected Snowpipe rows/files and re-stage only the failed inputs through an approved recovery path.",
                "copy_history": "Inspect failed COPY history records and first-error metadata to isolate the rejected file or column.",
                "latency": "Investigate stage-to-load delay, notification delivery and Snowpipe queueing against the configured SLA.",
                "stream": "Resolve stream staleness before consuming downstream deltas.",
                "stream_backlog": "Investigate the stream consumer or task schedule causing the pending-change backlog.",
                "schema_drift": "Reconcile producer and target schemas before accepting new files.",
                "quality": "Correct the failing target-table data-quality checks before downstream publication.",
                "reconciliation": "Reconcile parsed, loaded and rejected row counts and recover only the missing/rejected inputs.",
            }
            recommendations.append(recommendations_by_component[first_component])
        else:
            evidence.append({"component": "pipeline", "status": health["status"], "detail": "No deterministic divergence detected."})

        return {
            "status": health["status"],
            "first_divergence": first_divergence,
            "first_component": first_component,
            "evidence": evidence,
            "recommended_actions": recommendations,
            "health": health,
            "mode": "DETERMINISTIC_SNOWFLAKE_PIPELINE_RCA",
        }
