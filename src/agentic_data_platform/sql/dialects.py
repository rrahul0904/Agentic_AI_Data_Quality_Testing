from __future__ import annotations

from agentic_data_platform.sql.engine import identify_dialect

SUPPORTED_DIALECTS = frozenset({"ansi", "sqlserver", "snowflake", "databricks", "bigquery"})


def resolve_dialect(sql: str, requested: str | None = None) -> str:
    dialect = (requested or identify_dialect(sql)).lower()
    return dialect if dialect in SUPPORTED_DIALECTS else "ansi"
