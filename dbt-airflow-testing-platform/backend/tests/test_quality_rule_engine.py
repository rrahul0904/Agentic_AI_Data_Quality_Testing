import pytest

from app.models_quality import QualityRule
from app.services.adapters.base import DataPlatformAdapter, QueryResult
from app.services.quality_rule_engine import (
    RuleCompilationError,
    compile_rule,
    execute_rule,
)


def _rule(**kwargs) -> QualityRule:
    defaults = dict(
        name="test rule", dimension="completeness", rule_type="not_null",
        target_table="orders", target_column="id", expression={},
        tolerance_type=None, tolerance_value=None, severity="P2",
    )
    defaults.update(kwargs)
    return QualityRule(**defaults)


class FakeAdapter(DataPlatformAdapter):
    """Returns a pre-canned QueryResult regardless of the SQL passed in --
    lets us test the engine's interpretation logic without a real database."""

    dialect = "duckdb"

    def __init__(self, result: QueryResult | None = None, raise_error: bool = False):
        self._result = result
        self._raise_error = raise_error
        self.last_sql: str | None = None

    def test_connection(self) -> bool:
        return True

    def get_row_count(self, table, predicate=None):
        raise NotImplementedError

    def get_schema(self, table):
        raise NotImplementedError

    def execute_query(self, sql: str) -> QueryResult:
        self.last_sql = sql
        if self._raise_error:
            raise RuntimeError("simulated adapter failure")
        return self._result


# ---------------------------------------------------------------------------
# compile_rule
# ---------------------------------------------------------------------------


def test_compile_not_null():
    sql = compile_rule(_rule(rule_type="not_null"))
    assert "IS NULL" in sql
    assert "orders" in sql


def test_compile_unique():
    sql = compile_rule(_rule(rule_type="unique", target_column="order_id"))
    assert "COUNT(DISTINCT" in sql.upper()


def test_compile_accepted_values():
    rule = _rule(rule_type="accepted_values", target_column="status", expression={"values": ["a", "b"]})
    sql = compile_rule(rule)
    # sqlglot may normalize "status NOT IN (...)" to "NOT status IN (...)" --
    # semantically identical, so assert on the two tokens separately rather
    # than a fixed "NOT IN" substring.
    assert "NOT" in sql.upper() and " IN (" in sql.upper()
    assert "'a'" in sql and "'b'" in sql


def test_compile_accepted_values_missing_values_raises():
    rule = _rule(rule_type="accepted_values", expression={})
    with pytest.raises(RuleCompilationError):
        compile_rule(rule)


def test_compile_row_count_reconciliation():
    rule = _rule(rule_type="row_count_reconciliation", target_column=None, expression={"source_table": "raw_orders"})
    sql = compile_rule(rule)
    assert "raw_orders" in sql and "orders" in sql


def test_compile_transpiles_to_other_dialects():
    sql_duckdb = compile_rule(_rule(rule_type="not_null"), target_dialect="duckdb")
    sql_snowflake = compile_rule(_rule(rule_type="not_null"), target_dialect="snowflake")
    # Both should be valid, semantically equivalent SQL for the same logical rule.
    assert "IS NULL" in sql_duckdb and "IS NULL" in sql_snowflake


def test_compile_unknown_rule_type_raises():
    rule = _rule(rule_type="not_a_real_type")
    with pytest.raises(RuleCompilationError):
        compile_rule(rule)


# ---------------------------------------------------------------------------
# execute_rule
# ---------------------------------------------------------------------------


def test_execute_rule_pass_when_no_failing_rows():
    adapter = FakeAdapter(QueryResult(columns=["failing_count"], rows=[(0,)]))
    outcome = execute_rule(_rule(), adapter)
    assert outcome.status == "PASS"
    assert outcome.measured_value == 0.0
    assert outcome.evidence


def test_execute_rule_fail_when_over_tolerance():
    adapter = FakeAdapter(QueryResult(columns=["failing_count"], rows=[(3,)]))
    outcome = execute_rule(_rule(tolerance_value=0), adapter)
    assert outcome.status == "FAIL"
    assert outcome.measured_value == 3.0
    assert "tolerance" in outcome.message


def test_execute_rule_pass_within_tolerance():
    adapter = FakeAdapter(QueryResult(columns=["failing_count"], rows=[(2,)]))
    outcome = execute_rule(_rule(tolerance_value=5), adapter)
    assert outcome.status == "PASS"


def test_execute_rule_error_on_adapter_failure():
    adapter = FakeAdapter(raise_error=True)
    outcome = execute_rule(_rule(), adapter)
    assert outcome.status == "ERROR"
    assert "simulated adapter failure" in outcome.message


def test_execute_reconciliation_within_tolerance():
    adapter = FakeAdapter(QueryResult(columns=["target_count", "source_count"], rows=[(100, 100)]))
    rule = _rule(
        rule_type="row_count_reconciliation", target_column=None,
        expression={"source_table": "raw_orders"}, tolerance_type="percentage", tolerance_value=0,
    )
    outcome = execute_rule(rule, adapter)
    assert outcome.status == "PASS"
    assert outcome.measured_value == 0.0


def test_execute_reconciliation_outside_tolerance():
    adapter = FakeAdapter(QueryResult(columns=["target_count", "source_count"], rows=[(50, 100)]))
    rule = _rule(
        rule_type="row_count_reconciliation", target_column=None,
        expression={"source_table": "raw_orders"}, tolerance_type="percentage", tolerance_value=0,
    )
    outcome = execute_rule(rule, adapter)
    assert outcome.status == "FAIL"
    assert outcome.measured_value == 50.0
