"""Production-oriented SQL column lineage with explicit ambiguity and unresolved evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage as sqlglot_lineage
from sqlglot.optimizer.scope import Scope, traverse_scope

from agentic_data_platform.sql.lineage import dialect_name


@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str


@dataclass(frozen=True)
class ColumnMapping:
    target: str
    sources: tuple[ColumnRef, ...]
    expression: str
    resolved: bool
    confidence: str
    unresolved_references: tuple[str, ...] = ()


def _schema_columns(schema: Mapping[str, Any] | None, table: str) -> tuple[str, ...]:
    if not schema:
        return ()
    wanted = table.casefold()
    wanted_simple = table.split(".")[-1].casefold()
    for name, definition in schema.items():
        name_text = str(name)
        if name_text.casefold() != wanted and name_text.split(".")[-1].casefold() != wanted_simple:
            continue
        if isinstance(definition, Mapping):
            return tuple(str(column) for column in definition)
        if isinstance(definition, Sequence) and not isinstance(definition, (str, bytes)):
            values = []
            for item in definition:
                if isinstance(item, Mapping):
                    values.append(str(item.get("name") or item.get("column") or ""))
                else:
                    values.append(str(item))
            return tuple(value for value in values if value)
    return ()


def _table_name(table: exp.Table) -> str:
    return ".".join(part.name if isinstance(part, exp.Identifier) else part.sql() for part in table.parts)


def _scope_sources(scope: Scope) -> dict[str, str]:
    result: dict[str, str] = {}
    for alias, source in scope.sources.items():
        if isinstance(source, exp.Table):
            result[str(alias)] = _table_name(source)
    return result


def _ambiguous_unqualified_columns(tree: exp.Expression, schema: Mapping[str, Any] | None) -> list[str]:
    ambiguous: list[str] = []
    for scope in traverse_scope(tree) or ():
        tables = _scope_sources(scope)
        if len(tables) <= 1:
            continue
        for column in scope.columns:
            if column.table or column.name == "*":
                continue
            candidates = []
            for table in tables.values():
                columns = _schema_columns(schema, table)
                if not columns or column.name.casefold() in {item.casefold() for item in columns}:
                    candidates.append(table)
            if len(candidates) != 1:
                ambiguous.append(f"{column.name}: candidates={','.join(sorted(candidates or tables.values()))}")
    return sorted(set(ambiguous))


def analyze_column_lineage(
    sql: str,
    *,
    dialect: str | None = None,
    schema: Mapping[str, Any] | None = None,
    sources: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve top-level output-column value lineage for one SQL statement."""

    try:
        trees = [tree for tree in sqlglot.parse(sql, read=dialect_name(dialect)) if tree is not None]
        if len(trees) != 1:
            raise ValueError("column lineage requires exactly one SQL statement")
        tree = trees[0]
        if isinstance(tree, (exp.Create, exp.Insert)):
            tree = tree.expression
        if not isinstance(tree, exp.Query):
            raise ValueError("statement does not contain a query projection")

        ambiguity = _ambiguous_unqualified_columns(tree, schema)
        output_names = [projection.alias_or_name for projection in tree.selects]
        duplicate_names = sorted(
            name for name in set(output_names) if name and output_names.count(name) > 1
        )
        nodes: dict[str, Any] = {}
        for output_name in output_names:
            if not output_name or output_name in nodes:
                continue
            nodes[output_name] = sqlglot_lineage(
                output_name,
                tree,
                schema=dict(schema or {}),
                sources=dict(sources or {}),
                dialect=dialect_name(dialect),
            )
        mappings: list[ColumnMapping] = []

        for output_name, node in nodes.items():
            leaves: set[ColumnRef] = set()
            unresolved: list[str] = []
            for item in node.walk():
                expression = item.expression
                if isinstance(expression, exp.Table):
                    table = _table_name(expression)
                    column = item.name.rsplit(".", 1)[-1].strip(chr(34) + chr(96))
                    if column == "*":
                        unresolved.append(f"{output_name}: wildcard requires schema metadata")
                    else:
                        leaves.add(ColumnRef(table, column))

                if not item.downstream:
                    terminal = str(item.name or "").strip(chr(34) + chr(96))
                    parts = [
                        part.strip(chr(34) + chr(96))
                        for part in terminal.split(".")
                        if part
                    ]
                    if len(parts) >= 2 and parts[-1] != "*":
                        table = ".".join(parts[:-1])
                        column = parts[-1]
                        known_tables = {str(name).casefold() for name in (schema or {})}
                        known_simple = {
                            name.split(".")[-1].casefold() for name in known_tables
                        }
                        if (
                            not known_tables
                            or table.casefold() in known_tables
                            or table.split(".")[-1].casefold() in known_simple
                        ):
                            leaves.add(ColumnRef(table, column))
                    elif len(parts) == 1 and parts[0] != "*" and schema:
                        column = parts[0]
                        candidates = [
                            str(table_name)
                            for table_name in schema
                            if column.casefold()
                            in {
                                candidate.casefold()
                                for candidate in _schema_columns(schema, str(table_name))
                            }
                        ]
                        if len(candidates) == 1:
                            leaves.add(ColumnRef(candidates[0], column))
                        elif len(candidates) > 1:
                            unresolved.append(
                                f"{output_name}: terminal column {column} is ambiguous across "
                                + ",".join(sorted(candidates))
                            )

            for message in ambiguity:
                column_name = message.split(":", 1)[0]
                if any(
                    isinstance(column, exp.Column)
                    and not column.table
                    and column.name.casefold() == column_name.casefold()
                    for column in node.expression.find_all(exp.Column)
                ):
                    unresolved.append(message)

            if output_name == "*" and not leaves:
                unresolved.append("*: wildcard expansion unresolved")

            resolved = not unresolved and bool(leaves or not list(node.expression.find_all(exp.Column)))
            confidence = "high" if resolved else "low" if unresolved else "medium"
            mappings.append(
                ColumnMapping(
                    target=output_name,
                    sources=tuple(sorted(leaves, key=lambda item: (item.table, item.column))),
                    expression=node.expression.sql(dialect=dialect_name(dialect)),
                    resolved=resolved,
                    confidence=confidence,
                    unresolved_references=tuple(sorted(set(unresolved))),
                )
            )

        unresolved = sorted(
            {message for mapping in mappings for message in mapping.unresolved_references}
            | set(ambiguity)
            | {f"duplicate output name: {name}" for name in duplicate_names}
        )
        return {
            "parseable": True,
            "status": "PASS" if not unresolved and all(mapping.resolved for mapping in mappings) else "PARTIAL",
            "mappings": [
                {
                    **asdict(mapping),
                    "sources": [asdict(source) for source in mapping.sources],
                }
                for mapping in mappings
            ],
            "unresolved_references": unresolved,
            "ambiguous_references": ambiguity,
            "output_columns": [mapping.target for mapping in mappings],
            "semantics": "value lineage; filter and join predicates are dependencies, not value sources",
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {
            "parseable": False,
            "status": "ERROR",
            "mappings": [],
            "unresolved_references": [str(exc)],
            "ambiguous_references": [],
            "output_columns": [],
            "error": str(exc),
        }


def column_upstream(result: Mapping[str, Any], target_column: str) -> dict[str, Any]:
    matches = [
        mapping
        for mapping in result.get("mappings", ())
        if str(mapping.get("target", "")).casefold() == target_column.casefold()
    ]
    return {"column": target_column, "upstream": matches, "status": result.get("status", "ERROR")}


def column_downstream(
    result: Mapping[str, Any],
    source_column: str,
    source_table: str | None = None,
) -> dict[str, Any]:
    source_cf = source_column.casefold()
    table_cf = source_table.casefold() if source_table else None
    matches = []
    for mapping in result.get("mappings", ()):
        for source in mapping.get("sources", ()):
            if str(source.get("column", "")).casefold() != source_cf:
                continue
            if table_cf and str(source.get("table", "")).casefold() != table_cf:
                continue
            matches.append(mapping)
            break
    return {
        "source_column": source_column,
        "source_table": source_table,
        "downstream": matches,
        "status": result.get("status", "ERROR"),
    }
