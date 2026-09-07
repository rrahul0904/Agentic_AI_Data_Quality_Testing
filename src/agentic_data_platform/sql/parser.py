from __future__ import annotations

import re
from typing import Protocol

from agentic_data_platform.sql.ast import SqlAst
from agentic_data_platform.sql.engine import extract_dependencies, normalize_sql


class SqlParser(Protocol):
    def parse(self, sql: str, dialect: str) -> SqlAst: ...


_DML = {"INSERT", "MERGE", "UPDATE", "DELETE"}
_DDL = {"CREATE", "ALTER", "DROP", "TRUNCATE"}


def _normalise_identifier(identifier: str) -> str:
    return identifier.strip().replace("[", "").replace("]", "").replace("`", "").replace('"', "")


class FallbackSqlParser:
    """Deliberately modest parser that remains available without optional sqlglot."""

    def parse(self, sql: str, dialect: str) -> SqlAst:
        normalized = normalize_sql(sql)
        first = re.match(r"^(\w+)", normalized, re.I)
        statement = first.group(1).upper() if first else "UNKNOWN"
        errors: list[str] = []
        if not normalized:
            errors.append("SQL is empty")
        if statement == "UNKNOWN":
            errors.append("unsupported or unrecognized SQL statement")
        ctes = tuple(match.group(1) for match in re.finditer(r"(?:WITH|,)\s*([\w$]+)\s+AS\s*\(", normalized, re.I))
        source = tuple(item for item in extract_dependencies(sql) if item.lower() not in {cte.lower() for cte in ctes})
        targets = tuple(
            _normalise_identifier(match.group(1))
            for match in re.finditer(r"\b(?:INTO|UPDATE|TABLE)\s+([\[\]`\"\w.$-]+)", normalized, re.I)
        )
        joins = tuple(_normalise_identifier(match.group(1)) for match in re.finditer(r"\bJOIN\s+([\[\]`\"\w.$-]+)", normalized, re.I))
        functions = tuple(sorted(set(match.group(1).upper() for match in re.finditer(r"\b([A-Za-z_][\w$]*)\s*\(", normalized) if match.group(1).upper() not in {"AS", "IN", "VALUES"})))
        columns: tuple[str, ...] = ()
        select = re.search(r"\bSELECT\s+(.*?)\s+\bFROM\b", normalized, re.I)
        if select:
            columns = tuple(part.strip() for part in select.group(1).split(",") if part.strip())
        ddl: list[str] = []
        dml: list[str] = []
        if statement in _DDL:
            suffix = ""
            if statement == "DROP":
                kind = re.search(r"\bDROP\s+(DATABASE|SCHEMA|TABLE|VIEW)\b", normalized, re.I)
                suffix = f"_{kind.group(1).upper()}" if kind else ""
            ddl.append(f"{statement}{suffix}")
        if statement in _DML:
            dml.append(statement)
        tables = tuple(dict.fromkeys((*source, *targets)))
        return SqlAst(dialect, statement, tables, columns, source, tuple(dict.fromkeys(targets)), joins, ctes, functions, tuple(ddl), tuple(dml), tuple(errors))


class SqlglotParser:
    def __init__(self) -> None:
        import sqlglot  # type: ignore[import-not-found]

        self.sqlglot = sqlglot

    def parse(self, sql: str, dialect: str) -> SqlAst:
        # sqlglot owns syntax validation; portable extraction stays intentionally small.
        self.sqlglot.parse_one(sql, read=dialect if dialect != "ansi" else None)
        fallback = FallbackSqlParser().parse(sql, dialect)
        return SqlAst(**{**fallback.__dict__, "backend": "sqlglot"})


def default_parser() -> SqlParser:
    try:
        return SqlglotParser()
    except ImportError:
        return FallbackSqlParser()


def parse_sql(sql: str, dialect: str | None = None, parser: SqlParser | None = None) -> SqlAst:
    from agentic_data_platform.sql.dialects import resolve_dialect

    selected = resolve_dialect(sql, dialect)
    try:
        return (parser or default_parser()).parse(sql, selected)
    except Exception as exc:
        fallback = FallbackSqlParser().parse(sql, selected)
        return SqlAst(**{**fallback.__dict__, "errors": (*fallback.errors, str(exc))})
