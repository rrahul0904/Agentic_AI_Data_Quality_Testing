"""Public SQL intelligence API, preserving existing call signatures."""

import re

import sqlglot

from .lineage import column_lineage, table_lineage, dialect_name
from .rules import analyze


_SINGLE_QUOTED = re.compile(r"'(?:''|[^'])*'", re.S)
_DOUBLE_QUOTED = re.compile(r'"(?:""|[^"])*"', re.S)
_BACKTICK_QUOTED = re.compile(r"`(?:``|[^`])*`", re.S)
_BRACKET_QUOTED = re.compile(r"\[(?:\]\]|[^\]])*\]", re.S)
_DOLLAR_QUOTED = re.compile(r"\$\$(?:.|\n)*?\$\$", re.S)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_NOT_IN = re.compile(r"\bNOT\s+IN\s*\(", re.I)
_MASK_PATTERNS = (
    _DOLLAR_QUOTED,
    _SINGLE_QUOTED,
    _DOUBLE_QUOTED,
    _BACKTICK_QUOTED,
    _BRACKET_QUOTED,
    _BLOCK_COMMENT,
    _LINE_COMMENT,
)


def _mask_nonstructural_sql(sql: str) -> str:
    value = sql
    for pattern in _MASK_PATTERNS:
        value = pattern.sub(lambda match: " " * len(match.group(0)), value)
    return value


def _not_in_finding_from_source(sql: str):
    """Detect NOT IN only after parsing succeeded, masking literals/comments/quoted identifiers.

    SQLGlot has represented negated IN predicates with different AST and canonical rendering
    shapes across versions/dialects. This compatibility fallback therefore examines the original
    *validated* SQL statement text, but only structural tokens are left visible. Masking preserves
    string length so line/column evidence remains tied to the submitted SQL.
    """

    structural = _mask_nonstructural_sql(sql)
    match = _NOT_IN.search(structural)
    if not match:
        return None
    line = sql.count("\n", 0, match.start()) + 1
    previous_newline = sql.rfind("\n", 0, match.start())
    column = match.start() - previous_newline
    return {
        "rule_id": "NULL_NOT_IN",
        "severity": "WARN",
        "message": "NULL in NOT IN input can reject all rows.",
        "line": line,
        "column": column,
        "evidence": sql,
        "recommendation": "Use NOT EXISTS or exclude NULL input.",
        "statement_index": None,
    }


def review_sql(sql, dialect=None, schema=None):
    try:
        trees = [t for t in sqlglot.parse(sql, read=dialect_name(dialect)) if t]
        if not trees:
            raise ValueError("SQL is empty")
        findings = []
        for index, tree in enumerate(trees):
            statement_findings = list(analyze(tree, schema))
            findings.extend(dict(item, statement_index=index) for item in statement_findings)
        if not any(item.get("rule_id") == "NULL_NOT_IN" for item in findings):
            fallback = _not_in_finding_from_source(sql)
            if fallback:
                findings.append(fallback)
        return {
            "parseable": True,
            "dialect": dialect or "ansi",
            "statement_type": trees[0].key.upper(),
            "statement_count": len(trees),
            "tables": table_lineage(sql, dialect).get("tables", []),
            "findings": findings,
            "status": "FAIL" if any(f["severity"] in {"ERROR", "CRITICAL"} for f in findings) else "PASS",
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {
            "parseable": False,
            "status": "FAIL",
            "dialect": dialect or "ansi",
            "tables": [],
            "findings": [
                {
                    "rule_id": "SQL_PARSE",
                    "severity": "ERROR",
                    "message": str(exc),
                    "line": None,
                    "column": None,
                    "evidence": sql,
                    "recommendation": "Correct syntax/dialect.",
                }
            ],
        }


def sql_lineage(sql, dialect=None, **kwargs):
    return {**column_lineage(sql, dialect, **kwargs), "review": review_sql(sql, dialect)}


def column_upstream(sql, column, dialect=None, **kwargs):
    result = column_lineage(sql, dialect, **kwargs)
    return {
        **result,
        "column": column,
        "upstream": [m for m in result["mappings"] if m["target_column"].casefold() == column.casefold()],
    }


def column_downstream(sql, column, dialect=None, **kwargs):
    result = column_lineage(sql, dialect, **kwargs)
    return {
        **result,
        "column": column,
        "downstream": [
            m
            for m in result["mappings"]
            if any(
                column.casefold() in {s["column"].casefold(), f"{s['table']}.{s['column']}".casefold()}
                for s in m["sources"]
            )
        ],
    }