"""Remaining deterministic Altimate core wrapper behaviors."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import sqlglot
from sqlglot import exp

from agentic_data_platform.dbt.adapter import LocalDbtProjectAdapter
from agentic_data_platform.governance.pii import scan_metadata, scan_query
from agentic_data_platform.lineage.engine import analyze_column_lineage
from agentic_data_platform.sql.core_compat import import_ddl, load_schema
from agentic_data_platform.sql.lineage import dialect_name
from agentic_data_platform.sql.parity import diff_sql


def classify_schema_pii(*, schema_context=None, schema_path=None) -> dict[str, Any]:
    schema = load_schema(schema_context, schema_path)
    columns = []
    for table, definition in schema.items():
        raw = definition.get("columns") if isinstance(definition, Mapping) and isinstance(definition.get("columns"), Mapping) else definition
        if not isinstance(raw, Mapping):
            continue
        for name, value in raw.items():
            details = value if isinstance(value, Mapping) else {"data_type": value}
            columns.append(
                {
                    "object_id": table,
                    "column_name": str(name),
                    "data_type": details.get("data_type") or details.get("type"),
                    "description": details.get("description"),
                    "tags": details.get("tags") or (),
                }
            )
    result = scan_metadata(columns)
    return {
        "status": "PASS",
        "success": True,
        "finding_count": result["classification_count"],
        "findings": result["findings"],
        "total_columns": len(columns),
    }


def query_pii(sql: str, *, schema_context=None, schema_path=None) -> dict[str, Any]:
    schema = load_schema(schema_context, schema_path)
    if not schema:
        return {
            "status": "FAIL",
            "success": False,
            "exposure_count": 0,
            "pii_columns": [],
            "error": "schema_context or schema_path is required",
        }
    normalized = {}
    for table, definition in schema.items():
        raw = definition.get("columns") if isinstance(definition, Mapping) and isinstance(definition.get("columns"), Mapping) else definition
        normalized[table] = raw if isinstance(raw, Mapping) else {}
    result = scan_query(sql, normalized)
    exposures = result.get("pii_columns_referenced", [])
    return {
        "status": "PASS",
        "success": True,
        "exposure_count": len(exposures),
        "pii_columns": exposures,
        "accesses_pii": bool(exposures),
    }


def compare_sql(left_sql: str, right_sql: str, *, dialect=None) -> dict[str, Any]:
    result = diff_sql(left_sql, right_sql, dialect)
    if not result.get("success"):
        return {
            "status": "FAIL",
            "success": False,
            "identical": False,
            "diff_count": 0,
            "diffs": [],
            "error": result.get("error"),
        }
    diffs = [
        {
            "change_type": item["operation"],
            "description": (
                f"AST tokens {item['operation']} "
                f"left={item['original']} right={item['modified']}"
            ),
        }
        for item in result.get("ast_changes", ())
    ]
    return {
        "status": "PASS",
        "success": True,
        "identical": not result.get("has_changes"),
        "diff_count": len(diffs),
        "diffs": diffs,
        "similarity": result.get("similarity"),
        "unified_diff": result.get("unified_diff"),
    }


def export_ddl(*, schema_context=None, schema_path=None) -> dict[str, Any]:
    schema = load_schema(schema_context, schema_path)
    statements = []
    for table in sorted(schema):
        definition = schema[table]
        raw = definition.get("columns") if isinstance(definition, Mapping) and isinstance(definition.get("columns"), Mapping) else definition
        if not isinstance(raw, Mapping):
            raw = {}
        columns = []
        for name, value in raw.items():
            details = value if isinstance(value, Mapping) else {"data_type": value}
            data_type = str(details.get("data_type") or details.get("type") or "VARCHAR")
            nullable = details.get("nullable", True)
            suffix = "" if nullable is not False else " NOT NULL"
            columns.append(f"{name} {data_type}{suffix}")
        statements.append(f"CREATE TABLE {table} (" + ", ".join(columns) + ");")
    return {
        "status": "PASS",
        "success": True,
        "table_count": len(statements),
        "ddl": "\n\n".join(statements),
    }


def extract_sql_metadata(sql: str, *, dialect=None) -> dict[str, Any]:
    try:
        trees = [tree for tree in sqlglot.parse(sql, read=dialect_name(dialect)) if tree is not None]
    except sqlglot.errors.SqlglotError as exc:
        return {"status": "FAIL", "success": False, "tables": [], "columns": [], "functions": [], "ctes": [], "error": str(exc)}
    tables = sorted({
        table.sql(dialect=dialect_name(dialect)).replace('"', "").replace(chr(96), "")
        for tree in trees
        for table in tree.find_all(exp.Table)
    })
    columns = sorted({
        column.sql(dialect=dialect_name(dialect)).replace('"', "").replace(chr(96), "")
        for tree in trees
        for column in tree.find_all(exp.Column)
    })
    functions = sorted({
        node.sql_name().upper()
        for tree in trees
        for node in tree.walk()
        if isinstance(node, exp.Func)
    })
    ctes = sorted({
        str(cte.alias_or_name)
        for tree in trees
        for cte in tree.find_all(exp.CTE)
        if cte.alias_or_name
    })
    return {
        "status": "PASS",
        "success": True,
        "tables": tables,
        "columns": columns,
        "functions": functions,
        "ctes": ctes,
    }


def migration_safety(old_ddl: str, new_ddl: str, *, dialect=None) -> dict[str, Any]:
    old = import_ddl(old_ddl, dialect=dialect)
    new = import_ddl(new_ddl, dialect=dialect)
    if not old.get("success") or not new.get("success"):
        return {
            "status": "FAIL",
            "success": False,
            "safe": False,
            "overall_risk": "unknown",
            "findings": [],
            "errors": [*old.get("errors", ()), *new.get("errors", ())],
        }

    findings = []
    old_schema, new_schema = old["schema"], new["schema"]
    for table in sorted(set(old_schema) - set(new_schema)):
        findings.append({
            "risk": "critical",
            "operation": "drop_table",
            "message": f"table removed: {table}",
            "mitigation": "confirm data retention/backup before removal",
        })
    for table in sorted(set(old_schema) & set(new_schema)):
        old_cols = old_schema[table].get("columns", {})
        new_cols = new_schema[table].get("columns", {})
        for column in sorted(set(old_cols) - set(new_cols)):
            findings.append({
                "risk": "high",
                "operation": "drop_column",
                "message": f"column removed: {table}.{column}",
                "mitigation": "verify no downstream dependency before removal",
            })
        for column in sorted(set(old_cols) & set(new_cols)):
            before, after = old_cols[column], new_cols[column]
            if str(before.get("data_type")).casefold() != str(after.get("data_type")).casefold():
                findings.append({
                    "risk": "medium",
                    "operation": "type_change",
                    "message": (
                        f"type changed: {table}.{column} "
                        f"{before.get('data_type')} -> {after.get('data_type')}"
                    ),
                    "mitigation": "validate range/precision compatibility and data parity",
                })
            if before.get("nullable", True) is True and after.get("nullable", True) is False:
                findings.append({
                    "risk": "medium",
                    "operation": "nullable_tightening",
                    "message": f"column became NOT NULL: {table}.{column}",
                    "mitigation": "verify existing data contains no NULL values",
                })

    ranks = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    overall = max((item["risk"] for item in findings), key=lambda value: ranks[value], default="safe")
    risky = [item for item in findings if item["risk"] != "safe"]
    return {
        "status": "PASS",
        "success": True,
        "safe": not risky,
        "overall_risk": overall,
        "risk_count": len(risky),
        "findings": findings,
    }


def parse_dbt_project(project_dir: str | Path) -> dict[str, Any]:
    adapter = LocalDbtProjectAdapter(project_dir)
    manifest = adapter.load_manifest()
    models = adapter.list_models(manifest)
    sources = adapter.list_sources(manifest)
    tests = adapter.list_tests(manifest)
    seeds = adapter._nodes_by_type(manifest, "seed")
    return {
        "status": "PASS",
        "success": True,
        "project": adapter.project_metadata(),
        "models": models,
        "sources": sources,
        "tests": tests,
        "seeds": seeds,
        "model_count": len(models),
        "source_count": len(sources),
        "test_count": len(tests),
        "seed_count": len(seeds),
    }


def generate_sql_tests(sql: str, *, dialect=None, schema_context=None, schema_path=None) -> dict[str, Any]:
    schema = load_schema(schema_context, schema_path)
    try:
        tree = sqlglot.parse_one(sql, read=dialect_name(dialect))
    except sqlglot.errors.SqlglotError as exc:
        return {"status": "FAIL", "success": False, "tests": [], "test_count": 0, "error": str(exc)}

    tests = [
        {
            "name": "query-parses",
            "description": "SQL parses in the requested dialect.",
            "category": "syntax",
            "assertion": "parse succeeds",
        },
        {
            "name": "empty-input-behavior",
            "description": "Validate query behavior when source relations contain zero rows.",
            "category": "edge_case",
            "assertion": "query returns a valid empty or aggregate result",
        },
        {
            "name": "null-handling",
            "description": "Validate nullable input columns and NULL propagation.",
            "category": "null",
            "assertion": "NULL behavior matches intended semantics",
        },
    ]
    if any(True for _ in tree.find_all(exp.Div)):
        tests.append({
            "name": "zero-denominator",
            "description": "Validate division when denominator is zero.",
            "category": "boundary",
            "assertion": "query does not raise divide-by-zero unexpectedly",
        })
    if any(True for _ in tree.find_all(exp.Join)):
        tests.append({
            "name": "join-cardinality",
            "description": "Validate duplicate/missing join-key behavior.",
            "category": "join",
            "assertion": "join cardinality and unmatched-row handling are correct",
        })
    if schema:
        tests.append({
            "name": "schema-contract",
            "description": "Validate referenced tables/columns against supplied schema context.",
            "category": "schema",
            "assertion": "all references exist and types are compatible",
        })
    return {"status": "PASS", "success": True, "tests": tests, "test_count": len(tests)}


def track_lineage(queries: list[str], *, dialect=None, schema_context=None, schema_path=None) -> dict[str, Any]:
    schema = load_schema(schema_context, schema_path)
    query_results = []
    all_edges = []
    for index, sql in enumerate(queries):
        result = analyze_column_lineage(sql, dialect=dialect, schema=schema or None)
        edges = []
        for mapping in result.get("mappings", ()):
            target = mapping.get("target") or mapping.get("target_column")
            for source in mapping.get("sources", ()):
                edge = {
                    "source": {
                        "table": source.get("table"),
                        "column": source.get("column"),
                    },
                    "target": {"table": f"query_{index}", "column": target},
                    "transform_type": "expression",
                }
                edges.append(edge)
                all_edges.append(edge)
        query_results.append({
            "index": index,
            "status": result.get("status"),
            "edges": edges,
        })
    return {
        "status": "PASS",
        "success": True,
        "queries": query_results,
        "edges": all_edges,
        "edge_count": len(all_edges),
    }
