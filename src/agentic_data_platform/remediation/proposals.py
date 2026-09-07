"""Proposal-only deterministic remediation helpers. These functions never write files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentic_data_platform.dbt.manifest_graph import DbtManifestGraph
from agentic_data_platform.platform.airflow import AirflowProject
from agentic_data_platform.sql.intelligence import review_sql


def propose_dbt_tests(graph: DbtManifestGraph, *, limit: int = 25) -> dict[str, Any]:
    proposals = []
    for node_id, node in graph.nodes.items():
        if node.get("resource_type") != "model" or graph.tests_for_node(node_id):
            continue
        columns = node.get("columns") or {}
        id_candidates = [name for name in columns if name.casefold() == "id" or name.casefold().endswith("_id")]
        recommended = []
        for column in id_candidates[:2]:
            recommended.append({"column": column, "tests": ["not_null", "unique"], "confidence": "MEDIUM"})
        proposals.append({
            "model": node.get("name") or node_id,
            "path": node.get("original_file_path"),
            "recommendations": recommended or [{"tests": ["not_null candidate"], "confidence": "LOW"}],
            "status": "PROPOSED",
            "requires_builder_approval": True,
        })
        if len(proposals) >= limit:
            break
    return {"count": len(proposals), "proposals": proposals, "applied": False}


def propose_sql_repair(sql: str, dialect: str | None = None) -> dict[str, Any]:
    review = review_sql(sql, dialect)
    proposals = []
    for finding in review.get("findings", []):
        rule = finding.get("rule_id")
        if rule:
            proposals.append({
                "rule_id": rule,
                "problem": finding.get("message"),
                "proposal": finding.get("recommendation") or "Review and rewrite the flagged AST expression.",
                "automatic_edit": False,
            })
    return {
        "status": "PROPOSED",
        "dialect": dialect or "ansi",
        "finding_count": len(review.get("findings", [])),
        "proposals": proposals,
        "applied": False,
        "requires_builder_approval": True,
    }


def propose_airflow_retry(project: str | Path, dag_id: str) -> dict[str, Any]:
    dag = AirflowProject.scan(project).dags.get(dag_id)
    if dag is None:
        raise KeyError(f"Airflow DAG not found: {dag_id}")
    current = dag.retries or 0
    return {
        "dag_id": dag_id,
        "current_retries": current,
        "proposal": {
            "retries": max(1, current),
            "retry_exponential_backoff": True,
            "max_retry_delay": "bounded; choose from workload SLA",
        },
        "status": "PROPOSED" if current < 1 else "NO_CHANGE_REQUIRED",
        "applied": False,
        "requires_builder_approval": True,
    }


def propose_quality_rule(asset: str, check_type: str, *, severity: str = "ERROR") -> dict[str, Any]:
    templates = {
        "not_null": {"expected": 0, "metric": "null_count"},
        "unique": {"expected": 0, "metric": "duplicate_key_count"},
        "row_count": {"tolerance": 0, "metric": "source_target_row_count"},
        "freshness": {"metric": "age_seconds", "threshold": "REVIEW_REQUIRED"},
        "referential_integrity": {"expected": 0, "metric": "orphan_key_count"},
    }
    if check_type not in templates:
        raise ValueError(f"unsupported quality-rule proposal: {check_type}")
    return {
        "asset": asset,
        "check_type": check_type,
        "severity": severity,
        "configuration": templates[check_type],
        "status": "PROPOSED",
        "applied": False,
        "requires_builder_approval": True,
    }
