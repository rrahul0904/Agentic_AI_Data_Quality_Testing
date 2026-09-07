from __future__ import annotations

from agentic_data_platform.sql.parser import parse_sql


def tables_referenced(sql: str, dialect: str | None = None) -> tuple[str, ...]:
    return parse_sql(sql, dialect).tables


def upstream_tables(sql: str, dialect: str | None = None) -> tuple[str, ...]:
    return parse_sql(sql, dialect).source_tables


def target_tables(sql: str, dialect: str | None = None) -> tuple[str, ...]:
    return parse_sql(sql, dialect).target_tables
