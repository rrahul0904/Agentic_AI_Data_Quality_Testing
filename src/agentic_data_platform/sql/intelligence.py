"""Public SQL intelligence API, preserving existing call signatures."""

import re

import sqlglot

from .lineage import column_lineage, table_lineage, dialect_name
from .rules import analyze


_SINGLE_QUOTED = re.compile(r"'(?:''|[^'])*'", re.S)
_DOLLAR_QUOTED = re.compile(r"\$\$(?:.|\n)*?\$\$", re.S)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_NOT_IN = re.compile(r"\bNOT\s+IN\s*\(", re.I)


def _parsed_not_in_finding(tree):
    """Detect NOT IN from SQLGlot's canonical parsed statement, independent of AST wrapper shape.

    SQLGlot has represented negated IN predicates with different parent/argument layouts across
    dialect/version combinations. We therefore use the already-successfully-parsed canonical SQL
    as a compatibility fallback, after removing literal/comment text so words inside data cannot
    create a false finding.
    """

    rendered = tree.sql()
    structural = _DOLLAR_QUOTED.sub("$$''$$", rendered)
    structural = _SINGLE_QUOTED.sub("''", structural)
    structural = _BLOCK_COMMENT.sub(" ", structural)
    structural = _LINE_COMMENT.sub(" ", structural)
    if not _NOT_IN.search(structural):
        return None
    return {
        "rule_id": "NULL_NOT_IN",
        "severity": "WARN",
        "message": "NULL in NOT IN input can reject all rows.",
        "line": None,
        "column": None,
        "evidence": rendered,
        "recommendation": "Use NOT EXISTS or exclude NULL input.",
    }


def review_sql(sql, dialect=None, schema=None):
    try:
        trees = [t for t in sqlglot.parse(sql, read=dialect_name(dialect)) if t]
        if not trees:
            raise ValueError("SQL is empty")
        findings = []
        for index, tree in enumerate(trees):
            statement_findings = list(analyze(tree, schema))
            if not any(item.get("rule_id") == "NULL_NOT_IN" for item in statement_findings):
                fallback = _parsed_not_in_finding(tree)
                if fallback:
                    statement_findings.append(fallback)
            findings.extend(dict(item, statement_index=index) for item in statement_findings)
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
