"""Deterministic compatibility layer for Altimate core SQL behaviors."""

from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping

import sqlglot
import yaml
from sqlglot import exp

from agentic_data_platform.governance.pii import scan_query
from agentic_data_platform.sql.intelligence import review_sql
from agentic_data_platform.sql.lineage import dialect_name
from agentic_data_platform.sql.parity import autocomplete_sql, fix_sql


def load_schema(schema_context=None, schema_path=None) -> dict[str, Any]:
    if schema_context:
        return {str(k): v for k, v in schema_context.items()}
    if not schema_path:
        return {}
    path = Path(schema_path).expanduser().resolve()
    text = path.read_text()
    value = json.loads(text) if path.suffix.casefold() == ".json" else yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("schema must be a table mapping")
    return {str(k): v for k, v in value.items()}


def _columns(definition: Any) -> dict[str, Any]:
    if isinstance(definition, Mapping):
        nested = definition.get("columns")
        return dict(nested) if isinstance(nested, Mapping) else dict(definition)
    if isinstance(definition, list):
        result = {}
        for item in definition:
            if isinstance(item, Mapping) and item.get("name"):
                result[str(item["name"])] = item.get("data_type") or item.get("type") or "UNKNOWN"
            else:
                result[str(item)] = "UNKNOWN"
        return result
    return {}


def _clean_identifier(value: str) -> str:
    return value.replace('"', "").replace("`", "")


def complete_sql(sql: str, cursor_pos: int, *, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    fragment = sql[: max(0, min(int(cursor_pos), len(sql)))]
    match = re.search(r"([A-Za-z_][\w$]*)$", fragment)
    result = autocomplete_sql(fragment, match.group(1) if match else "", schema)
    items = result.get("items") or result.get("suggestions") or []
    return {"status": "PASS", "success": True, "suggestion_count": len(items), "items": items, "schema_aware": bool(schema)}


def validate_sql(sql: str, *, dialect=None, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    review = review_sql(sql, dialect, schema or None)
    errors = []
    if not review.get("parseable"):
        errors = [{"message": item.get("message"), "rule": item.get("rule_id")} for item in review.get("findings", ())]
        return {"status": "PASS", "success": True, "valid": False, "has_schema": bool(schema), "errors": errors}
    if schema:
        tree = sqlglot.parse_one(sql, read=dialect_name(dialect))
        exact = {name.casefold(): name for name in schema}
        simple = {name.split(".")[-1].casefold(): name for name in schema}
        aliases = {}
        for table in tree.find_all(exp.Table):
            rendered = _clean_identifier(table.sql(dialect=dialect_name(dialect)))
            resolved = exact.get(rendered.casefold()) or simple.get(table.name.casefold())
            if resolved is None:
                errors.append({"message": f"table not found: {rendered}", "rule": "missing_table"})
            aliases[table.alias_or_name.casefold()] = resolved or rendered
        for column in tree.find_all(exp.Column):
            if column.name == "*" or not column.table:
                continue
            table_name = aliases.get(column.table.casefold(), column.table)
            definition = schema.get(table_name)
            if definition is None:
                resolved = simple.get(str(table_name).split(".")[-1].casefold())
                definition = schema.get(resolved) if resolved else None
            if definition is not None and column.name.casefold() not in {name.casefold() for name in _columns(definition)}:
                errors.append({"message": f"column not found: {column.table}.{column.name}", "rule": "missing_column"})
    return {"status": "PASS", "success": True, "valid": not errors, "has_schema": bool(schema), "errors": errors}


def semantic_equivalence(sql1: str, sql2: str, *, dialect=None, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    if not schema:
        return {"status": "FAIL", "success": False, "equivalent": False, "has_schema": False, "error": "schema_context or schema_path is required"}
    validations = [validate_sql(sql, dialect=dialect, schema_context=schema) for sql in (sql1, sql2)]
    if not all(item["valid"] for item in validations):
        return {"status": "PASS", "success": False, "equivalent": False, "has_schema": True, "validation_errors": [error for item in validations for error in item["errors"]]}

    def normalized(sql: str) -> str:
        tree = sqlglot.parse_one(sql, read=dialect_name(dialect))
        try:
            from sqlglot.optimizer import optimize
            tree = optimize(tree, schema=dict(schema), dialect=dialect_name(dialect))
        except Exception:
            pass
        return tree.sql(dialect=dialect_name(dialect), normalize=True, pretty=False)

    left, right = normalized(sql1), normalized(sql2)
    equivalent = left == right
    return {
        "status": "PASS", "success": True, "equivalent": equivalent, "has_schema": True,
        "confidence": "high" if equivalent else "medium",
        "similarity": round(SequenceMatcher(None, left, right, autojunk=False).ratio(), 6),
        "differences": [] if equivalent else [{"description": "normalized optimized SQL differs", "left": left, "right": right}],
    }


def grade_sql(sql: str, *, dialect=None, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    review = review_sql(sql, dialect, schema or None)
    if not review.get("parseable"):
        return {"status": "PASS", "success": True, "grade": "F", "score": 0, "scores": {"overall": 0.0, "syntax": 0.0, "style": 0.0, "safety": 0.0, "complexity": 0.0}, "feedback": [item.get("message") for item in review.get("findings", ())]}
    weights = {"INFO": 1, "WARN": 5, "WARNING": 5, "ERROR": 18, "CRITICAL": 30}
    findings = list(review.get("findings", ()))
    penalty = sum(weights.get(str(item.get("severity") or "WARN").upper(), 5) for item in findings)
    score = max(0, 100 - penalty)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    safety_rules = {"DANGEROUS_DDL", "DROP_TRUNCATE", "DELETE_WITHOUT_WHERE", "UPDATE_WITHOUT_WHERE", "MERGE_RISK"}
    safety_penalty = sum(weights.get(str(item.get("severity") or "WARN").upper(), 5) for item in findings if str(item.get("rule_id") or "").upper() in safety_rules)
    return {
        "status": "PASS", "success": True, "grade": grade, "score": score,
        "scores": {"overall": score / 100, "syntax": 1.0, "style": max(0, score + safety_penalty) / 100, "safety": max(0, 100 - safety_penalty) / 100, "complexity": max(0, 100 - min(40, len(findings) * 3)) / 100},
        "feedback": [str(item.get("recommendation") or item.get("message") or "") for item in findings],
    }


def optimize_schema_context(*, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    tables = sorted(schema)
    level1 = {"tables": tables}
    level2 = {table: sorted(_columns(schema[table])) for table in tables}
    level3 = {table: {name: (value.get("data_type") or value.get("type") or "UNKNOWN") if isinstance(value, Mapping) else value for name, value in _columns(schema[table]).items()} for table in tables}
    level4 = {table: {"columns": level3[table], "column_count": len(level3[table])} for table in tables}
    levels = []
    for index, value in enumerate((level1, level2, level3, level4, schema), 1):
        text = json.dumps(value, sort_keys=True, default=str)
        levels.append({"level": index, "tokens": math.ceil(len(text) / 4), "characters": len(text), "schema": value})
    return {"status": "PASS", "success": True, "levels": levels, "table_count": len(tables)}


def prune_schema(sql: str, *, dialect=None, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    tree = sqlglot.parse_one(sql, read=dialect_name(dialect))
    referenced = {_clean_identifier(table.sql(dialect=dialect_name(dialect))) for table in tree.find_all(exp.Table)}
    simple = {name.split(".")[-1].casefold() for name in referenced}
    pruned = {name: value for name, value in schema.items() if name.casefold() in {item.casefold() for item in referenced} or name.split(".")[-1].casefold() in simple}
    return {"status": "PASS", "success": True, "total_tables": len(schema), "tables_pruned": len(schema) - len(pruned), "relevant_tables": sorted(pruned), "pruned": pruned, "pruned_schema_yaml": yaml.safe_dump(pruned, sort_keys=True)}


def resolve_term(term: str, *, schema_context=None, schema_path=None, limit: int = 20):
    schema = load_schema(schema_context, schema_path)
    wanted = term.casefold().strip()
    matches = []
    for table, definition in schema.items():
        candidates = [(table, None)] + [(f"{table}.{column}", column) for column in _columns(definition)]
        for fqn, column in candidates:
            text = fqn.replace("_", " ").casefold()
            score = SequenceMatcher(None, wanted, text, autojunk=False).ratio()
            if wanted and wanted in text:
                score = max(score, 0.9)
            if set(wanted.split()) and set(wanted.split()).issubset(set(text.split())):
                score = max(score, 0.95)
            if score >= 0.35:
                matches.append({"fqn": fqn, "table": table, "column": column, "matched_column": {"table": table, "column": column} if column else None, "confidence": round(score, 4), "source": "schema"})
    matches.sort(key=lambda item: (-item["confidence"], item["fqn"]))
    bounded = matches[: max(1, min(int(limit), 100))]
    return {"status": "PASS", "success": True, "term": term, "matches": bounded, "match_count": len(bounded)}


def policy_check(sql: str, policy_json, *, dialect=None, schema_context=None, schema_path=None):
    policy = json.loads(policy_json) if isinstance(policy_json, str) else dict(policy_json)
    schema = load_schema(schema_context, schema_path)
    review = review_sql(sql, dialect, schema or None)
    if not review.get("parseable"):
        return {"status": "FAIL", "success": False, "allowed": False, "violations": [{"rule": "valid_sql", "message": "SQL is not parseable", "severity": "error"}], "warnings": []}
    tree = sqlglot.parse_one(sql, read=dialect_name(dialect))
    tables = {_clean_identifier(table.sql(dialect=dialect_name(dialect))) for table in tree.find_all(exp.Table)}
    denied = {str(item).casefold() for item in policy.get("denied_tables", policy.get("forbidden_tables", ()))}
    allowed = {str(item).casefold() for item in policy.get("allowed_tables", ())}
    violations, warnings = [], []
    for table in sorted(tables):
        low, simple = table.casefold(), table.split(".")[-1].casefold()
        if low in denied or simple in denied:
            violations.append({"rule": "forbidden_table", "message": f"table is forbidden: {table}", "severity": "error"})
        if allowed and low not in allowed and simple not in allowed:
            violations.append({"rule": "allowed_tables", "message": f"table is not allowlisted: {table}", "severity": "error"})
    op = str(tree.key or "").casefold()
    if op in {str(item).casefold() for item in policy.get("forbidden_operations", ())}:
        violations.append({"rule": "forbidden_operation", "message": f"operation is forbidden: {op}", "severity": "error"})
    if policy.get("require_where_for_mutations", True) and isinstance(tree, (exp.Update, exp.Delete)) and tree.args.get("where") is None:
        violations.append({"rule": "mutation_where", "message": f"{op} requires WHERE", "severity": "error"})
    if policy.get("warn_on_select_star", False) and any(True for _ in tree.find_all(exp.Star)):
        warnings.append({"rule": "select_star", "message": "SELECT * is discouraged", "severity": "warning"})
    return {"status": "PASS", "success": True, "allowed": not violations, "pass": not violations, "violations": violations, "warnings": warnings, "has_schema": bool(schema)}


def semantics(sql: str, *, dialect=None, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    if not schema:
        return {"status": "FAIL", "success": False, "valid": False, "has_schema": False, "findings": [], "error": "schema_context or schema_path is required"}
    validation = validate_sql(sql, dialect=dialect, schema_context=schema)
    review = review_sql(sql, dialect, schema)
    findings = list(review.get("findings", ()))
    return {"status": "PASS", "success": validation["valid"], "valid": validation["valid"], "has_schema": True, "findings": findings, "issue_count": len(findings), "validation_errors": validation["errors"]}


def full_check(sql: str, *, dialect=None, schema_context=None, schema_path=None):
    schema = load_schema(schema_context, schema_path)
    validation = validate_sql(sql, dialect=dialect, schema_context=schema or None)
    lint = review_sql(sql, dialect, schema or None)
    pii = scan_query(sql, {table: {name: value if isinstance(value, Mapping) else {"data_type": value} for name, value in _columns(definition).items()} for table, definition in schema.items()}) if schema else {"count": 0, "pii_columns_referenced": []}
    safety_rules = {"DANGEROUS_DDL", "DROP_TRUNCATE", "DELETE_WITHOUT_WHERE", "UPDATE_WITHOUT_WHERE", "MERGE_RISK"}
    threats = [item for item in lint.get("findings", ()) if str(item.get("rule_id") or "").upper() in safety_rules]
    return {"status": "PASS", "success": True, "has_schema": bool(schema), "validation": {"valid": validation["valid"], "errors": validation["errors"]}, "lint": {"clean": not lint.get("findings"), "findings": lint.get("findings", [])}, "safety": {"safe": not threats, "threats": threats}, "pii": {"accesses_pii": bool(pii.get("count")), "pii_columns": pii.get("pii_columns_referenced", [])}}


def correct_sql(sql: str, *, dialect=None, schema_context=None, schema_path=None, max_iterations: int = 3):
    schema = load_schema(schema_context, schema_path)
    current, changes = sql, []
    for iteration in range(1, max(1, min(int(max_iterations), 10)) + 1):
        validation = validate_sql(current, dialect=dialect, schema_context=schema or None)
        review = review_sql(current, dialect, schema or None)
        blocking = [item for item in review.get("findings", ()) if str(item.get("severity") or "").upper() in {"ERROR", "CRITICAL"}]
        fixed = fix_sql(current, dialect, schema or None)
        candidate = fixed.get("fixed_sql") or current
        if candidate != current:
            changes.extend(fixed.get("fixes", ()))
            current = candidate
            continue
        if validation["valid"] and not blocking:
            return {"status": "PASS", "success": True, "corrected_sql": current, "iterations": iteration - 1, "changes": changes, "final_validation": validation}
        break
    final_validation = validate_sql(current, dialect=dialect, schema_context=schema or None)
    return {"status": "PASS", "success": final_validation["valid"], "corrected_sql": current if current != sql else None, "iterations": len(changes), "changes": changes, "final_validation": final_validation}


def import_ddl(ddl: str, *, dialect=None):
    schema, errors = {}, []
    try:
        trees = sqlglot.parse(ddl, read=dialect_name(dialect))
    except sqlglot.errors.SqlglotError as exc:
        return {"status": "FAIL", "success": False, "schema": {}, "errors": [str(exc)]}
    for tree in trees:
        if not isinstance(tree, exp.Create) or str(tree.args.get("kind") or "").upper() != "TABLE":
            continue
        table_expr = tree.this
        table = table_expr.this if isinstance(table_expr, exp.Schema) else table_expr
        table_name = _clean_identifier(table.sql(dialect=dialect_name(dialect)))
        columns = {}
        schema_expr = table_expr if isinstance(table_expr, exp.Schema) else tree.find(exp.Schema)
        for column in (schema_expr.expressions if isinstance(schema_expr, exp.Schema) else []):
            if isinstance(column, exp.ColumnDef):
                kind = column.args.get("kind")
                columns[column.this.name] = {"data_type": kind.sql(dialect=dialect_name(dialect)) if kind else "UNKNOWN", "nullable": not any(True for _ in column.find_all(exp.NotNullColumnConstraint))}
        schema[table_name] = {"columns": columns}
    if not schema:
        errors.append("no CREATE TABLE statements found")
    return {"status": "PASS" if schema else "FAIL", "success": bool(schema), "schema": schema, "errors": errors}


def introspection_sql(db_type: str, database: str, *, schema_name=None):
    platform = db_type.casefold()
    escaped_schema = schema_name.replace("'", "''") if schema_name else None
    if platform in {"postgres", "redshift", "mysql", "mssql", "sqlserver"}:
        filt = f" WHERE table_schema = '{escaped_schema}'" if escaped_schema else ""
        queries = {
            "schemas": "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name",
            "tables": "SELECT table_schema, table_name, table_type FROM information_schema.tables" + filt + " ORDER BY table_schema, table_name",
            "columns": "SELECT table_schema, table_name, column_name, data_type, is_nullable FROM information_schema.columns" + filt + " ORDER BY table_schema, table_name, ordinal_position",
        }
    elif platform == "snowflake":
        prefix = f"{database}." if database else ""
        queries = {
            "schemata": f"SHOW SCHEMAS IN DATABASE {database}",
            "tables": f"SELECT table_schema, table_name, table_type FROM {prefix}information_schema.tables" + (f" WHERE table_schema = '{escaped_schema}'" if escaped_schema else ""),
            "columns": f"SELECT table_schema, table_name, column_name, data_type FROM {prefix}information_schema.columns" + (f" WHERE table_schema = '{escaped_schema}'" if escaped_schema else ""),
        }
    elif platform == "bigquery":
        tick = chr(96)
        region = schema_name or "region-us"
        queries = {
            "schemata": f"SELECT schema_name FROM {tick}{database}.{region}.INFORMATION_SCHEMA.SCHEMATA{tick}",
            "tables": f"SELECT table_schema, table_name, table_type FROM {tick}{database}.{region}.INFORMATION_SCHEMA.TABLES{tick}",
            "columns": f"SELECT table_schema, table_name, column_name, data_type FROM {tick}{database}.{region}.INFORMATION_SCHEMA.COLUMNS{tick}",
        }
    else:
        return {"status": "UNSUPPORTED", "success": False, "db_type": db_type, "queries": {}}
    return {"status": "PASS", "success": True, "db_type": platform, "queries": queries}
