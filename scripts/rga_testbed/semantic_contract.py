#!/usr/bin/env python3
"""Load and validate the canonical governed semantic contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "rga_semantic_contract.yml"


def load_semantic_contract(path: Path = DEFAULT_CONTRACT, database: str | None = None) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        contract = yaml.safe_load(handle)
    validate_semantic_contract(contract)
    if database:
        contract = dict(contract)
        contract["database"] = database
    return contract


def validate_semantic_contract(contract: dict[str, Any]) -> None:
    required = {
        "name",
        "database",
        "semantic_schema",
        "mart_schema",
        "mart_table",
        "table_alias",
        "grain",
        "dimensions",
        "time_dimensions",
        "facts",
        "metrics",
        "verified_queries",
        "consumers",
        "performance",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError("Semantic contract missing fields: " + ", ".join(missing))

    metric_names = [item["name"] for item in contract["metrics"]]
    if len(metric_names) != len(set(metric_names)):
        raise ValueError("Semantic contract has duplicate metric names")
    dimension_names = [item["name"] for item in contract["dimensions"]]
    time_names = [item["name"] for item in contract["time_dimensions"]]
    if len(dimension_names + time_names) != len(set(dimension_names + time_names)):
        raise ValueError("Semantic contract has duplicate dimension names")

    known_metrics = set(metric_names)
    known_dimensions = set(dimension_names) | set(time_names)
    query_ids: set[str] = set()
    for query in contract["verified_queries"]:
        query_id = query["id"]
        if query_id in query_ids:
            raise ValueError(f"Duplicate verified query id: {query_id}")
        query_ids.add(query_id)
        unknown_metrics = sorted(set(query.get("metrics", [])) - known_metrics)
        unknown_dimensions = sorted(set(query.get("dimensions", [])) - known_dimensions)
        if unknown_metrics:
            raise ValueError(f"Verified query {query_id} references unknown metrics: {unknown_metrics}")
        if unknown_dimensions:
            raise ValueError(f"Verified query {query_id} references unknown dimensions: {unknown_dimensions}")

    if contract["consumers"]["ai"].get("allow_unrestricted_sql") is not False:
        raise ValueError("AI consumer must remain governed; unrestricted SQL is disabled")
    for client in ("power_bi", "excel"):
        if contract["consumers"][client].get("duplicate_metric_logic_allowed") is not False:
            raise ValueError(f"{client} must not duplicate governed metric logic")


def semantic_view_fqn(contract: dict[str, Any]) -> str:
    return f"{contract['database']}.{contract['semantic_schema']}.{contract['name']}"


def mart_fqn(contract: dict[str, Any]) -> str:
    return f"{contract['database']}.{contract['mart_schema']}.{contract['mart_table']}"


def metric_names(contract: dict[str, Any]) -> list[str]:
    return [item["name"] for item in contract["metrics"]]
