"""Altimate-compatible deterministic SQL tool surface built on SQLGlot."""

from __future__ import annotations

import difflib
import re
from typing import Any, Mapping, Sequence

import sqlglot
from sqlglot import exp

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.sql.intelligence import review_sql
from agentic_data_platform.sql.lineage import dialect_name


_READ_KEYS = {"select", "union", "intersect", "except", "show", "describe", "desc", "explain"}
_HARD_DENY = re.compile(r"^\s*(?:DROP\s+(?:DATABASE|SCHEMA)\b|TRUNCATE(?:\s+TABLE)?\b)", re.I)


def _read_dialect(dialect: str | None) -> str | None:
    value = dialect_name(dialect)
    return None if value in {"ansi", ""} else value


def _parse(sql: str, dialect: str | None = None) -> list[exp.Expression]:
    trees = [tree for tree in sqlglot.parse(sql, read=_read_dialect(dialect)) if tree is not None]
    if not trees:
        raise ValueError("SQL is empty")
    return trees


def _statement_type(tree: exp.Expression) -> str:
    return str(tree.key or tree.__class__.__name__).upper()


def _is_read(tree: exp.Expression) -> bool:
    key = str(tree.key or "").casefold()
    return isinstance(tree, exp.Query) or key in _READ_KEYS


def classify_sql(sql: str, dialect: str | None = None) -> dict[str, Any]:
    if not isinstance(sql, str) or not sql.strip():
        return {
            "query_type": "read",
            "blocked": False,
            "statement_types": [],
            "categories": [],
            "parseable": False,
            "error": "SQL is empty",
        }
    try:
        trees = _parse(sql, dialect)
        types = [_statement_type(tree) for tree in trees]
        categories = ["query" if _is_read(tree) else "write" for tree in trees]
        blocked = any(_HARD_DENY.search(tree.sql()) for tree in trees)
        return {
            "query_type": "read" if all(item == "query" for item in categories) else "write",
            "blocked": blocked,
            "statement_types": types,
            "categories": categories,
            "parseable": True,
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        cleaned = re.sub(r"/\*[\s\S]*?\*/|--[^\n]*", " ", sql)
        statements = [item.strip() for item in cleaned.split(";") if item.strip()]
        read_pattern = re.compile(r"^(?:SELECT|WITH|SHOW|EXPLAIN|DESCRIBE|DESC)\b", re.I)
        query_type = "read" if all(read_pattern.search(item) for item in statements) else "write"
        return {
            "query_type": query_type,
            "blocked": any(_HARD_DENY.search(item) for item in statements),
            "statement_types": [],
            "categories": [],
            "parseable": False,
            "error": str(exc),
        }


def fingerprint_sql(sql: str, dialect: str | None = None) -> dict[str, Any]:
    trees = _parse(sql, dialect)
    nodes = [node for tree in trees for node in tree.walk()]
    tables = sorted({table.sql() for tree in trees for table in tree.find_all(exp.Table)})
    functions = [node.sql_name().upper() for node in nodes if isinstance(node, exp.Func)]
    return {
        "statement_types": [_statement_type(tree) for tree in trees],
        "categories": ["query" if _is_read(tree) else "write" for tree in trees],
        "table_count": len(tables),
        "function_count": len(functions),
        "has_subqueries": any(isinstance(node, exp.Subquery) for node in nodes),
        "has_aggregation": any(isinstance(node, exp.AggFunc) for node in nodes),
        "has_window_functions": any(isinstance(node, exp.Window) for node in nodes),
        "node_count": len(nodes),
    }


def analyze_sql(sql: str, dialect: str | None = None, schema_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = review_sql(sql, dialect, schema_context)
    classification = classify_sql(sql, dialect)
    result["classification"] = classification
    if result.get("parseable"):
        result["fingerprint"] = fingerprint_sql(sql, dialect)
        for finding in result.get("findings", []):
            finding.setdefault("confidence", "high")
            finding.setdefault("location", {"line": finding.get("line"), "column": finding.get("column")})
    return result


def format_sql(sql: str, dialect: str | None = None, indent: int = 2) -> dict[str, Any]:
    del indent  # SQLGlot owns its stable pretty-print indentation.
    try:
        trees = _parse(sql, dialect)
        formatted = ";\n\n".join(tree.sql(dialect=_read_dialect(dialect), pretty=True) for tree in trees)
        return {"success": True, "formatted_sql": formatted, "statement_count": len(trees), "error": None}
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {"success": False, "formatted_sql": None, "statement_count": 0, "error": str(exc)}


def translate_sql(sql: str, source_dialect: str, target_dialect: str) -> dict[str, Any]:
    try:
        source = _read_dialect(source_dialect)
        target = _read_dialect(target_dialect)
        original = _parse(sql, source_dialect)
        translated = sqlglot.transpile(sql, read=source, write=target, pretty=True)
        anonymous = sorted({
            node.name.upper()
            for tree in original
            for node in tree.find_all(exp.Anonymous)
            if node.name
        })
        warnings = [
            f"Verify function {name} exists with equivalent semantics in {target_dialect}."
            for name in anonymous
        ]
        return {
            "success": True,
            "source_dialect": source_dialect,
            "target_dialect": target_dialect,
            "translated_sql": ";\n\n".join(translated),
            "statement_count": len(translated),
            "warnings": warnings,
            "confidence": "medium" if warnings else "high",
            "error": None,
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {
            "success": False,
            "source_dialect": source_dialect,
            "target_dialect": target_dialect,
            "translated_sql": None,
            "statement_count": 0,
            "warnings": [],
            "confidence": "unknown",
            "error": str(exc),
        }


def _canonical(sql: str, dialect: str | None) -> tuple[str, list[str]]:
    trees = _parse(sql, dialect)
    statements = [tree.sql(dialect=_read_dialect(dialect), pretty=True, normalize=True) for tree in trees]
    return ";\n".join(statements), statements


def _ast_tokens(sql: str, dialect: str | None) -> list[str]:
    tokens: list[str] = []
    for tree in _parse(sql, dialect):
        for node in tree.walk():
            if isinstance(node, (exp.Identifier, exp.Literal)):
                value = node.sql(dialect=_read_dialect(dialect), normalize=True)
            else:
                value = node.key.upper()
            tokens.append(f"{node.key}:{value}")
    return tokens


def diff_sql(original: str, modified: str, dialect: str | None = None, context_lines: int = 3) -> dict[str, Any]:
    try:
        left, _ = _canonical(original, dialect)
        right, _ = _canonical(modified, dialect)
        left_tokens, right_tokens = _ast_tokens(original, dialect), _ast_tokens(modified, dialect)
        matcher = difflib.SequenceMatcher(a=left_tokens, b=right_tokens, autojunk=False)
        opcodes = matcher.get_opcodes()
        changes = [
            {"operation": tag, "original": [i1, i2], "modified": [j1, j2]}
            for tag, i1, i2, j1, j2 in opcodes if tag != "equal"
        ]
        unified = "\n".join(difflib.unified_diff(
            left.splitlines(), right.splitlines(), fromfile="original.sql", tofile="modified.sql",
            lineterm="", n=max(0, int(context_lines)),
        ))
        additions = sum(j2 - j1 for tag, _, _, j1, j2 in opcodes if tag in {"insert", "replace"})
        deletions = sum(i2 - i1 for tag, i1, i2, _, _ in opcodes if tag in {"delete", "replace"})
        similarity = matcher.ratio()
        return {
            "success": True,
            "has_changes": bool(changes),
            "change_count": len(changes),
            "additions": additions,
            "deletions": deletions,
            "similarity": similarity,
            "unified_diff": unified,
            "ast_changes": changes,
            "canonical_original": left,
            "canonical_modified": right,
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {
            "success": False, "has_changes": False, "change_count": 0, "additions": 0, "deletions": 0,
            "similarity": 0.0, "unified_diff": "", "ast_changes": [], "error": str(exc),
        }


def optimize_sql(sql: str, dialect: str | None = None, schema_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        trees = _parse(sql, dialect)
        optimized_sql: list[str] = []
        optimizer_errors: list[str] = []
        for tree in trees:
            candidate = tree.copy()
            try:
                from sqlglot.optimizer import optimize as sqlglot_optimize

                kwargs: dict[str, Any] = {}
                if schema_context:
                    kwargs["schema"] = dict(schema_context)
                read = _read_dialect(dialect)
                if read:
                    kwargs["dialect"] = read
                candidate = sqlglot_optimize(candidate, **kwargs)
            except Exception as exc:  # optimizer rules may require richer schema; fall back deterministically
                optimizer_errors.append(str(exc))
                try:
                    from sqlglot.optimizer.simplify import simplify

                    candidate = simplify(candidate)
                except Exception:
                    candidate = tree.copy()
            optimized_sql.append(candidate.sql(dialect=_read_dialect(dialect), pretty=True))

        review = analyze_sql(sql, dialect, schema_context)
        anti_patterns = [
            {
                "type": finding["rule_id"],
                "severity": finding["severity"],
                "confidence": finding.get("confidence", "high"),
                "message": finding["message"],
                "location": finding.get("location"),
                "recommendation": finding.get("recommendation"),
            }
            for finding in review.get("findings", [])
        ]
        output = ";\n\n".join(optimized_sql)
        changed = diff_sql(sql, output, dialect).get("has_changes", False)
        suggestions = [
            {
                "type": item["type"],
                "impact": "high" if item["severity"] in {"ERROR", "CRITICAL"} else "medium",
                "description": item["recommendation"],
            }
            for item in anti_patterns
            if item.get("recommendation")
        ]
        return {
            "success": True,
            "optimized_sql": output if changed else None,
            "suggestions": suggestions,
            "anti_patterns": anti_patterns,
            "confidence": "high" if schema_context else "medium",
            "schema_aware": bool(schema_context),
            "optimizer_warnings": optimizer_errors,
            "error": None,
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {
            "success": False, "optimized_sql": None, "suggestions": [], "anti_patterns": [],
            "confidence": "unknown", "schema_aware": bool(schema_context), "optimizer_warnings": [], "error": str(exc),
        }


def _columns_for_table(schema_context: Mapping[str, Any], table: str) -> list[str]:
    wanted = table.casefold()
    for name, definition in schema_context.items():
        simple = name.split(".")[-1].casefold()
        if name.casefold() not in {wanted} and simple != wanted.split(".")[-1]:
            continue
        if isinstance(definition, Mapping):
            return [str(column) for column in definition]
        if isinstance(definition, Sequence) and not isinstance(definition, (str, bytes)):
            return [str(item["name"] if isinstance(item, Mapping) and "name" in item else item) for item in definition]
    return []


def rewrite_sql(sql: str, dialect: str | None = None, schema_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        trees = _parse(sql, dialect)
        rewrites: list[dict[str, Any]] = []
        rewritten_trees: list[exp.Expression] = []

        for tree in trees:
            candidate = tree.copy()
            if schema_context:
                for select in list(candidate.find_all(exp.Select)):
                    tables = list(select.find_all(exp.Table))
                    alias_map = {table.alias_or_name: table.name for table in tables if table.alias_or_name}
                    new_projections: list[exp.Expression] = []
                    changed = False
                    for projection in select.expressions:
                        if isinstance(projection, exp.Star):
                            if len(tables) == 1:
                                table = tables[0]
                                columns = _columns_for_table(schema_context, table.name)
                                if columns:
                                    new_projections.extend(exp.column(column) for column in columns)
                                    changed = True
                                    rewrites.append({
                                        "rule": "SELECT_STAR",
                                        "explanation": "Expanded wildcard using supplied schema context.",
                                        "original_fragment": projection.sql(),
                                        "rewritten_fragment": ", ".join(columns),
                                        "can_auto_apply": True,
                                    })
                                    continue
                        if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
                            alias = projection.table
                            table_name = alias_map.get(alias, alias)
                            columns = _columns_for_table(schema_context, table_name)
                            if columns:
                                new_projections.extend(exp.column(column, table=alias) for column in columns)
                                changed = True
                                rewrites.append({
                                    "rule": "QUALIFIED_SELECT_STAR",
                                    "explanation": "Expanded qualified wildcard using supplied schema context.",
                                    "original_fragment": projection.sql(),
                                    "rewritten_fragment": ", ".join(f"{alias}.{column}" for column in columns),
                                    "can_auto_apply": True,
                                })
                                continue
                        new_projections.append(projection)
                    if changed:
                        select.set("expressions", new_projections)

            def fix_null_and_division(node: exp.Expression) -> exp.Expression:
                if isinstance(node, (exp.EQ, exp.NEQ)) and (
                    isinstance(node.left, exp.Null) or isinstance(node.right, exp.Null)
                ):
                    operand = node.right if isinstance(node.left, exp.Null) else node.left
                    replacement: exp.Expression = exp.Is(this=operand.copy(), expression=exp.Null())
                    if isinstance(node, exp.NEQ):
                        replacement = exp.Not(this=replacement)
                    rewrites.append({
                        "rule": "NULL_COMPARISON",
                        "explanation": "Replaced NULL equality with IS NULL / IS NOT NULL semantics.",
                        "original_fragment": node.sql(),
                        "rewritten_fragment": replacement.sql(),
                        "can_auto_apply": True,
                    })
                    return replacement
                if isinstance(node, exp.Div) and not isinstance(node.right, exp.Nullif):
                    replacement = node.copy()
                    replacement.set("expression", exp.Nullif(this=node.right.copy(), expression=exp.Literal.number(0)))
                    rewrites.append({
                        "rule": "SAFE_DIVISION",
                        "explanation": "Wrapped denominator with NULLIF(..., 0) to prevent divide-by-zero errors.",
                        "original_fragment": node.sql(),
                        "rewritten_fragment": replacement.sql(),
                        "can_auto_apply": True,
                    })
                    return replacement
                return node

            candidate = candidate.transform(fix_null_and_division)
            rewritten_trees.append(candidate)

        rewritten = ";\n\n".join(tree.sql(dialect=_read_dialect(dialect), pretty=True) for tree in rewritten_trees)
        return {
            "success": True,
            "rewritten_sql": rewritten if rewrites else None,
            "rewrites_applied": rewrites,
            "rewrite_count": len(rewrites),
            "auto_apply_count": sum(bool(item["can_auto_apply"]) for item in rewrites),
            "error": None,
        }
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {
            "success": False, "rewritten_sql": None, "rewrites_applied": [],
            "rewrite_count": 0, "auto_apply_count": 0, "error": str(exc),
        }


def fix_sql(sql: str, dialect: str | None = None, schema_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rewrite = rewrite_sql(sql, dialect, schema_context)
    review_before = analyze_sql(sql, dialect, schema_context)
    fixed = rewrite.get("rewritten_sql") or sql
    review_after = analyze_sql(fixed, dialect, schema_context) if rewrite.get("success") else review_before
    before_errors = sum(item["severity"] in {"ERROR", "CRITICAL"} for item in review_before.get("findings", []))
    after_errors = sum(item["severity"] in {"ERROR", "CRITICAL"} for item in review_after.get("findings", []))
    return {
        "success": bool(rewrite.get("success")),
        "original_sql": sql,
        "fixed_sql": fixed if fixed != sql else None,
        "fixes": rewrite.get("rewrites_applied", []),
        "blocking_findings_before": before_errors,
        "blocking_findings_after": after_errors,
        "improved": after_errors < before_errors or fixed != sql,
        "remaining_findings": review_after.get("findings", []),
        "error": rewrite.get("error"),
    }


_KEYWORDS = (
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "INNER JOIN",
    "GROUP BY", "ORDER BY", "HAVING", "QUALIFY", "LIMIT", "WITH", "UNION ALL", "CASE", "WHEN",
)


def autocomplete_sql(
    sql: str,
    prefix: str = "",
    schema_context: Mapping[str, Any] | None = None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    schema_context = schema_context or {}
    suggestions: list[dict[str, Any]] = []
    needle = prefix.casefold()

    alias_match = re.search(r"([A-Za-z_][\w$]*)\.([A-Za-z_\w$]*)$", sql[: max(0, len(sql))])
    aliases = {
        alias: table
        for table, alias in re.findall(
            r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w$.]*)\s+(?:AS\s+)?([A-Za-z_][\w$]*)",
            sql,
            re.I,
        )
    }
    if alias_match:
        alias, column_prefix = alias_match.groups()
        table = aliases.get(alias, alias)
        for column in _columns_for_table(schema_context, table):
            if column.casefold().startswith(column_prefix.casefold()):
                suggestions.append({"kind": "column", "label": column, "insert_text": column, "detail": table})
    else:
        for table, definition in schema_context.items():
            if not needle or table.casefold().startswith(needle):
                suggestions.append({"kind": "table", "label": table, "insert_text": table, "detail": "schema"})
            columns = _columns_for_table(schema_context, table)
            for column in columns:
                if not needle or column.casefold().startswith(needle):
                    suggestions.append({"kind": "column", "label": column, "insert_text": column, "detail": table})
        for keyword in _KEYWORDS:
            if not needle or keyword.casefold().startswith(needle):
                suggestions.append({"kind": "keyword", "label": keyword, "insert_text": keyword, "detail": "SQL"})

    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in suggestions:
        dedup[(item["kind"], item["label"], item["detail"])] = item
    items = list(dedup.values())[: max(1, min(int(limit), 200))]
    return {"prefix": prefix, "items": items, "count": len(items), "schema_aware": bool(schema_context)}


def _bounded_sql(sql: str, dialect: str | None, row_limit: int) -> str:
    trees = _parse(sql, dialect)
    if len(trees) != 1 or not _is_read(trees[0]):
        return sql
    tree = trees[0].copy()
    if isinstance(tree, exp.Query) and not tree.args.get("limit"):
        tree = tree.limit(row_limit + 1)
        return tree.sql(dialect=_read_dialect(dialect))
    return sql


def execute_sql(
    connector: DataPlatformConnector,
    sql: str,
    dialect: str | None = None,
    *,
    row_limit: int = 1000,
) -> dict[str, Any]:
    classification = classify_sql(sql, dialect)
    if classification["blocked"]:
        raise PermissionError("hard-denied SQL operation")
    if classification["query_type"] != "read":
        raise PermissionError("sql_execute is read-only; mutations require a separately approved Builder tool")
    bounded = _bounded_sql(sql, dialect, max(1, min(int(row_limit), 10000)))
    result = connector.execute_read(bounded)
    rows = list(result.rows)
    truncated = len(rows) > row_limit
    rows = rows[:row_limit]
    return {
        "status": "PASS",
        "platform": connector.platform,
        "query_type": "read",
        "rows": rows,
        "row_count": len(rows),
        "columns": list(result.columns),
        "query_id": result.query_id,
        "metadata": result.metadata,
        "row_limit": row_limit,
        "truncated": truncated,
    }


def explain_sql(connector: DataPlatformConnector, sql: str, dialect: str | None = None) -> dict[str, Any]:
    classification = classify_sql(sql, dialect)
    if classification["blocked"] or classification["query_type"] != "read":
        raise PermissionError("sql_explain only accepts read-only SQL")
    result = connector.dry_run_sql(sql)
    return {
        "status": "PASS" if result.valid else "FAIL",
        "platform": connector.platform,
        "valid": result.valid,
        "estimated_bytes": result.estimated_bytes,
        "estimated_cost": str(result.estimated_cost) if result.estimated_cost is not None else None,
        "warnings": list(result.warnings),
        "metadata": result.metadata,
    }
