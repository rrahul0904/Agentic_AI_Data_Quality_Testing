"""Scalable connector-based data diff with profile, join, hash and cascade algorithms."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from numbers import Number
from typing import Any, Iterable, Sequence

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.models import ColumnMetadata
from agentic_data_platform.quality.data_diff import row_diff


_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_NUMERIC = ("INT", "DECIMAL", "NUMERIC", "NUMBER", "REAL", "FLOAT", "DOUBLE")


def _safe_ref(value: str) -> str:
    if not _REF.fullmatch(value):
        raise ValueError(f"unsafe table reference: {value!r}")
    return value


def _safe_column(value: str) -> str:
    if not _COLUMN.fullmatch(value):
        raise ValueError(f"unsafe column reference: {value!r}")
    return value


def _parts(table: str) -> tuple[str, str]:
    parts = _safe_ref(table).split(".")
    if len(parts) < 2:
        raise ValueError("table reference must include schema.table")
    return parts[-2], parts[-1]


def _value(row: dict[str, Any], name: str, default: Any = None) -> Any:
    wanted = name.casefold()
    for key, value in row.items():
        if str(key).casefold() == wanted:
            return value
    return default


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Number):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise ValueError("non-finite numeric literal is not supported")
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _is_numeric(column: ColumnMetadata) -> bool:
    upper = column.data_type.upper()
    return any(token in upper for token in _NUMERIC)


def _metadata(connector: DataPlatformConnector, table: str) -> tuple[ColumnMetadata, ...]:
    schema, name = _parts(table)
    return connector.describe_table(schema, name).columns


def _column_map(connector: DataPlatformConnector, table: str) -> dict[str, ColumnMetadata]:
    return {column.name.casefold(): column for column in _metadata(connector, table)}


def _select_columns(
    source: DataPlatformConnector,
    target: DataPlatformConnector,
    source_table: str,
    target_table: str,
    keys: Sequence[str],
    compare_columns: Sequence[str] | None,
    exclude_columns: Iterable[str],
) -> tuple[list[str], list[str]]:
    source_columns = _column_map(source, source_table)
    target_columns = _column_map(target, target_table)
    excluded = {item.casefold() for item in exclude_columns}
    key_names = [_safe_column(item) for item in keys]
    for key in key_names:
        if key.casefold() not in source_columns or key.casefold() not in target_columns:
            raise KeyError(f"key column missing from source or target: {key}")

    if compare_columns:
        compare = [_safe_column(item) for item in compare_columns]
    else:
        compare = sorted(
            source_columns.keys() & target_columns.keys() - excluded - {item.casefold() for item in key_names}
        )
        compare = [source_columns[name].name for name in compare]

    missing = [
        column
        for column in compare
        if column.casefold() not in source_columns or column.casefold() not in target_columns
    ]
    if missing:
        raise KeyError(f"compare columns missing from source or target: {', '.join(missing)}")
    return key_names, compare


def _where_clause(where: str | None) -> str:
    if not where:
        return ""
    if ";" in where or "--" in where or "/*" in where:
        raise ValueError("unsafe diff WHERE clause")
    return " WHERE " + where


def profile_table(
    connector: DataPlatformConnector,
    table: str,
    *,
    columns: Sequence[str] | None = None,
    where: str | None = None,
) -> dict[str, Any]:
    table = _safe_ref(table)
    metadata = _column_map(connector, table)
    selected = (
        [_safe_column(item) for item in columns]
        if columns
        else [column.name for column in metadata.values()]
    )
    expressions = ["COUNT(*) AS __row_count"]
    aliases: list[tuple[str, str, str]] = []
    for index, name in enumerate(selected):
        column = metadata.get(name.casefold())
        if column is None:
            raise KeyError(f"column not found: {name}")
        null_alias = f"__c{index}_null"
        distinct_alias = f"__c{index}_distinct"
        min_alias = f"__c{index}_min"
        max_alias = f"__c{index}_max"
        expressions.extend(
            [
                f"SUM(CASE WHEN {name} IS NULL THEN 1 ELSE 0 END) AS {null_alias}",
                f"COUNT(DISTINCT {name}) AS {distinct_alias}",
                f"MIN({name}) AS {min_alias}",
                f"MAX({name}) AS {max_alias}",
            ]
        )
        aliases.extend(
            [
                (name, "null_count", null_alias),
                (name, "distinct_count", distinct_alias),
                (name, "min", min_alias),
                (name, "max", max_alias),
            ]
        )
        if _is_numeric(column):
            sum_alias = f"__c{index}_sum"
            avg_alias = f"__c{index}_avg"
            expressions.extend([f"SUM({name}) AS {sum_alias}", f"AVG({name}) AS {avg_alias}"])
            aliases.extend([(name, "sum", sum_alias), (name, "avg", avg_alias)])

    result = connector.execute_read(
        "SELECT " + ", ".join(expressions) + f" FROM {table}" + _where_clause(where)
    )
    if not result.rows:
        raise RuntimeError("profile query returned no aggregate row")
    row = result.rows[0]
    profiles: dict[str, dict[str, Any]] = {name: {} for name in selected}
    for name, metric, alias in aliases:
        profiles[name][metric] = _value(row, alias)
    return {
        "platform": connector.platform,
        "table": table,
        "row_count": int(_value(row, "__row_count", 0) or 0),
        "columns": profiles,
        "raw_rows_retrieved": 0,
    }


def profile_diff(
    source: DataPlatformConnector,
    target: DataPlatformConnector,
    source_table: str,
    target_table: str,
    *,
    columns: Sequence[str] | None = None,
    where: str | None = None,
    numeric_tolerance: float = 0.0,
) -> dict[str, Any]:
    left = profile_table(source, source_table, columns=columns, where=where)
    right = profile_table(target, target_table, columns=columns, where=where)
    differences: list[dict[str, Any]] = []
    if left["row_count"] != right["row_count"]:
        differences.append(
            {
                "metric": "row_count",
                "source": left["row_count"],
                "target": right["row_count"],
            }
        )
    for column in sorted(set(left["columns"]) | set(right["columns"])):
        l_metrics = left["columns"].get(column, {})
        r_metrics = right["columns"].get(column, {})
        for metric in sorted(set(l_metrics) | set(r_metrics)):
            l_value = l_metrics.get(metric)
            r_value = r_metrics.get(metric)
            same = l_value == r_value
            if isinstance(l_value, Number) and isinstance(r_value, Number):
                same = abs(float(l_value) - float(r_value)) <= numeric_tolerance
            if not same:
                differences.append(
                    {
                        "column": column,
                        "metric": metric,
                        "source": l_value,
                        "target": r_value,
                    }
                )
    return {
        "algorithm": "PROFILE",
        "status": "PASS" if not differences else "FAIL",
        "source": left,
        "target": right,
        "differences": differences,
        "pii_safe": True,
    }


def _cast_text(platform: str, column: str) -> str:
    if platform == "bigquery":
        return f"CAST({column} AS STRING)"
    if platform == "clickhouse":
        return f"toString({column})"
    if platform == "sqlserver":
        return f"CAST({column} AS VARCHAR(MAX))"
    if platform == "oracle":
        return f"CAST({column} AS VARCHAR2(4000))"
    return f"CAST({column} AS VARCHAR)"


def _concat(platform: str, expressions: Sequence[str]) -> str:
    values = [f"COALESCE({item}, '<NULL>')" for item in expressions]
    if platform == "bigquery":
        pieces = []
        for index, item in enumerate(values):
            if index:
                pieces.append("'|'")
            pieces.append(item)
        return "CONCAT(" + ", ".join(pieces) + ")"
    if platform == "clickhouse":
        return "concatWithSeparator('|', " + ", ".join(values) + ")"
    if platform == "oracle":
        return " || '|' || ".join(values)
    return "CONCAT_WS('|', " + ", ".join(values) + ")"


def _row_hash_expression(platform: str, columns: Sequence[str]) -> str:
    concat = _concat(platform, [_cast_text(platform, column) for column in columns])
    if platform == "bigquery":
        return f"TO_HEX(MD5({concat}))"
    if platform == "clickhouse":
        return f"hex(MD5({concat}))"
    if platform == "sqlserver":
        return f"CONVERT(VARCHAR(32), HASHBYTES('MD5', {concat}), 2)"
    if platform == "oracle":
        return f"STANDARD_HASH({concat}, 'MD5')"
    return f"MD5({concat})"


def _key_range(
    connector: DataPlatformConnector,
    table: str,
    key: str,
    where: str | None,
) -> dict[str, Any]:
    result = connector.execute_read(
        f"SELECT COUNT(*) AS __count, MIN({key}) AS __min, MAX({key}) AS __max "
        f"FROM {_safe_ref(table)}" + _where_clause(where)
    )
    row = result.rows[0]
    return {
        "count": int(_value(row, "__count", 0) or 0),
        "min": _value(row, "__min"),
        "max": _value(row, "__max"),
    }


def _range_where(base: str | None, key: str, lower: Number, upper: Number, inclusive_upper: bool) -> str:
    parts = [base] if base else []
    operator = "<=" if inclusive_upper else "<"
    parts.append(f"{key} >= {_literal(lower)} AND {key} {operator} {_literal(upper)}")
    return " AND ".join(parts)


def _hash_rows(
    connector: DataPlatformConnector,
    table: str,
    key_columns: Sequence[str],
    compare_columns: Sequence[str],
    where: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    columns = [*key_columns, *compare_columns]
    hash_expr = _row_hash_expression(connector.platform, columns)
    sql = (
        "SELECT "
        + ", ".join(key_columns)
        + f", {hash_expr} AS __row_hash FROM {_safe_ref(table)}"
        + _where_clause(where)
        + " ORDER BY "
        + ", ".join(key_columns)
        + f" LIMIT {limit + 1}"
    )
    rows = list(connector.execute_read(sql).rows)
    if len(rows) > limit:
        raise RuntimeError(f"hash partition exceeded bounded limit={limit}")
    return rows


def hash_diff(
    source: DataPlatformConnector,
    target: DataPlatformConnector,
    source_table: str,
    target_table: str,
    *,
    key_columns: Sequence[str],
    compare_columns: Sequence[str] | None = None,
    exclude_columns: Sequence[str] = (),
    where: str | None = None,
    max_partition_rows: int = 50000,
    max_depth: int = 24,
    detail_limit: int = 100,
) -> dict[str, Any]:
    keys, compare = _select_columns(
        source,
        target,
        source_table,
        target_table,
        key_columns,
        compare_columns,
        exclude_columns,
    )
    if len(keys) != 1:
        raise ValueError("partitioned HASH_DIFF currently requires exactly one numeric key column")
    key = keys[0]
    source_meta = _column_map(source, source_table)[key.casefold()]
    target_meta = _column_map(target, target_table)[key.casefold()]
    if not (_is_numeric(source_meta) and _is_numeric(target_meta)):
        raise ValueError("partitioned HASH_DIFF currently requires a numeric key")

    left_range = _key_range(source, source_table, key, where)
    right_range = _key_range(target, target_table, key, where)
    if left_range["count"] == right_range["count"] == 0:
        return {
            "algorithm": "HASH_DIFF",
            "status": "PASS",
            "changed_keys": [],
            "missing_keys": [],
            "extra_keys": [],
            "partitions": 0,
            "raw_rows_retrieved": 0,
        }

    minima = [value for value in (left_range["min"], right_range["min"]) if value is not None]
    maxima = [value for value in (left_range["max"], right_range["max"]) if value is not None]
    lower = min(minima)
    upper = max(maxima)
    stack: list[tuple[Number, Number, int, bool]] = [(lower, upper, 0, True)]
    changed: list[Any] = []
    missing: list[Any] = []
    extra: list[Any] = []
    partitions = 0

    while stack:
        part_lower, part_upper, depth, inclusive_upper = stack.pop()
        partitions += 1
        part_where = _range_where(where, key, part_lower, part_upper, inclusive_upper)
        left_count = _key_range(source, source_table, key, part_where)["count"]
        right_count = _key_range(target, target_table, key, part_where)["count"]
        largest = max(left_count, right_count)
        if largest > max_partition_rows:
            if depth >= max_depth or part_lower == part_upper:
                raise RuntimeError(
                    f"HASH_DIFF cannot bound partition below {largest} rows at depth={depth}"
                )
            midpoint = (part_lower + part_upper) / 2
            if midpoint == part_lower or midpoint == part_upper:
                raise RuntimeError("HASH_DIFF partition midpoint stopped progressing")
            stack.append((midpoint, part_upper, depth + 1, inclusive_upper))
            stack.append((part_lower, midpoint, depth + 1, False))
            continue

        left_rows = _hash_rows(
            source,
            source_table,
            keys,
            compare,
            part_where,
            max_partition_rows,
        )
        right_rows = _hash_rows(
            target,
            target_table,
            keys,
            compare,
            part_where,
            max_partition_rows,
        )
        left_map = {tuple(_value(row, item) for item in keys): _value(row, "__row_hash") for row in left_rows}
        right_map = {tuple(_value(row, item) for item in keys): _value(row, "__row_hash") for row in right_rows}
        left_keys = set(left_map)
        right_keys = set(right_map)
        missing.extend(sorted(left_keys - right_keys, key=str))
        extra.extend(sorted(right_keys - left_keys, key=str))
        changed.extend(
            sorted(
                (item for item in left_keys & right_keys if left_map[item] != right_map[item]),
                key=str,
            )
        )

    detail_keys = [*changed, *missing, *extra][:detail_limit]
    return {
        "algorithm": "HASH_DIFF",
        "status": "PASS" if not (changed or missing or extra) else "FAIL",
        "key_columns": keys,
        "compare_columns": compare,
        "changed_keys": [list(item) for item in changed],
        "missing_keys": [list(item) for item in missing],
        "extra_keys": [list(item) for item in extra],
        "detail_keys": [list(item) for item in detail_keys],
        "detail_truncated": len(changed) + len(missing) + len(extra) > detail_limit,
        "partitions": partitions,
        "max_partition_rows": max_partition_rows,
        "raw_rows_retrieved": 0,
        "hash_rows_retrieved": left_range["count"] + right_range["count"],
    }


def _bounded_rows(
    connector: DataPlatformConnector,
    table: str,
    columns: Sequence[str],
    where: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = list(
        connector.execute_read(
            "SELECT "
            + ", ".join(columns)
            + f" FROM {_safe_ref(table)}"
            + _where_clause(where)
            + f" LIMIT {limit + 1}"
        ).rows
    )
    if len(rows) > limit:
        raise RuntimeError(f"JOIN_DIFF cross-warehouse fallback exceeds row_sample_limit={limit}")
    return rows


def join_diff(
    source: DataPlatformConnector,
    target: DataPlatformConnector,
    source_table: str,
    target_table: str,
    *,
    key_columns: Sequence[str],
    compare_columns: Sequence[str] | None = None,
    exclude_columns: Sequence[str] = (),
    where: str | None = None,
    row_sample_limit: int = 10000,
) -> dict[str, Any]:
    keys, compare = _select_columns(
        source,
        target,
        source_table,
        target_table,
        key_columns,
        compare_columns,
        exclude_columns,
    )
    columns = [*keys, *compare]

    if source is target:
        join = " AND ".join(f"s.{key} = t.{key}" for key in keys)
        mismatch_terms = []
        for column in compare:
            mismatch_terms.append(
                f"(s.{column} <> t.{column} OR (s.{column} IS NULL AND t.{column} IS NOT NULL) "
                f"OR (s.{column} IS NOT NULL AND t.{column} IS NULL))"
            )
        missing_test = f"t.{keys[0]} IS NULL"
        extra_test = f"s.{keys[0]} IS NULL"
        changed_test = " OR ".join(mismatch_terms) if mismatch_terms else "FALSE"
        source_where = _where_clause(where)
        target_where = _where_clause(where)
        source_query = f"(SELECT * FROM {_safe_ref(source_table)}{source_where})"
        target_query = f"(SELECT * FROM {_safe_ref(target_table)}{target_where})"
        selected_keys = ", ".join(f"COALESCE(s.{key}, t.{key}) AS {key}" for key in keys)
        sql = (
            f"SELECT {selected_keys}, CASE WHEN {missing_test} THEN 'MISSING' "
            f"WHEN {extra_test} THEN 'EXTRA' WHEN ({changed_test}) THEN 'CHANGED' ELSE 'MATCH' END AS __status "
            f"FROM {source_query} s FULL OUTER JOIN {target_query} t ON {join} "
            f"WHERE {missing_test} OR {extra_test} OR ({changed_test}) "
            f"LIMIT {row_sample_limit + 1}"
        )
        rows = list(source.execute_read(sql).rows)
        if len(rows) > row_sample_limit:
            rows = rows[:row_sample_limit]
            truncated = True
        else:
            truncated = False
        counts = {"missing": 0, "extra": 0, "changed": 0}
        for row in rows:
            status = str(_value(row, "__status", "")).casefold()
            if status in counts:
                counts[status] += 1
        return {
            "algorithm": "JOIN_DIFF",
            "status": "PASS" if not rows else "FAIL",
            "execution": "WAREHOUSE_PUSHDOWN",
            "differences": rows,
            "counts": counts,
            "truncated": truncated,
            "raw_rows_retrieved": len(rows),
        }

    left = _bounded_rows(source, source_table, columns, where, row_sample_limit)
    right = _bounded_rows(target, target_table, columns, where, row_sample_limit)
    result = row_diff(left, right, keys, compare_columns=compare)
    return {
        "algorithm": "JOIN_DIFF",
        "execution": "BOUNDED_CROSS_WAREHOUSE_FALLBACK",
        **result,
        "raw_rows_retrieved": len(left) + len(right),
        "row_sample_limit": row_sample_limit,
    }


@dataclass
class WarehouseDiffEngine:
    source: DataPlatformConnector
    target: DataPlatformConnector

    def plan(
        self,
        source_table: str,
        target_table: str,
        *,
        key_columns: Sequence[str],
        compare_columns: Sequence[str] | None = None,
        exclude_columns: Sequence[str] = (),
    ) -> dict[str, Any]:
        keys, compare = _select_columns(
            self.source,
            self.target,
            source_table,
            target_table,
            key_columns,
            compare_columns,
            exclude_columns,
        )
        algorithm = "JOIN_DIFF" if self.source is self.target else "CASCADE"
        return {
            "algorithm": algorithm,
            "source_platform": self.source.platform,
            "target_platform": self.target.platform,
            "source_table": _safe_ref(source_table),
            "target_table": _safe_ref(target_table),
            "key_columns": keys,
            "compare_columns": compare,
            "reason": (
                "same connector can push FULL OUTER JOIN"
                if algorithm == "JOIN_DIFF"
                else "cross-warehouse comparison starts with PII-safe PROFILE then bounded HASH_DIFF"
            ),
        }

    def profile(self, source_table: str, target_table: str, **kwargs: Any) -> dict[str, Any]:
        return profile_diff(self.source, self.target, source_table, target_table, **kwargs)

    def join(self, source_table: str, target_table: str, **kwargs: Any) -> dict[str, Any]:
        return join_diff(self.source, self.target, source_table, target_table, **kwargs)

    def hash(self, source_table: str, target_table: str, **kwargs: Any) -> dict[str, Any]:
        return hash_diff(self.source, self.target, source_table, target_table, **kwargs)

    def cascade(
        self,
        source_table: str,
        target_table: str,
        *,
        key_columns: Sequence[str],
        compare_columns: Sequence[str] | None = None,
        exclude_columns: Sequence[str] = (),
        where: str | None = None,
        numeric_tolerance: float = 0.0,
        max_partition_rows: int = 50000,
        detail_limit: int = 100,
    ) -> dict[str, Any]:
        profile = self.profile(
            source_table,
            target_table,
            columns=[*key_columns, *(compare_columns or ())] if compare_columns else None,
            where=where,
            numeric_tolerance=numeric_tolerance,
        )
        if profile["status"] == "PASS":
            return {
                "algorithm": "CASCADE",
                "status": "PASS",
                "profile": profile,
                "hash": None,
                "detail": None,
                "raw_rows_retrieved": 0,
            }
        hashed = self.hash(
            source_table,
            target_table,
            key_columns=key_columns,
            compare_columns=compare_columns,
            exclude_columns=exclude_columns,
            where=where,
            max_partition_rows=max_partition_rows,
            detail_limit=detail_limit,
        )
        detail = None
        if hashed["status"] == "FAIL" and self.source is self.target:
            detail = self.join(
                source_table,
                target_table,
                key_columns=key_columns,
                compare_columns=compare_columns,
                exclude_columns=exclude_columns,
                where=where,
                row_sample_limit=detail_limit,
            )
        return {
            "algorithm": "CASCADE",
            "status": hashed["status"],
            "profile": profile,
            "hash": hashed,
            "detail": detail,
            "raw_rows_retrieved": detail.get("raw_rows_retrieved", 0) if detail else 0,
        }

    def auto(self, source_table: str, target_table: str, **kwargs: Any) -> dict[str, Any]:
        plan = self.plan(
            source_table,
            target_table,
            key_columns=kwargs["key_columns"],
            compare_columns=kwargs.get("compare_columns"),
            exclude_columns=kwargs.get("exclude_columns", ()),
        )
        if plan["algorithm"] == "JOIN_DIFF":
            return self.join(source_table, target_table, **kwargs)
        return self.cascade(source_table, target_table, **kwargs)
