from __future__ import annotations

import re

from agentic_data_platform.sql.parser import parse_sql

HARD_DENIED = frozenset({"DROP_DATABASE", "DROP_SCHEMA", "TRUNCATE"})


def classify_mutation(sql: str, dialect: str | None = None) -> str:
    ast = parse_sql(sql, dialect)
    if ast.ddl_operations or ast.dml_operations:
        return "mutating"
    return "read"


def dangerous_operations(sql: str, dialect: str | None = None) -> tuple[str, ...]:
    ast = parse_sql(sql, dialect)
    operations = (*ast.ddl_operations, *ast.dml_operations)
    return tuple(item for item in operations if item in HARD_DENIED)


def is_hard_denied(sql: str, dialect: str | None = None) -> bool:
    return bool(dangerous_operations(sql, dialect))


def validate_single_statement(sql: str) -> bool:
    body = re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.S)
    return len([piece for piece in body.split(";") if piece.strip()]) <= 1
