"""Small deterministic parity utilities shared by tool surfaces."""

from __future__ import annotations

from typing import Any


def validate_warehouse_name(warehouse: Any) -> str | None:
    if warehouse is None:
        return None
    if not isinstance(warehouse, str):
        return "warehouse must be a string"
    trimmed = warehouse.strip()
    if not trimmed:
        return (
            "warehouse is an empty string — omit it to use the default warehouse "
            "or pass a configured connection name"
        )
    if trimmed[0] in "?$:@":
        return (
            f"warehouse name looks like an unsubstituted placeholder ({trimmed!r}); "
            "use warehouse_list to inspect configured connections"
        )
    return None


def validate_table_name(table: Any) -> str | None:
    if not isinstance(table, str) or not table.strip():
        return "table is required — pass a table name, optionally schema-qualified"
    trimmed = table.strip()
    if trimmed[0] in "?$:@":
        return f"table name looks like an unsubstituted placeholder ({trimmed!r})"
    return None


def normalize_error(value: Any) -> str | None:
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, str):
        return value
    if value in (None, False, 0):
        return None
    if isinstance(value, dict):
        for key in ("message", "error", "detail"):
            if isinstance(value.get(key), str):
                return str(value[key])
        return "Error details unavailable."
    return str(value)


class PostConnectSuggestions:
    def __init__(self) -> None:
        self._shown: set[str] = set()

    def reset(self) -> None:
        self._shown.clear()

    def post_connect(
        self,
        *,
        warehouse_type: str,
        schema_indexed: bool,
        dbt_detected: bool,
        connection_count: int,
    ) -> list[str]:
        suggestions: list[str] = []
        if not schema_indexed:
            suggestions.append(
                "Index your schema with schema_index to enable analysis, lineage, and quality checks."
            )
        is_mongo = warehouse_type.casefold() in {"mongo", "mongodb"}
        if not is_mongo:
            suggestions.append(
                f"Run SQL against {warehouse_type} with sql_execute."
            )
            suggestions.append(
                "Analyze SQL quality and optimization opportunities with sql_analyze."
            )
        if dbt_detected:
            suggestions.append(
                "dbt detected — use dbt-develop or dbt-troubleshoot workflows."
            )
        suggestions.append("Trace data flow with lineage_check.")
        suggestions.append("Audit sensitive data exposure with schema_detect_pii.")
        if int(connection_count) > 1:
            suggestions.append("Compare warehouses with data_diff.")
        return suggestions

    def progressive(self, last_tool_used: str) -> str | None:
        progression = {
            "sql_execute": (
                "Tip: use sql_analyze to check this query for correctness, "
                "performance, and best practices."
            ),
            "sql_analyze": (
                "Tip: use schema_inspect to explore referenced tables and columns."
            ),
            "schema_inspect": (
                "Tip: use lineage_check to inspect how this data flows."
            ),
            "schema_index": (
                "Schema indexed: sql_analyze, schema_inspect, and lineage_check "
                "are now schema-aware."
            ),
        }
        suggestion = progression.get(last_tool_used)
        if not suggestion or last_tool_used in self._shown:
            return None
        self._shown.add(last_tool_used)
        return suggestion
