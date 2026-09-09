"""Declarative Snowflake Cortex AI-function workflow compiler and runner."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import sqlglot
from sqlglot import exp

from agentic_data_platform.connectors.snowflake import SnowflakeConnector
from agentic_data_platform.sql.safety import classify_mutation, validate_single_statement


_ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SUPPORTED = frozenset({"filter", "agg", "summarize-agg", "classify", "complete", "count-tokens"})


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _alias(value: str) -> str:
    text = str(value)
    if not _ALIAS.fullmatch(text):
        raise ValueError(f"invalid workflow alias: {text}")
    return text


def _expression(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("AI workflow expression is required")
    tree = sqlglot.parse_one(f"SELECT {text}", read="snowflake")
    if any(tree.find(kind) for kind in (exp.Subquery, exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter)):
        raise ValueError("AI workflow expressions may not contain subqueries or mutations")
    expressions = list(tree.expressions)
    if len(expressions) != 1:
        raise ValueError("AI workflow expression must contain exactly one expression")
    return expressions[0].sql(dialect="snowflake", pretty=False)


def _json_variant(value: Any) -> str:
    return f"PARSE_JSON({_literal(json.dumps(value, sort_keys=True, separators=(',', ':')))})"


def _categories(items: list[Any]) -> str:
    if not items:
        raise ValueError("AI_CLASSIFY requires at least one category")
    rendered = []
    for item in items:
        if isinstance(item, str):
            rendered.append(_literal(item))
        elif isinstance(item, dict):
            rendered.append(_json_variant(item))
        else:
            raise ValueError("AI_CLASSIFY categories must be strings or objects")
    return "ARRAY_CONSTRUCT(" + ", ".join(rendered) + ")"


@dataclass(frozen=True)
class CompiledAIWorkflow:
    name: str
    sql: str
    steps: tuple[dict[str, Any], ...]
    source_sql: str

    def public(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "name": self.name,
            "source_sql": self.source_sql,
            "step_count": len(self.steps),
            "steps": list(self.steps),
            "sql": self.sql,
        }


class AIWorkflowCompiler:
    def compile(self, workflow: dict[str, Any]) -> CompiledAIWorkflow:
        name = _alias(str(workflow.get("name") or "ai_workflow"))
        source_sql = str(workflow.get("source_sql") or "").strip().rstrip(";")
        if not source_sql:
            raise ValueError("AI workflow source_sql is required")
        if not validate_single_statement(source_sql) or classify_mutation(source_sql, "snowflake") != "read":
            raise ValueError("AI workflow source_sql must be one read-only Snowflake statement")

        raw_steps = list(workflow.get("steps") or [])
        if not raw_steps:
            raise ValueError("AI workflow requires at least one step")

        ctes = [f"step_0 AS ({source_sql})"]
        normalized: list[dict[str, Any]] = []
        previous = "step_0"

        for index, raw in enumerate(raw_steps, start=1):
            if not isinstance(raw, dict):
                raise ValueError("AI workflow steps must be objects")
            operation = str(raw.get("operation") or "").casefold()
            if operation not in _SUPPORTED:
                raise ValueError(f"unsupported AI workflow operation: {operation}")
            alias = _alias(str(raw.get("alias") or f"ai_step_{index}"))
            input_expr = _expression(str(raw.get("input") or ""))
            group_by = [_expression(str(item)) for item in raw.get("group_by") or []]
            current = f"step_{index}"

            if operation == "filter":
                prompt = str(raw.get("prompt") or "").strip()
                if prompt:
                    predicate = f"AI_FILTER(PROMPT({_literal(prompt)}, {input_expr}))"
                else:
                    predicate = f"AI_FILTER({input_expr})"
                sql = f"SELECT * FROM {previous} WHERE {predicate}"

            elif operation == "classify":
                categories = _categories(list(raw.get("categories") or []))
                config = raw.get("config")
                function = f"AI_CLASSIFY({input_expr}, {categories}"
                if config is not None:
                    function += f", {_json_variant(config)}"
                function += ")"
                sql = f"SELECT *, {function} AS {alias} FROM {previous}"

            elif operation == "complete":
                model = str(raw.get("model") or "").strip()
                if not model:
                    raise ValueError("AI_COMPLETE step requires model")
                function = f"AI_COMPLETE({_literal(model)}, {input_expr}"
                params = raw.get("model_parameters")
                response_format = raw.get("response_format")
                show_details = raw.get("show_details")
                if params is not None or response_format is not None or show_details is not None:
                    function += f", {_json_variant(params or {})}"
                    if response_format is not None or show_details is not None:
                        function += f", {_json_variant(response_format or {})}"
                        if show_details is not None:
                            function += f", {'TRUE' if bool(show_details) else 'FALSE'}"
                function += ")"
                sql = f"SELECT *, {function} AS {alias} FROM {previous}"

            elif operation == "count-tokens":
                function_name = str(raw.get("function_name") or "ai_complete").casefold()
                if not re.fullmatch(r"ai_[a-z_]+", function_name):
                    raise ValueError("AI_COUNT_TOKENS function_name must start with ai_ and use lowercase letters")
                model = raw.get("model")
                if model:
                    function = f"AI_COUNT_TOKENS({_literal(function_name)}, {_literal(str(model))}, {input_expr})"
                else:
                    function = f"AI_COUNT_TOKENS({_literal(function_name)}, {input_expr})"
                sql = f"SELECT *, {function} AS {alias} FROM {previous}"

            elif operation in {"agg", "summarize-agg"}:
                if operation == "agg":
                    instruction = str(raw.get("instruction") or "").strip()
                    if not instruction:
                        raise ValueError("AI_AGG step requires instruction")
                    function = f"AI_AGG({input_expr}, {_literal(instruction)})"
                else:
                    function = f"AI_SUMMARIZE_AGG({input_expr})"
                select_parts = [*group_by, f"{function} AS {alias}"]
                sql = f"SELECT {', '.join(select_parts)} FROM {previous}"
                if group_by:
                    sql += " GROUP BY " + ", ".join(group_by)
            else:
                raise AssertionError(operation)

            ctes.append(f"{current} AS ({sql})")
            normalized.append({
                "index": index,
                "operation": operation,
                "alias": alias,
                "input": input_expr,
                "group_by": group_by,
            })
            previous = current

        final_sql = "WITH " + ",\n".join(ctes) + f"\nSELECT * FROM {previous}"
        return CompiledAIWorkflow(name, final_sql, tuple(normalized), source_sql)


class SnowflakeAIWorkflowRunner:
    def __init__(self, connector: SnowflakeConnector) -> None:
        if not isinstance(connector, SnowflakeConnector):
            raise TypeError("SnowflakeAIWorkflowRunner requires SnowflakeConnector")
        self.connector = connector

    def run(self, workflow: dict[str, Any]) -> dict[str, Any]:
        compiled = AIWorkflowCompiler().compile(workflow)
        result = self.connector.execute_read(compiled.sql)
        return {
            **compiled.public(),
            "status": "PASS",
            "row_count": len(result.rows),
            "rows": [dict(row) for row in result.rows],
            "columns": list(result.columns),
            "query_id": result.query_id,
        }
