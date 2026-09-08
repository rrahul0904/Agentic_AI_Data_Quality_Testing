"""Deterministic dbt schema-test and unit-test generation."""

from __future__ import annotations

from collections import Counter
import importlib.metadata
import re
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


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(item) for item in re.findall(r"\d+", value)[:3]]
    return tuple((parts + [0, 0, 0])[:3])


def _dbt_version(manifest: Mapping[str, Any]) -> str:
    value = str((manifest.get("metadata") or {}).get("dbt_version") or "")
    if value:
        return value
    try:
        return importlib.metadata.version("dbt-core")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _incremental_analysis(node: Mapping[str, Any], sql: str) -> dict[str, Any]:
    config = dict(node.get("config") or {})
    materialized = str(config.get("materialized") or "")
    raw = str(node.get("raw_code") or node.get("raw_sql") or sql)
    unique_key = config.get("unique_key")
    keys = [unique_key] if isinstance(unique_key, str) else list(unique_key or ())
    strategy = str(config.get("incremental_strategy") or "default")
    predicates = list(config.get("incremental_predicates") or ())
    is_incremental = materialized == "incremental" or bool(
        re.search(r"\bis_incremental\s*\(\s*\)", raw)
    )
    return {
        "is_incremental": is_incremental,
        "materialized": materialized,
        "uses_is_incremental_macro": bool(re.search(r"\bis_incremental\s*\(\s*\)", raw)),
        "unique_key": keys,
        "incremental_strategy": strategy,
        "merge": strategy in {"default", "merge"},
        "delete_insert": strategy in {"delete+insert", "delete_insert"},
        "insert_overwrite": strategy == "insert_overwrite",
        "microbatch": strategy == "microbatch",
        "incremental_predicates": predicates,
        "on_schema_change": config.get("on_schema_change"),
    }


_INCREMENTAL_SCENARIOS = (
    "new_records",
    "updated_records",
    "late_arriving_records",
    "duplicate_unique_keys",
    "null_unique_keys",
    "incremental_cutoff_boundary",
    "outside_incremental_predicate",
    "schema_change",
    "existing_unchanged_records",
)


def _set_key(row: dict[str, Any], key: str | None, value: Any) -> dict[str, Any]:
    result = dict(row)
    if key and key in result:
        result[key] = value
    return result


def _incremental_test(
    node: Mapping[str, Any],
    dependency_ids: Sequence[str],
    nodes: Mapping[str, Mapping[str, Any]],
    output_columns: Mapping[str, Mapping[str, Any]],
    scenario: str,
    index: int,
    unique_key: str | None,
) -> dict[str, Any]:
    existing = {
        name: _type_value(metadata.get("data_type"), 1 + position)
        for position, (name, metadata) in enumerate(output_columns.items())
    }
    existing = _set_key(existing, unique_key, 1)
    incoming_id = 2 if scenario == "new_records" else 1
    given = [{"input": "this", "rows": [existing]}]

    for dependency_id in dependency_ids:
        dependency = nodes[dependency_id]
        row = {
            name: _type_value(metadata.get("data_type"), index + position + 2)
            for position, (name, metadata) in enumerate(_columns(dependency).items())
        }
        row = _set_key(row, unique_key, incoming_id)
        if scenario == "null_unique_keys":
            row = _set_key(row, unique_key, None)
        given.append({"input": _ref_for(dependency_id, dependency), "rows": [row]})

    expected = {
        name: _type_value(metadata.get("data_type"), index + position + 2)
        for position, (name, metadata) in enumerate(output_columns.items())
    }
    expected = _set_key(expected, unique_key, incoming_id)
    if scenario == "null_unique_keys":
        expected = _set_key(expected, unique_key, None)

    notes = {
        "new_records": "Exercise a key absent from the existing target.",
        "existing_unchanged_records": "Exercise an existing key whose business values are unchanged.",
        "updated_records": "Exercise an existing unique key with changed incoming values.",
        "late_arriving_records": "Exercise a record arriving behind the normal ingestion watermark.",
        "duplicate_unique_keys": "Exercise repeated incoming unique keys; materialization-level deduplication still requires integration verification.",
        "null_unique_keys": "Exercise NULL unique-key behavior explicitly.",
        "incremental_cutoff_boundary": "Exercise a record exactly on the incremental cutoff boundary.",
        "outside_incremental_predicate": "Exercise a record outside configured incremental predicates.",
        "schema_change": "Exercise schema-change assumptions; adapter on_schema_change behavior requires dbt build verification.",
    }
    if scenario == "duplicate_unique_keys" and len(given) > 1:
        given[1]["rows"].append(dict(given[1]["rows"][0]))
    return {
        "name": f"{node.get('name')}_incremental_{scenario}",
        "model": str(node.get("name")),
        "description": notes[scenario],
        "overrides": {"macros": {"is_incremental": True}},
        "given": given,
        "expect": {"rows": [expected]},
    }


def generate_unit_tests(
    manifest: Mapping[str, Any],
    model: str,
    *,
    dialect: str = "snowflake",
    max_scenarios: int = 12,
) -> dict[str, Any]:
    model_id, node = _resolve_model(manifest, model)
    version = _dbt_version(manifest)
    if _version_tuple(version) < (1, 8, 0):
        raise ValueError(f"dbt unit tests require dbt >= 1.8; detected {version}")
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
    incremental = _incremental_analysis(node, sql)
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

    incremental_tests: list[dict[str, Any]] = []
    if incremental["is_incremental"]:
        unique_key = incremental["unique_key"][0] if incremental["unique_key"] else None
        remaining = max(0, max_scenarios - len(tests))
        selected = _INCREMENTAL_SCENARIOS[:remaining or len(_INCREMENTAL_SCENARIOS)]
        incremental_tests = [
            _incremental_test(
                node,
                dependency_ids,
                nodes,
                output_columns,
                scenario,
                index,
                unique_key,
            )
            for index, scenario in enumerate(selected, 1)
        ]
        tests.extend(incremental_tests)

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
        "dbt_version": version,
        "materialized": (node.get("config") or {}).get("materialized"),
        "incremental_analysis": incremental,
        "incremental_scenarios": [
            item["name"].split("_incremental_", 1)[-1]
            for item in incremental_tests
        ],
        "dependency_count": len(dependency_ids),
        "tests": tests,
        "test_count": len(tests),
        "logic_categories": categories,
        "anti_patterns": anti_patterns,
        "column_lineage": lineage,
        "warnings": [
            "Expected outputs are type-correct deterministic placeholders; validate by running dbt unit tests before applying.",
            *(
                [
                    "Incremental unit tests exercise model SQL with is_incremental=true; adapter-level MERGE/delete+insert/insert_overwrite/microbatch materialization semantics require dbt build/live verification."
                ]
                if incremental["is_incremental"]
                else []
            ),
        ],
        "yaml": yaml.safe_dump(payload, sort_keys=False),
        "applied": False,
        "requires_builder_approval": True,
    }
