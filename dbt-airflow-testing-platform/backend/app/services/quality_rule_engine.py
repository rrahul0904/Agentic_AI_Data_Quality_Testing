"""Quality Rule Engine (Master Prompt §12, Architecture spec §15-16).

Converts a canonical, platform-independent QualityRule into dialect SQL
(via SQLGlot, so the same rule is portable across warehouses even though
only DuckDB executes for real in this phase) and, when an adapter is
supplied, actually runs it and returns a deterministic PASS/FAIL/ERROR --
never an AI opinion. This is the concrete "AI decides WHAT to test,
deterministic engines prove WHETHER it passed" boundary from the spec.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot

from ..models_quality import QualityRule
from .adapters.base import DataPlatformAdapter, QueryResult

CANONICAL_DIALECT = "duckdb"  # rule templates below are written in this dialect


class RuleCompilationError(ValueError):
    pass


def _quote_literal(value) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _template_sql(rule: QualityRule) -> str:
    """Renders the canonical (DuckDB-dialect) SQL for one rule. This is the
    "logical rule identity" the compiler then transpiles per target
    dialect -- see compile_rule()."""
    expr = rule.expression or {}

    if rule.rule_type == "not_null":
        return (
            f"SELECT count(*) AS failing_count FROM {rule.target_table} "
            f"WHERE {rule.target_column} IS NULL"
        )

    if rule.rule_type == "unique":
        return (
            f"SELECT count(*) - count(DISTINCT {rule.target_column}) AS failing_count "
            f"FROM {rule.target_table}"
        )

    if rule.rule_type == "accepted_values":
        values = expr.get("values")
        if not values:
            raise RuleCompilationError("accepted_values rule requires expression.values")
        in_list = ", ".join(_quote_literal(v) for v in values)
        return (
            f"SELECT count(*) AS failing_count FROM {rule.target_table} "
            f"WHERE {rule.target_column} NOT IN ({in_list})"
        )

    if rule.rule_type == "row_count_reconciliation":
        source_table = expr.get("source_table")
        if not source_table:
            raise RuleCompilationError("row_count_reconciliation requires expression.source_table")
        return (
            f"SELECT (SELECT count(*) FROM {rule.target_table}) AS target_count, "
            f"(SELECT count(*) FROM {source_table}) AS source_count"
        )

    if rule.rule_type == "aggregate_reconciliation":
        source_table = expr.get("source_table")
        column = expr.get("column") or rule.target_column
        agg = expr.get("agg", "sum")
        if not source_table or not column:
            raise RuleCompilationError(
                "aggregate_reconciliation requires expression.source_table and a column"
            )
        return (
            f"SELECT (SELECT {agg}({column}) FROM {rule.target_table}) AS target_value, "
            f"(SELECT {agg}({column}) FROM {source_table}) AS source_value"
        )

    if rule.rule_type == "custom_sql":
        sql = expr.get("sql")
        if not sql:
            raise RuleCompilationError("custom_sql rule requires expression.sql")
        return sql

    raise RuleCompilationError(f"unknown rule_type: {rule.rule_type}")


def compile_rule(rule: QualityRule, target_dialect: str = CANONICAL_DIALECT) -> str:
    """Returns rule SQL transpiled to `target_dialect`. Raises
    RuleCompilationError if the rule is malformed, or sqlglot.errors.*
    if the canonical SQL doesn't parse (both are real, actionable errors --
    not swallowed)."""
    canonical_sql = _template_sql(rule)
    if target_dialect == CANONICAL_DIALECT:
        # Still round-trip through sqlglot so a malformed template SQL fails
        # here, at compile time, not silently at execution time.
        return sqlglot.transpile(canonical_sql, read=CANONICAL_DIALECT, write=CANONICAL_DIALECT)[0]
    return sqlglot.transpile(canonical_sql, read=CANONICAL_DIALECT, write=target_dialect)[0]


@dataclass
class RuleExecutionOutcome:
    status: str  # PASS | FAIL | ERROR
    measured_value: float | None
    compiled_sql: str
    dialect: str
    message: str | None
    evidence: list[dict]  # [{evidence_type, dataset_ref, value, query_text}, ...]


def _tolerance_or_zero(rule: QualityRule) -> float:
    return rule.tolerance_value if rule.tolerance_value is not None else 0.0


def _evaluate_count_style(rule: QualityRule, result: QueryResult) -> tuple[str, float]:
    failing_count = float(result.scalar() or 0)
    tolerance = _tolerance_or_zero(rule)
    status = "PASS" if failing_count <= tolerance else "FAIL"
    return status, failing_count


def _evaluate_reconciliation(rule: QualityRule, result: QueryResult) -> tuple[str, float]:
    row = result.as_dicts()[0]
    a_key, b_key = list(row.keys())[:2]
    a_val = float(row[a_key] or 0)
    b_val = float(row[b_key] or 0)
    diff = abs(a_val - b_val)
    pct_diff = (diff / b_val * 100.0) if b_val else (0.0 if a_val == 0 else 100.0)

    tolerance = _tolerance_or_zero(rule)
    measured = pct_diff if rule.tolerance_type == "percentage" else diff
    status = "PASS" if measured <= tolerance else "FAIL"
    return status, measured


def execute_rule(rule: QualityRule, adapter: DataPlatformAdapter) -> RuleExecutionOutcome:
    try:
        compiled_sql = compile_rule(rule, target_dialect=adapter.dialect)
    except (RuleCompilationError, sqlglot.errors.SqlglotError) as exc:
        return RuleExecutionOutcome(
            status="ERROR", measured_value=None, compiled_sql="", dialect=adapter.dialect,
            message=f"compilation failed: {exc}", evidence=[],
        )

    try:
        result = adapter.execute_query(compiled_sql)
    except Exception as exc:  # noqa: BLE001 - surface any adapter/connection failure as ERROR, not a crash
        return RuleExecutionOutcome(
            status="ERROR", measured_value=None, compiled_sql=compiled_sql, dialect=adapter.dialect,
            message=f"execution failed: {exc}", evidence=[],
        )

    if rule.rule_type in ("row_count_reconciliation", "aggregate_reconciliation"):
        status, measured_value = _evaluate_reconciliation(rule, result)
        evidence_type = "ROW_COUNT" if rule.rule_type == "row_count_reconciliation" else "AGGREGATE"
    else:
        status, measured_value = _evaluate_count_style(rule, result)
        evidence_type = "QUERY_RESULT"

    message = None
    if status == "FAIL":
        message = f"measured {measured_value} against tolerance {_tolerance_or_zero(rule)}"

    evidence = [
        {
            "evidence_type": evidence_type,
            "dataset_ref": rule.target_table,
            "value": str(measured_value),
            "query_text": compiled_sql,
        }
    ]

    return RuleExecutionOutcome(
        status=status,
        measured_value=measured_value,
        compiled_sql=compiled_sql,
        dialect=adapter.dialect,
        message=message,
        evidence=evidence,
    )
