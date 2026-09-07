#!/usr/bin/env python3
"""Run deterministic lineage benchmark fixtures and emit JSON evidence."""

from __future__ import annotations

import json
from pathlib import Path

from agentic_data_platform.lineage.engine import analyze_column_lineage


CASES = [
    {
        "name": "simple_rename",
        "sql": "SELECT customer_id AS guest_id FROM raw.customers",
        "schema": {"raw.customers": {"customer_id": "INTEGER"}},
        "expected": {("guest_id", "raw.customers", "customer_id")},
    },
    {
        "name": "join",
        "sql": "SELECT o.id AS order_id, c.email FROM orders o JOIN customers c ON o.customer_id = c.id",
        "schema": {
            "orders": {"id": "INTEGER", "customer_id": "INTEGER"},
            "customers": {"id": "INTEGER", "email": "TEXT"},
        },
        "expected": {("order_id", "orders", "id"), ("email", "customers", "email")},
    },
    {
        "name": "nested_cte",
        "sql": "WITH a AS (SELECT id, amount FROM orders), b AS (SELECT id, amount * 2 AS gross FROM a) SELECT id, gross FROM b",
        "schema": {"orders": {"id": "INTEGER", "amount": "NUMBER"}},
        "expected": {("id", "orders", "id"), ("gross", "orders", "amount")},
    },
    {
        "name": "case_coalesce",
        "sql": "SELECT CASE WHEN amount > 0 THEN COALESCE(amount, 0) ELSE 0 END AS normalized FROM orders",
        "schema": {"orders": {"amount": "NUMBER"}},
        "expected": {("normalized", "orders", "amount")},
    },
    {
        "name": "window",
        "sql": "SELECT customer_id, SUM(amount) OVER (PARTITION BY customer_id) AS lifetime FROM orders",
        "schema": {"orders": {"customer_id": "INTEGER", "amount": "NUMBER"}},
        "expected": {
            ("customer_id", "orders", "customer_id"),
            ("lifetime", "orders", "amount"),
            ("lifetime", "orders", "customer_id"),
        },
    },
    {
        "name": "aggregate",
        "sql": "SELECT customer_id, SUM(amount) AS total FROM orders GROUP BY customer_id",
        "schema": {"orders": {"customer_id": "INTEGER", "amount": "NUMBER"}},
        "expected": {("customer_id", "orders", "customer_id"), ("total", "orders", "amount")},
    },
    {
        "name": "union",
        "sql": "SELECT id FROM current_orders UNION ALL SELECT id FROM archived_orders",
        "schema": {
            "current_orders": {"id": "INTEGER"},
            "archived_orders": {"id": "INTEGER"},
        },
        "expected": {("id", "current_orders", "id"), ("id", "archived_orders", "id")},
    },
]


def observed_edges(result):
    return {
        (mapping["target"], source["table"], source["column"])
        for mapping in result.get("mappings", ())
        for source in mapping.get("sources", ())
    }


def main() -> None:
    true_positive = false_positive = false_negative = parse_failures = unresolved = 0
    cases = []
    for case in CASES:
        result = analyze_column_lineage(
            case["sql"],
            dialect="snowflake",
            schema=case["schema"],
        )
        observed = observed_edges(result)
        expected = case["expected"]
        tp = len(observed & expected)
        fp = len(observed - expected)
        fn = len(expected - observed)
        true_positive += tp
        false_positive += fp
        false_negative += fn
        parse_failures += 0 if result.get("parseable") else 1
        unresolved += len(result.get("unresolved_references", ()))
        cases.append(
            {
                "name": case["name"],
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "status": result.get("status"),
            }
        )

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    report = {
        "cases": cases,
        "summary": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "resolved_edges": true_positive,
            "unresolved_references": unresolved,
            "parse_failures": parse_failures,
        },
    }
    output = Path("benchmarks/lineage/results.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
