"""Scalable connector-based data diff with profile, join, hash and cascade algorithms."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from numbers import Number
from typing import Any, Iterable, Sequence

from agentic_data_platform.connectors.base import DataPlatformConnector
from agentic_data_platform.connectors.models import ColumnMetadata
from agentic_data_platform.quality.data_diff import row_diff


_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_NUMERIC = ("INT", "DECIMAL", "NUMERIC", "NUMBER", "REAL", "FLOAT", "DOUBLE")
_TEMPORAL = ("DATE", "TIME", "TIMESTAMP", "DATETIME")
_HEX = "0123456789abcdef"


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


def _is_temporal(column: ColumnMetadata) -> bool:
    upper = column.data_type.upper()
    return any(token in upper for token in _TEMPORAL)


def _is_string(column: ColumnMetadata) -> bool:
    upper = column.data_type.upper()
    return any(token in upper for token in ("CHAR", "TEXT", "STRING", "VARCHAR"))


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
        f"SELECT COUNT(*) AS __count, MIN({key}) AS __min, MAX({key}) AS __max, "
        f"SUM(CASE WHEN {key} IS NULL THEN 1 ELSE 0 END) AS __null_count "
        f"FROM {_safe_ref(table)}" + _where_clause(where)
    )
    row = result.rows[0]
    return {
        "count": int(_value(row, "__count", 0) or 0),
        "min": _value(row, "__min"),
        "max": _value(row, "__max"),
        "null_count": int(_value(row, "__null_count", 0) or 0),
    }


def _range_where(base: str | None, key: str, lower: Any, upper: Any, inclusive_upper: bool) -> str:
    parts = [base] if base else []
    operator = "<=" if inclusive_upper else "<"
    parts.append(f"{key} >= {_literal(lower)} AND {key} {operator} {_literal(upper)}")
    return " AND ".join(parts)


def _and_where(base: str | None, predicate: str) -> str:
    return " AND ".join(item for item in (base, predicate) if item)


def _count_rows(connector: DataPlatformConnector, table: str, where: str | None) -> int:
    result = connector.execute_read(
        f"SELECT COUNT(*) AS __count FROM {_safe_ref(table)}" + _where_clause(where)
    )
    return int(_value(result.rows[0], "__count", 0) or 0)


def _boundary(
    connector: DataPlatformConnector,
    table: str,
    key: str,
    where: str | None,
    offset: int,
) -> Any:
    base = f"SELECT {key} AS __boundary FROM {_safe_ref(table)}" + _where_clause(where)
    if connector.platform in {"sqlserver", "oracle"}:
        sql = base + f" ORDER BY {key} OFFSET {max(0, offset)} ROWS FETCH NEXT 1 ROWS ONLY"
    else:
        sql = base + f" ORDER BY {key} LIMIT 1 OFFSET {max(0, offset)}"
    rows = connector.execute_read(sql).rows
    return _value(rows[0], "__boundary") if rows else None


def _temporal_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _midpoint(lower: Any, upper: Any, *, temporal: bool) -> Any:
    if temporal:
        left, right = _temporal_value(lower), _temporal_value(upper)
        return left + (right - left) / 2
    return (lower + upper) / 2


def _numeric_hash_expression(platform: str, hash_expression: str, offset: int) -> str | None:
    part = f"SUBSTR({hash_expression}, {offset}, 8)"
    if platform == "bigquery":
        return f"CAST(CONCAT('0x', {part}) AS INT64)"
    if platform in {"mysql", "databricks"}:
        return f"CAST(CONV({part}, 16, 10) AS DECIMAL(20,0))"
    if platform == "trino":
        return f"from_base({part}, 16)"
    if platform in {"snowflake", "oracle"}:
        return f"TO_NUMBER({part}, 'XXXXXXXX')"
    if platform == "postgres":
        return f"(('x' || {part})::bit(32)::bigint)"
    if platform == "duckdb":
        return f"CAST(('0x' || {part}) AS UBIGINT)"
    return None


def _partition_signature(
    connector: DataPlatformConnector,
    table: str,
    key_columns: Sequence[str],
    compare_columns: Sequence[str],
    where: str | None,
) -> dict[str, Any]:
    columns = [*key_columns, *compare_columns]
    hash_expression = _row_hash_expression(connector.platform, columns)
    first = _numeric_hash_expression(connector.platform, hash_expression, 1)
    second = _numeric_hash_expression(connector.platform, hash_expression, 9)
    if first is None or second is None:
        return {
            "count": _count_rows(connector, table, where),
            "signature": None,
            "pushdown": False,
        }
    result = connector.execute_read(
        "SELECT COUNT(*) AS __count, "
        f"SUM({first}) AS __sum1, SUM({second}) AS __sum2 "
        f"FROM {_safe_ref(table)}" + _where_clause(where)
    )
    row = result.rows[0]
    return {
        "count": int(_value(row, "__count", 0) or 0),
        "signature": (
            str(_value(row, "__sum1", 0) or 0),
            str(_value(row, "__sum2", 0) or 0),
        ),
        "pushdown": True,
    }


def _hash_prefix_where(
    connector: DataPlatformConnector,
    keys: Sequence[str],
    prefix: str,
    base: str | None,
) -> str:
    expression = _row_hash_expression(connector.platform, keys)
    predicate = f"LOWER(SUBSTR({expression}, 1, {len(prefix)})) = {_literal(prefix)}"
    return _and_where(base, predicate)


def _partition_strategy(
    source_meta: Sequence[ColumnMetadata],
    target_meta: Sequence[ColumnMetadata],
    *,
    same_platform: bool,
    requested: str,
) -> str:
    requested = requested.upper()
    if requested != "AUTO":
        allowed = {"NUMERIC_RANGE", "TIMESTAMP_RANGE", "LEXICOGRAPHIC", "HASH_BUCKET", "COMPOUND_KEY"}
        if requested not in allowed:
            raise ValueError(f"unsupported partition strategy: {requested}")
        return requested
    if len(source_meta) > 1:
        return "COMPOUND_KEY"
    if _is_numeric(source_meta[0]) and _is_numeric(target_meta[0]):
        return "NUMERIC_RANGE"
    if _is_temporal(source_meta[0]) and _is_temporal(target_meta[0]):
        return "TIMESTAMP_RANGE"
    if _is_string(source_meta[0]) and _is_string(target_meta[0]) and same_platform:
        return "LEXICOGRAPHIC"
    return "HASH_BUCKET"


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
    partition_strategy: str = "AUTO",
) -> dict[str, Any]:
    """Partitioned cross-warehouse hash diff with pushdown-first elimination.

    Numeric/timestamp/string range predicates allow native pruning. Compound or
    cross-platform string keys use deterministic MD5 prefix buckets. Matching
    partitions are eliminated from aggregate signatures when the platform has a
    safe numeric-hash aggregate; row hashes move only for bounded mismatches.
    """

    keys, compare = _select_columns(
        source,
        target,
        source_table,
        target_table,
        key_columns,
        compare_columns,
        exclude_columns,
    )
    source_columns = _column_map(source, source_table)
    target_columns = _column_map(target, target_table)
    source_meta = [source_columns[key.casefold()] for key in keys]
    target_meta = [target_columns[key.casefold()] for key in keys]
    strategy = _partition_strategy(
        source_meta,
        target_meta,
        same_platform=source.platform == target.platform,
        requested=partition_strategy,
    )

    changed: list[Any] = []
    missing: list[Any] = []
    extra: list[Any] = []
    partitions = 0
    eliminated_partitions = 0
    hash_rows_retrieved = 0
    query_count = 0

    def signatures(part_where_source: str | None, part_where_target: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal query_count
        left = _partition_signature(source, source_table, keys, compare, part_where_source)
        right = _partition_signature(target, target_table, keys, compare, part_where_target)
        query_count += 2
        return left, right

    def compare_bounded(part_where_source: str | None, part_where_target: str | None) -> None:
        nonlocal hash_rows_retrieved, query_count
        left_rows = _hash_rows(source, source_table, keys, compare, part_where_source, max_partition_rows)
        right_rows = _hash_rows(target, target_table, keys, compare, part_where_target, max_partition_rows)
        query_count += 2
        hash_rows_retrieved += len(left_rows) + len(right_rows)
        left_map: dict[tuple[Any, ...], Counter[str]] = {}
        right_map: dict[tuple[Any, ...], Counter[str]] = {}
        for row in left_rows:
            item = tuple(_value(row, name) for name in keys)
            digest = str(_value(row, "__row_hash")).casefold()
            left_map.setdefault(item, Counter())[digest] += 1
        for row in right_rows:
            item = tuple(_value(row, name) for name in keys)
            digest = str(_value(row, "__row_hash")).casefold()
            right_map.setdefault(item, Counter())[digest] += 1
        left_keys, right_keys = set(left_map), set(right_map)
        missing.extend(sorted(left_keys - right_keys, key=str))
        extra.extend(sorted(right_keys - left_keys, key=str))
        changed.extend(
            sorted(
                (item for item in left_keys & right_keys if left_map[item] != right_map[item]),
                key=str,
            )
        )

    if strategy in {"NUMERIC_RANGE", "TIMESTAMP_RANGE", "LEXICOGRAPHIC"}:
        if len(keys) != 1:
            raise ValueError(f"{strategy} requires exactly one key column")
        key = keys[0]
        left_range = _key_range(source, source_table, key, where)
        right_range = _key_range(target, target_table, key, where)
        query_count += 2
        if left_range["count"] == right_range["count"] == 0:
            return {
                "algorithm": "HASH_DIFF",
                "status": "PASS",
                "partition_strategy": strategy,
                "changed_keys": [],
                "missing_keys": [],
                "extra_keys": [],
                "partitions": 0,
                "eliminated_partitions": 0,
                "raw_rows_retrieved": 0,
                "hash_rows_retrieved": 0,
                "rows_transferred": 0,
                "query_count": query_count,
            }

        if left_range["null_count"] or right_range["null_count"]:
            partitions += 1
            null_where = _and_where(where, f"{key} IS NULL")
            left_sig, right_sig = signatures(null_where, null_where)
            if left_sig["signature"] is not None and left_sig == right_sig:
                eliminated_partitions += 1
            else:
                largest = max(left_sig["count"], right_sig["count"])
                if largest > max_partition_rows:
                    raise RuntimeError(
                        f"HASH_DIFF cannot bound NULL-key partition below {largest} rows; "
                        "use a non-null unique key or increase max_partition_rows"
                    )
                compare_bounded(null_where, null_where)

        minima = [value for value in (left_range["min"], right_range["min"]) if value is not None]
        maxima = [value for value in (left_range["max"], right_range["max"]) if value is not None]
        stack: list[tuple[Any, Any, int, bool]] = []
        if minima and maxima:
            stack.append((min(minima), max(maxima), 0, True))
        temporal = strategy == "TIMESTAMP_RANGE"

        while stack:
            part_lower, part_upper, depth, inclusive_upper = stack.pop()
            partitions += 1
            part_where = _range_where(where, key, part_lower, part_upper, inclusive_upper)
            left_sig, right_sig = signatures(part_where, part_where)
            if (
                left_sig["signature"] is not None
                and left_sig == right_sig
            ):
                eliminated_partitions += 1
                continue
            largest = max(left_sig["count"], right_sig["count"])
            if largest <= max_partition_rows:
                compare_bounded(part_where, part_where)
                continue
            if depth >= max_depth or part_lower == part_upper:
                raise RuntimeError(
                    f"HASH_DIFF cannot bound {strategy} partition below {largest} rows at depth={depth}"
                )

            if strategy == "LEXICOGRAPHIC":
                chosen_connector = source if left_sig["count"] >= right_sig["count"] else target
                chosen_table = source_table if chosen_connector is source else target_table
                boundary = _boundary(
                    chosen_connector,
                    chosen_table,
                    key,
                    part_where,
                    largest // 2,
                )
                query_count += 1
                if boundary is None or boundary in {part_lower, part_upper}:
                    raise RuntimeError(
                        "LEXICOGRAPHIC partition could not find a progressing warehouse boundary; "
                        "use HASH_BUCKET for highly duplicated/skewed string keys"
                    )
                midpoint = boundary
            else:
                midpoint = _midpoint(part_lower, part_upper, temporal=temporal)
                if midpoint == part_lower or midpoint == part_upper:
                    raise RuntimeError(f"{strategy} partition midpoint stopped progressing")

            stack.append((midpoint, part_upper, depth + 1, inclusive_upper))
            stack.append((part_lower, midpoint, depth + 1, False))
    else:
        stack: list[tuple[str, int]] = [("", 0)]
        while stack:
            prefix, depth = stack.pop()
            partitions += 1
            if prefix:
                left_where = _hash_prefix_where(source, keys, prefix, where)
                right_where = _hash_prefix_where(target, keys, prefix, where)
            else:
                left_where = right_where = where
            left_sig, right_sig = signatures(left_where, right_where)
            if (
                left_sig["signature"] is not None
                and left_sig == right_sig
            ):
                eliminated_partitions += 1
                continue
            largest = max(left_sig["count"], right_sig["count"])
            if largest <= max_partition_rows:
                compare_bounded(left_where, right_where)
                continue
            if depth >= min(max_depth, 6):
                raise RuntimeError(
                    f"HASH_BUCKET cannot bound a skewed partition below {largest} rows at prefix={prefix!r}"
                )
            stack.extend((prefix + char, depth + 1) for char in reversed(_HEX))

    changed = sorted(set(changed), key=str)
    missing = sorted(set(missing), key=str)
    extra = sorted(set(extra), key=str)
    detail_keys = [*changed, *missing, *extra][:detail_limit]
    return {
        "algorithm": "HASH_DIFF",
        "status": "PASS" if not (changed or missing or extra) else "FAIL",
        "partition_strategy": strategy,
        "key_columns": keys,
        "compare_columns": compare,
        "changed_keys": [list(item) for item in changed],
        "missing_keys": [list(item) for item in missing],
        "extra_keys": [list(item) for item in extra],
        "detail_keys": [list(item) for item in detail_keys],
        "detail_truncated": len(changed) + len(missing) + len(extra) > detail_limit,
        "partitions": partitions,
        "eliminated_partitions": eliminated_partitions,
        "max_partition_rows": max_partition_rows,
        "raw_rows_retrieved": 0,
        "hash_rows_retrieved": hash_rows_retrieved,
        "rows_transferred": hash_rows_retrieved,
        "query_count": query_count,
        "warehouse_pushdown": True,
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
        join = " AND ".join(
            f"(s.{key} = t.{key} OR (s.{key} IS NULL AND t.{key} IS NULL))"
            for key in keys
        )
        mismatch_terms = []
        for column in compare:
            mismatch_terms.append(
                f"(s.{column} <> t.{column} OR (s.{column} IS NULL AND t.{column} IS NOT NULL) "
                f"OR (s.{column} IS NOT NULL AND t.{column} IS NULL))"
            )
        missing_test = "t.__target_present IS NULL"
        extra_test = "s.__source_present IS NULL"
        changed_test = " OR ".join(mismatch_terms) if mismatch_terms else "FALSE"
        source_where = _where_clause(where)
        target_where = _where_clause(where)
        source_query = f"(SELECT *, 1 AS __source_present FROM {_safe_ref(source_table)}{source_where})"
        target_query = f"(SELECT *, 1 AS __target_present FROM {_safe_ref(target_table)}{target_where})"
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
        source_columns = _column_map(self.source, source_table)
        target_columns = _column_map(self.target, target_table)
        source_meta = [source_columns[key.casefold()] for key in keys]
        target_meta = [target_columns[key.casefold()] for key in keys]
        partition_strategy = _partition_strategy(
            source_meta,
            target_meta,
            same_platform=self.source.platform == self.target.platform,
            requested="AUTO",
        )
        return {
            "algorithm": algorithm,
            "source_platform": self.source.platform,
            "target_platform": self.target.platform,
            "source_table": _safe_ref(source_table),
            "target_table": _safe_ref(target_table),
            "key_columns": keys,
            "compare_columns": compare,
            "partition_strategy": partition_strategy,
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
