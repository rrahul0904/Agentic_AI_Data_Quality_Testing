"""Reproducible ADE deterministic competitive benchmark.

This is an ADE-owned parity corpus, NOT Altimate's private benchmark dataset. It mirrors
published scale only: 1,077 anti-pattern classifications and 500 column-lineage cases.
Results must never be presented as an Altimate benchmark score.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable

from agentic_data_platform.sql.intelligence import review_sql
from agentic_data_platform.sql.lineage import column_lineage


@dataclass(frozen=True)
class RuleFixture:
    rule: str
    positive: Callable[[int], str]
    negative: Callable[[int], str]


def _fixtures() -> list[RuleFixture]:
    return [
        RuleFixture("SELECT_STAR", lambda i: f"SELECT * FROM dim_orders_{i}", lambda i: f"SELECT id FROM dim_orders_{i}"),
        RuleFixture("CARTESIAN_JOIN", lambda i: f"SELECT a.id FROM dim_a_{i} a JOIN dim_b_{i} b", lambda i: f"SELECT a.id FROM dim_a_{i} a JOIN dim_b_{i} b ON a.id=b.id"),
        RuleFixture("MISSING_JOIN_PREDICATE", lambda i: f"SELECT a.id FROM dim_a_{i} a JOIN dim_b_{i} b", lambda i: f"SELECT a.id FROM dim_a_{i} a JOIN dim_b_{i} b USING (id)"),
        RuleFixture("UNBOUNDED_CROSS_JOIN", lambda i: f"SELECT a.id FROM dim_a_{i} a CROSS JOIN dim_b_{i} b", lambda i: f"SELECT a.id FROM dim_a_{i} a CROSS JOIN dim_b_{i} b LIMIT 10"),
        RuleFixture("UNFILTERED_FACT_SCAN", lambda i: f"SELECT id FROM fact_orders_{i}", lambda i: f"SELECT id FROM fact_orders_{i} WHERE id > 0"),
        RuleFixture("UNBOUNDED_DML", lambda i: f"DELETE FROM dim_orders_{i}", lambda i: f"DELETE FROM dim_orders_{i} WHERE id={i + 1}"),
        RuleFixture("UNSAFE_DDL", lambda i: f"DROP TABLE dim_orders_{i}", lambda i: f"CREATE TABLE dim_orders_{i}(id INT)"),
        RuleFixture("UNSAFE_MERGE", lambda i: f"MERGE INTO tgt_{i} t USING src_{i} s ON t.id > s.id WHEN MATCHED THEN UPDATE SET t.v=s.v", lambda i: f"MERGE INTO tgt_{i} t USING src_{i} s ON t.id=s.id WHEN MATCHED THEN UPDATE SET t.v=s.v"),
        RuleFixture("UNSAFE_DIVISION", lambda i: f"SELECT revenue / units AS ratio FROM dim_metric_{i}", lambda i: f"SELECT revenue / NULLIF(units, 0) AS ratio FROM dim_metric_{i}"),
        RuleFixture("NON_DETERMINISTIC", lambda i: f"SELECT CURRENT_TIMESTAMP AS ts FROM dim_orders_{i}", lambda i: f"SELECT created_at AS ts FROM dim_orders_{i}"),
        RuleFixture("UNSUPPORTED_DIALECT_FUNCTION", lambda i: f"SELECT MY_ADE_FUNC_{i}(id) FROM dim_orders_{i}", lambda i: f"SELECT COALESCE(id, 0) FROM dim_orders_{i}"),
        RuleFixture("FUNCTION_PORTABILITY", lambda i: f"SELECT MY_ADE_FUNC_{i}(id) FROM dim_orders_{i}", lambda i: f"SELECT COALESCE(id, 0) FROM dim_orders_{i}"),
        RuleFixture("NULL_SEMANTICS", lambda i: f"SELECT id FROM dim_orders_{i} WHERE deleted_at = NULL", lambda i: f"SELECT id FROM dim_orders_{i} WHERE deleted_at IS NULL"),
        RuleFixture("NULL_NOT_IN", lambda i: f"SELECT id FROM dim_a_{i} WHERE id NOT IN (SELECT id FROM dim_b_{i})", lambda i: f"SELECT a.id FROM dim_a_{i} a WHERE NOT EXISTS (SELECT 1 FROM dim_b_{i} b WHERE b.id=a.id)"),
        RuleFixture("IMPLICIT_CAST", lambda i: f"SELECT id FROM dim_orders_{i} WHERE 1 = '1'", lambda i: f"SELECT id FROM dim_orders_{i} WHERE id = {i + 1}"),
        RuleFixture("NESTED_SUBQUERY_COMPLEXITY", lambda i: f"SELECT id FROM (SELECT id FROM (SELECT id FROM (SELECT id FROM dim_orders_{i}) q1) q2) q3", lambda i: f"SELECT id FROM (SELECT id FROM dim_orders_{i}) q1"),
        RuleFixture("CORRELATED_SUBQUERY", lambda i: f"SELECT a.id FROM dim_a_{i} a WHERE EXISTS (SELECT 1 FROM dim_b_{i} b WHERE b.id=a.id)", lambda i: f"SELECT a.id FROM dim_a_{i} a WHERE EXISTS (SELECT 1 FROM dim_b_{i} b WHERE b.id>{i})"),
        RuleFixture("AMBIGUOUS_REFERENCE", lambda i: f"SELECT id FROM dim_a_{i} a JOIN dim_b_{i} b ON a.id=b.id", lambda i: f"SELECT a.id FROM dim_a_{i} a JOIN dim_b_{i} b ON a.id=b.id"),
        RuleFixture("UNUSED_CTE", lambda i: f"WITH unused_{i} AS (SELECT id FROM dim_a_{i}) SELECT id FROM dim_b_{i}", lambda i: f"WITH used_{i} AS (SELECT id FROM dim_a_{i}) SELECT id FROM used_{i}"),
    ]


def anti_pattern_corpus() -> list[tuple[str, bool, str]]:
    """Generate exactly 1,077 labeled target-rule examples across 19 rules."""
    fixtures = _fixtures()
    rows: list[tuple[str, bool, str]] = []
    for fixture in fixtures:
        for index in range(28):
            rows.append((fixture.rule, True, fixture.positive(index)))
            rows.append((fixture.rule, False, fixture.negative(index)))
    for index, fixture in enumerate(fixtures[:13]):
        rows.append((fixture.rule, True, fixture.positive(1000 + index)))
    assert len(rows) == 1077
    return rows


def run_anti_patterns() -> dict[str, object]:
    tp = fp = fn = tn = 0
    failures: list[dict[str, object]] = []
    started = time.perf_counter()
    for index, (target_rule, expected, sql) in enumerate(anti_pattern_corpus()):
        result = review_sql(sql, "snowflake")
        observed_rules = {str(item.get("rule_id")) for item in result.get("findings", [])}
        observed = target_rule in observed_rules
        if expected and observed:
            tp += 1
        elif not expected and observed:
            fp += 1
        elif expected and not observed:
            fn += 1
        else:
            tn += 1
        if observed != expected and len(failures) < 50:
            failures.append(
                {
                    "case": index,
                    "target_rule": target_rule,
                    "expected": expected,
                    "observed": observed,
                    "observed_rules": sorted(observed_rules),
                    "sql": sql,
                }
            )
    elapsed = time.perf_counter() - started
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "name": "ade_internal_sql_antipatterns",
        "dataset_owner": "ADE",
        "comparable_scale_only": True,
        "cases": 1077,
        "rules": len(_fixtures()),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "elapsed_seconds": round(elapsed, 6),
        "average_ms": round(elapsed * 1000 / 1077, 6),
        "failures": failures,
        "passed": f1 == 1.0 and not failures,
    }


def _lineage_case(index: int, category: int) -> tuple[str, set[tuple[str, str, str]]]:
    source = f"src_{index}"
    other = f"other_{index}"
    target = "out"
    col = f"c{index}"
    other_col = f"d{index}"
    category %= 13
    if category == 0:
        sql = f"SELECT {col} AS {target} FROM {source}"
        edges = {(target, source, col)}
    elif category == 1:
        sql = f"SELECT s.{col} AS {target} FROM {source} s"
        edges = {(target, source, col)}
    elif category == 2:
        sql = f"SELECT {col} + 1 AS {target} FROM {source}"
        edges = {(target, source, col)}
    elif category == 3:
        sql = f"SELECT COALESCE({col}, 0) AS {target} FROM {source}"
        edges = {(target, source, col)}
    elif category == 4:
        sql = f"SELECT CASE WHEN {col} > 0 THEN {col} ELSE 0 END AS {target} FROM {source}"
        edges = {(target, source, col)}
    elif category == 5:
        sql = f"SELECT s.{col} + o.{other_col} AS {target} FROM {source} s JOIN {other} o ON s.id=o.id"
        edges = {(target, source, col), (target, other, other_col)}
    elif category == 6:
        sql = f"WITH base AS (SELECT {col} FROM {source}) SELECT {col} AS {target} FROM base"
        edges = {(target, source, col)}
    elif category == 7:
        sql = f"SELECT q.{col} AS {target} FROM (SELECT {col} FROM {source}) q"
        edges = {(target, source, col)}
    elif category == 8:
        sql = f"SELECT SUM({col}) AS {target} FROM {source}"
        edges = {(target, source, col)}
    elif category == 9:
        sql = f"SELECT MAX({col}) OVER (PARTITION BY group_id) AS {target} FROM {source}"
        edges = {(target, source, col), (target, source, "group_id")}
    elif category == 10:
        sql = f"SELECT CAST({col} AS DOUBLE) AS {target} FROM {source}"
        edges = {(target, source, col)}
    elif category == 11:
        sql = f"SELECT {col} * {col} AS {target} FROM {source}"
        edges = {(target, source, col)}
    else:
        sql = f"SELECT ABS({col}) AS {target} FROM {source}"
        edges = {(target, source, col)}
    return sql, edges


def _normalized_edge(target: object, table: object, column: object) -> tuple[str, str, str]:
    return (
        str(target).strip('"`').casefold(),
        str(table).strip('"`').casefold(),
        str(column).strip('"`').casefold(),
    )


def _observed_edges(result: dict[str, object]) -> set[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for mapping in result.get("mappings", []):  # type: ignore[union-attr]
        for source in mapping.get("sources", []):
            edges.add(_normalized_edge(mapping.get("target_column"), source.get("table"), source.get("column")))
    return edges


def run_lineage() -> dict[str, object]:
    expected_total = observed_total = correct = 0
    mismatch_count = 0
    failures: list[dict[str, object]] = []
    started = time.perf_counter()
    for index in range(500):
        sql, expected_raw = _lineage_case(index, index % 13)
        expected = {_normalized_edge(*edge) for edge in expected_raw}
        result = column_lineage(sql, "snowflake")
        observed = _observed_edges(result)
        expected_total += len(expected)
        observed_total += len(observed)
        correct += len(expected & observed)
        if observed != expected:
            mismatch_count += 1
            if len(failures) < 50:
                failures.append(
                    {
                        "case": index,
                        "category": index % 13,
                        "expected": sorted(expected),
                        "observed": sorted(observed),
                        "status": result.get("status"),
                        "error": result.get("error"),
                        "sql": sql,
                    }
                )
    elapsed = time.perf_counter() - started
    precision = correct / observed_total if observed_total else 0.0
    recall = correct / expected_total if expected_total else 0.0
    edge_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "name": "ade_internal_column_lineage",
        "dataset_owner": "ADE",
        "comparable_scale_only": True,
        "cases": 500,
        "categories": 13,
        "expected_edges": expected_total,
        "observed_edges": observed_total,
        "correct_edges": correct,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "edge_f1": round(edge_f1, 6),
        "exact_case_count": 500 - mismatch_count,
        "elapsed_seconds": round(elapsed, 6),
        "average_ms": round(elapsed * 1000 / 500, 6),
        "failures": failures,
        "passed": precision == 1.0 and recall == 1.0 and mismatch_count == 0,
    }


def run() -> dict[str, object]:
    anti = run_anti_patterns()
    lineage = run_lineage()
    return {
        "schema_version": 1,
        "benchmark": "ADE deterministic competitive certification",
        "truthfulness": {
            "altimate_private_dataset_used": False,
            "altimate_score_claimed": False,
            "ade_bench_score_claimed": False,
            "purpose": "same-scale internal regression proof",
        },
        "anti_patterns": anti,
        "column_lineage": lineage,
        "passed": bool(anti["passed"] and lineage["passed"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/competitive/deterministic-benchmark.json")
    args = parser.parse_args()
    report = run()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
