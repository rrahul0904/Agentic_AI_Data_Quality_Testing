from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from agentic_data_platform.connectors.models import QueryResult

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid metadata identifier")
    return value


def query_result(raw: Any) -> QueryResult:
    if isinstance(raw, QueryResult):
        return raw
    if isinstance(raw, dict):
        rows = raw.get("rows", ())
        return QueryResult(tuple(dict(row) for row in rows), tuple(raw.get("columns", ())), raw.get("query_id"), dict(raw.get("metadata", {})))
    rows: Iterable[Any] = raw.fetchall() if hasattr(raw, "fetchall") else raw
    description = getattr(raw, "description", ()) or ()
    columns = tuple(item[0] if isinstance(item, tuple) else item.name for item in description)
    normalized = tuple(dict(zip(columns, row, strict=False)) if not isinstance(row, dict) else row for row in rows)
    return QueryResult(normalized, columns, getattr(raw, "sfqid", None))


def execute(executor: Callable[[str], Any] | Any, sql: str) -> Any:
    if callable(executor):
        return executor(sql)
    if hasattr(executor, "execute"):
        return executor.execute(sql)
    cursor = executor.cursor()
    return cursor.execute(sql)
