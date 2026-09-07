"""SQLGlot-backed deterministic SQL review and first-version column lineage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SqlFinding:
    rule_id: str
    severity: str
    message: str
    location: str | None = None
    evidence: dict[str, Any] | None = None
    recommendation: str | None = None


def _parse(sql: str, dialect: str | None = None):
    import sqlglot

    return sqlglot.parse_one(sql, read=dialect if dialect and dialect != "ansi" else None)


def review_sql(sql: str, dialect: str | None = None) -> dict[str, Any]:
    try:
        from sqlglot import expressions as exp

        tree = _parse(sql, dialect)
    except Exception as exc:  # noqa: BLE001 - a malformed query is an actionable finding
        return {"parseable": False, "dialect": dialect or "ansi", "findings": [asdict(SqlFinding("SQL_PARSE", "ERROR", str(exc)))], "tables": []}
    findings: list[SqlFinding] = []
    if any(isinstance(node, exp.Star) for node in tree.walk()):
        findings.append(SqlFinding("SELECT_STAR", "WARN", "SELECT * couples consumers to schema changes.", recommendation="Project explicit columns."))
    for join in tree.find_all(exp.Join):
        if join.args.get("kind", "").lower() == "cross" or not join.args.get("on") and not join.args.get("using"):
            findings.append(SqlFinding("CARTESIAN_JOIN", "ERROR", "Join has no deterministic join condition.", evidence={"join": join.sql()}))
    for div in tree.find_all(exp.Div):
        right = div.right
        if not isinstance(right, exp.Literal) or right.name not in {"0", "1"}:
            findings.append(SqlFinding("UNSAFE_DIVISION", "WARN", "Division may fail or produce an invalid ratio when the denominator is zero.", evidence={"expression": div.sql()}, recommendation="Use NULLIF(denominator, 0)."))
    for window in tree.find_all(exp.Window):
        if not window.args.get("partition_by"):
            findings.append(SqlFinding("UNBOUNDED_WINDOW", "WARN", "Window expression has no PARTITION BY and may scan the full relation.", evidence={"expression": window.sql()}))
    if any(isinstance(node, exp.Distinct) for node in tree.walk()):
        findings.append(SqlFinding("EXPENSIVE_DISTINCT", "INFO", "DISTINCT can require a full sort or hash operation.", recommendation="Confirm deduplication is required and prefer a keyed strategy."))
    if isinstance(tree, (exp.Delete, exp.Update)) and not tree.args.get("where"):
        findings.append(SqlFinding("UNBOUNDED_DML", "ERROR", "DELETE/UPDATE has no WHERE clause.", recommendation="Add a bounded predicate or require explicit approval."))
    if isinstance(tree, (exp.Drop, exp.TruncateTable)):
        findings.append(SqlFinding("UNSAFE_DDL", "CRITICAL", "Destructive DDL detected.", evidence={"statement": tree.sql()}))
    for func in tree.find_all(exp.Func):
        if func.sql_name().upper() in {"RANDOM", "RAND", "CURRENT_TIMESTAMP", "CURRENT_DATE", "UUID", "UUID_STRING"}:
            findings.append(SqlFinding("NON_DETERMINISTIC", "WARN", f"Non-deterministic function {func.sql_name()} can make results non-repeatable.", evidence={"function": func.sql_name()}))
    return {
        "parseable": True, "dialect": dialect or "ansi", "statement_type": tree.key.upper(),
        "tables": sorted({table.sql() for table in tree.find_all(exp.Table)}),
        "findings": [asdict(item) for item in findings],
        "status": "FAIL" if any(item.severity in {"ERROR", "CRITICAL"} for item in findings) else "PASS",
    }


def column_lineage(sql: str, dialect: str | None = None) -> dict[str, Any]:
    """Map projected columns to referenced source columns for SELECT statements."""

    try:
        from sqlglot import expressions as exp

        tree = _parse(sql, dialect)
    except Exception as exc:  # noqa: BLE001
        return {"parseable": False, "mappings": [], "error": str(exc)}
    if not isinstance(tree, exp.Select):
        select = tree.find(exp.Select)
        if select is None:
            return {"parseable": True, "mappings": [], "warning": "statement has no SELECT projection"}
        tree = select
    tables: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        physical = table.this.sql()
        tables[table.alias_or_name] = physical
        tables.setdefault(table.name, physical)
    mappings: list[dict[str, Any]] = []
    for projection in tree.expressions:
        target = projection.alias_or_name or projection.output_name or projection.sql()
        sources = []
        for column in projection.find_all(exp.Column):
            source_table = tables.get(column.table, column.table or next(iter(tables), ""))
            sources.append({"table": source_table, "column": column.name})
        if isinstance(projection, exp.Star):
            sources = [{"table": value, "column": "*"} for value in tables.values()]
        mappings.append({"target_column": target, "sources": sources, "expression": projection.sql()})
    return {"parseable": True, "tables": sorted(set(tables.values())), "mappings": mappings}


def sql_lineage(sql: str, dialect: str | None = None) -> dict[str, Any]:
    result = column_lineage(sql, dialect)
    result["review"] = review_sql(sql, dialect)
    return result


def column_upstream(sql: str, column: str, dialect: str | None = None) -> dict[str, Any]:
    result = column_lineage(sql, dialect)
    return {**result, "column": column, "upstream": [item for item in result.get("mappings", []) if item["target_column"].casefold() == column.casefold()]}


def column_downstream(sql: str, column: str, dialect: str | None = None) -> dict[str, Any]:
    result = column_lineage(sql, dialect)
    return {**result, "column": column, "downstream": [item for item in result.get("mappings", []) if any(source["column"].casefold() == column.casefold() for source in item["sources"])]}
