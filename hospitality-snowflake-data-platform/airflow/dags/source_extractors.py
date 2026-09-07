"""Chunked DB-API extraction adapters for PostgreSQL and Oracle."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from job_catalog import IngestionJob


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"Unsupported source value type: {type(value).__name__}")


def _validated_identifier(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe source identifier: {identifier!r}")
    return identifier


def extract_query_to_jsonl(connection: Any, query: str, parameters: tuple[Any, ...], destination: Path) -> int:
    """Stream a DB-API cursor to JSONL without accumulating a result set."""
    cursor = connection.cursor()
    cursor.arraysize = 10_000
    cursor.execute(query, parameters)
    columns = [description[0] for description in cursor.description]
    row_count = 0
    with destination.open("w", encoding="utf-8") as handle:
        while rows := cursor.fetchmany(cursor.arraysize):
            for values in rows:
                handle.write(json.dumps(dict(zip(columns, values)), default=_json_default, separators=(",", ":")) + "\n")
                row_count += 1
    cursor.close()
    return row_count


def extract_entity(job: IngestionJob | dict[str, Any], entity: str, destination: Path, watermark: str | None) -> int:
    source = job.source if isinstance(job, IngestionJob) else job["source"]
    strategy = job.load_strategy if isinstance(job, IngestionJob) else job["load_strategy"]
    table = _validated_identifier(entity)
    if source == "postgres":
        from airflow.providers.postgres.hooks.postgres import PostgresHook

        connection = PostgresHook(postgres_conn_id="postgres_hospitality").get_conn()
        marker = "%s"
        updated_column = "source_updated_at"
    elif source == "oracle":
        from airflow.providers.oracle.hooks.oracle import OracleHook

        connection = OracleHook(oracle_conn_id="oracle_hospitality").get_conn()
        marker = ":1"
        updated_column = "SOURCE_UPDATED_AT"
    else:
        raise ValueError(f"No relational extractor for source {source!r}")
    try:
        if watermark and strategy in {"timestamp_incremental", "high_watermark"}:
            query = f"SELECT * FROM {table} WHERE {updated_column} > {marker} ORDER BY {updated_column}"
            parameters = (watermark,)
        else:
            query = f"SELECT * FROM {table}"
            parameters = ()
        return extract_query_to_jsonl(connection, query, parameters, destination)
    finally:
        connection.close()

