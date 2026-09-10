"""Verified-query evaluation for provider-neutral semantic resources."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from agentic_data_platform.semantic.registry import SemanticRegistry
from agentic_data_platform.sql.safety import classify_mutation


def canonical_sql(sql: str, *, dialect: str = "snowflake") -> str:
    tree = sqlglot.parse_one(str(sql), read=dialect)
    return tree.sql(dialect=dialect, pretty=False, normalize=True)


def sql_tables(sql: str, *, dialect: str = "snowflake") -> set[str]:
    tree = sqlglot.parse_one(str(sql), read=dialect)
    return {
        ".".join(part for part in (table.catalog, table.db, table.name) if part).casefold()
        for table in tree.find_all(exp.Table)
    }


def evaluate_candidate(
    registry: SemanticRegistry,
    *,
    question: str,
    candidate_sql: str,
    dialect: str = "snowflake",
) -> dict[str, Any]:
    verified = registry.find_verified(question, limit=5)
    if not verified:
        return {
            "status": "NO_GROUND_TRUTH",
            "question": question,
            "candidate_sql": candidate_sql,
            "matches": [],
        }
    if classify_mutation(candidate_sql, dialect) != "read":
        return {
            "status": "FAIL",
            "reason": "candidate SQL is mutating; verified-query evaluation requires read-only SQL",
            "matches": [],
        }

    try:
        candidate_canonical = canonical_sql(candidate_sql, dialect=dialect)
        candidate_tables = sql_tables(candidate_sql, dialect=dialect)
    except Exception as exc:
        return {
            "status": "FAIL",
            "reason": f"candidate SQL parse failed: {type(exc).__name__}: {exc}",
            "matches": [],
        }

    matches = []
    for item in verified:
        try:
            expected_canonical = canonical_sql(item["sql"], dialect=dialect)
            expected_tables = sql_tables(item["sql"], dialect=dialect)
        except Exception as exc:
            matches.append({
                "verified_query": item["name"],
                "status": "INVALID_GROUND_TRUTH",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        exact = candidate_canonical == expected_canonical
        union = candidate_tables | expected_tables
        overlap = len(candidate_tables & expected_tables) / len(union) if union else 1.0
        matches.append({
            "verified_query": item["name"],
            "resource_id": item["resource_id"],
            "question": item["question"],
            "exact_sql": exact,
            "table_overlap": round(overlap, 4),
            "expected_tables": sorted(expected_tables),
            "candidate_tables": sorted(candidate_tables),
            "status": "PASS" if exact else ("PARTIAL" if overlap > 0 else "FAIL"),
        })

    best = sorted(
        matches,
        key=lambda item: (
            item.get("status") == "PASS",
            item.get("table_overlap", 0),
        ),
        reverse=True,
    )[0]
    return {
        "status": best["status"],
        "question": question,
        "candidate_sql": candidate_sql,
        "best_match": best,
        "matches": matches,
    }


def evaluate_batch(
    registry: SemanticRegistry,
    cases: list[dict[str, str]],
    *,
    dialect: str = "snowflake",
) -> dict[str, Any]:
    results = [
        evaluate_candidate(
            registry,
            question=case["question"],
            candidate_sql=case["sql"],
            dialect=dialect,
        )
        for case in cases
    ]
    passed = sum(item["status"] == "PASS" for item in results)
    partial = sum(item["status"] == "PARTIAL" for item in results)
    failed = sum(item["status"] == "FAIL" for item in results)
    return {
        "status": "FAIL" if failed else ("PARTIAL" if partial else "PASS"),
        "case_count": len(results),
        "passed": passed,
        "partial": partial,
        "failed": failed,
        "pass_rate": passed / len(results) if results else 1.0,
        "results": results,
    }
