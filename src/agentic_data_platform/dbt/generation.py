"""Deterministic dbt schema-test and unit-test generation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import sqlglot
import yaml
from sqlglot import exp

from agentic_data_platform.lineage.engine import analyze_column_lineage


def _all_nodes(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {**manifest.get("nodes", {}), **manifest.get("sources", {})}


def _resolve_model(manifest: Mapping[str, Any], reference: str) -> tuple[str, dict[str, Any]]:
    nodes = _all_nodes(manifest)
    if reference in nodes:
        return reference, nodes[reference]
    matches = [
        (unique_id, node)
        for unique_id, node in nodes.items()
        if str(node.get("name", "")).casefold() == reference.casefold()
        and node.get("resource_type") == "model"
    ]
    if len(matches) != 1:
        raise KeyError(f"dbt model reference is not unique: {reference}")
    return matches[0]


def _columns(node: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(name): dict(metadata or {}) for name, metadata in (node.get("columns") or {}).items()}


def _existing_tests(manifest: Mapping[str, Any], model_id: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "test":
            continue
        if model_id not in (node.get("depends_on") or {}).get("nodes", ()):
            continue
        metadata = node.get("test_metadata") or {}
        name = str(metadata.get("name") or "")
        kwargs = metadata.get("kwargs") or {}
        column = str(kwargs.get("column_name") or node.get("column_name") or "")
        if column and name:
            result.setdefault(column, set()).add(name)
    return result


def generate_schema_tests(
    manifest: Mapping[str, Any],
    model: str,
    *,
    relationships: Mapping[str, Mapping[str, str]] | None = None,
    accepted_values: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    model_id, node = _resolve_model(manifest, model)
    columns = _columns(node)
    existing = _existing_tests(manifest, model_id)
    proposals: dict[str, list[Any]] = {}

    grain_candidates = [
        name for name in columns
        if name.casefold() in {"id", f"{node.get('name', '')}_id".casefold()}
        or name.casefold().endswith("_id")
    ]
    model_name = str(node.get("name") or model)

    for name, metadata in columns.items():
        tests: list[Any] = []
        description = str(metadata.get("description") or "").casefold()
        lower = name.casefold()
        existing_for_column = existing.get(name, set())

        likely_required = (
            lower == "id"
            or lower.endswith("_id")
            or any(token in description for token in ("required", "must not be null", "primary key"))
        )
        likely_unique = (
            lower == "id"
            or lower == f"{model_name}_id".casefold()
            or "primary key" in description
            or "unique" in description
        )
        if likely_required and "not_null" not in existing_for_column:
            tests.append("not_null")
        if likely_unique and name in grain_candidates and "unique" not in existing_for_column:
            tests.append("unique")

        relation = (relationships or {}).get(name)
        if relation and "relationships" not in existing_for_column:
            tests.append({
                "relationships": {
                    "to": relation["to"],
                    "field": relation.get("field", name),
                }
            })
        values = (accepted_values or {}).get(name)
        if values is not None and "accepted_values" not in existing_for_column:
            tests.append({"accepted_values": {"values": list(values)}})

        if tests:
            proposals[name] = tests

    yaml_payload = {
        "version": 2,
        "models": [
            {
                "name": model_name,
                "columns": [
                    {"name": column, "data_tests": tests}
                    for column, tests in sorted(proposals.items())
                ],
            }
        ],
    }
    return {
        "model": model_name,
        "model_unique_id": model_id,
        "proposals": proposals,
        "test_count": sum(len(items) for items in proposals.values()),
        "yaml": yaml.safe_dump(yaml_payload, sort_keys=False),
        "applied": False,
        "requires_builder_approval": True,
    }


def _type_value(data_type: str | None, seed: int) -> Any:
    upper = (data_type or "").upper()
    if any(token in upper for token in ("INT", "NUMBER", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")):
        return seed
    if "BOOL" in upper:
        return bool(seed % 2)
    if "DATE" in upper and "TIME" not in upper:
        return f"2026-01-{min(seed, 28):02d}"
    if "TIMESTAMP" in upper or "DATETIME" in upper:
        return f"2026-01-{min(seed, 28):02d} 12:00:00"
    if "TIME" in upper:
        return "12:00:00"
    if any(token in upper for token in ("BINARY", "BYTES")):
        return f"binary_{seed}"
    return f"value_{seed}"


def _ref_for(unique_id: str, node: Mapping[str, Any]) -> str:
    if node.get("resource_type") == "source":
        return "source('" + str(node.get("source_name")) + "', '" + str(node.get("name")) + "')"
    return "ref('" + str(node.get("name")) + "')"


def _logic_categories(sql: str, dialect: str) -> list[str]:
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except sqlglot.errors.SqlglotError:
        return ["baseline"]
    categories = []
    checks = [
        (exp.Case, "case_when"),
        (exp.Join, "join"),
        (exp.Window, "window"),
        (exp.AggFunc, "aggregate"),
        (exp.Div, "division"),
        (exp.Where, "filter"),
    ]
    for cls, category in checks:
        if next(tree.find_all(cls), None) is not None:
            categories.append(category)
    if any(isinstance(column.parent, exp.Is) for column in tree.find_all(exp.Column)):
        categories.append("null_logic")
    return list(dict.fromkeys(categories)) or ["baseline"]


def generate_unit_tests(
    manifest: Mapping[str, Any],
    model: str,
    *,
    dialect: str = "snowflake",
    max_scenarios: int = 3,
) -> dict[str, Any]:
    model_id, node = _resolve_model(manifest, model)
    sql = str(node.get("compiled_code") or node.get("compiled_sql") or "")
    if not sql:
        raise ValueError(f"compiled SQL unavailable for {model}")

    nodes = _all_nodes(manifest)
    dependency_ids = [
        item for item in (node.get("depends_on") or {}).get("nodes", ())
        if item in nodes and nodes[item].get("resource_type") in {"model", "source", "seed"}
    ]
    if not dependency_ids:
        raise ValueError("unit-test generation requires at least one manifest dependency")

    categories = _logic_categories(sql, dialect)[: max(1, max_scenarios)]
    output_columns = _columns(node)
    lineage_schema = {
        str(dep.get("relation_name") or dep.get("name")): {
            column: str(meta.get("data_type") or "UNKNOWN")
            for column, meta in _columns(dep).items()
        }
        for dep_id in dependency_ids
        if (dep := nodes[dep_id])
    }
    lineage = analyze_column_lineage(sql, dialect=dialect, schema=lineage_schema)
    tests = []

    for scenario_index, category in enumerate(categories, 1):
        given = []
        for dependency_id in dependency_ids:
            dependency = nodes[dependency_id]
            input_columns = _columns(dependency)
            row = {
                name: (
                    None
                    if category == "null_logic" and position == 0
                    else _type_value(metadata.get("data_type"), scenario_index + position)
                )
                for position, (name, metadata) in enumerate(input_columns.items())
            }
            given.append({
                "input": _ref_for(dependency_id, dependency),
                "rows": [row],
            })

        expected_row = {
            name: _type_value(metadata.get("data_type"), scenario_index + position)
            for position, (name, metadata) in enumerate(output_columns.items())
        }
        tests.append({
            "name": f"{node.get('name')}_{category}",
            "model": str(node.get("name")),
            "description": f"Generated deterministic {category} scenario; review expected values before approval.",
            "given": given,
            "expect": {"rows": [expected_row]},
        })

    payload = {"unit_tests": tests}
    anti_patterns = []
    category_counts = Counter(categories)
    if category_counts["division"]:
        anti_patterns.append("division edge case requires zero-denominator review")
    if category_counts["join"]:
        anti_patterns.append("join logic requires matched/unmatched key review")
    if category_counts["case_when"]:
        anti_patterns.append("CASE branches require boundary-value review")

    return {
        "success": True,
        "model_name": str(node.get("name")),
        "model_unique_id": model_id,
        "materialized": (node.get("config") or {}).get("materialized"),
        "dependency_count": len(dependency_ids),
        "tests": tests,
        "test_count": len(tests),
        "logic_categories": categories,
        "anti_patterns": anti_patterns,
        "column_lineage": lineage,
        "warnings": [
            "Expected outputs are type-correct deterministic placeholders; validate by running dbt unit tests before applying."
        ],
        "yaml": yaml.safe_dump(payload, sort_keys=False),
        "applied": False,
        "requires_builder_approval": True,
    }
