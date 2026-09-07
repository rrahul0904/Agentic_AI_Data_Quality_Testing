"""Source discovery and chunked PostgreSQL/Oracle extraction."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .metadata import normalize_job


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


def extract_entity(source: str, strategy: str, entity: str, destination: Path, watermark: str | None) -> int:
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


def extract(job: dict[str, Any], ti: Any, **_: Any) -> list[dict[str, Any]]:
    spec = normalize_job(job)
    batch = ti.xcom_pull(task_ids="create_batch")
    watermarks = ti.xcom_pull(task_ids="read_watermark") or {}
    batch_dir = Path(os.environ.get("LOCAL_LANDING_DIR", "/opt/airflow/data/landing")) / batch["batch_id"]
    extract_dir = batch_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=False)
    artifacts: list[dict[str, Any]] = []

    if spec["source"] == "files":
        generated = Path(os.environ.get("GENERATED_FILE_DIR", "/opt/airflow/sources/files/generated"))
        for entity in spec["entities"]:
            candidate = generated / entity
            if not candidate.is_file():
                raise FileNotFoundError(f"Required source feed is missing: {candidate}")
            artifacts.append({"entity": entity, "source_path": str(candidate)})
    else:
        source_mode = os.environ.get(f"{spec['source'].upper()}_MODE", "simulated").lower()
        if source_mode in {"database", "real"}:
            for entity in spec["entities"]:
                candidate = extract_dir / f"{entity}.jsonl"
                rows = extract_entity(
                    spec["source"], spec["load_strategy"], entity, candidate, watermarks.get(entity)
                )
                artifacts.append({"entity": entity, "source_path": str(candidate), "extracted_rows": rows})
        elif source_mode == "simulated":
            export_root = Path(os.environ.get("SOURCE_EXPORT_DIR", "/opt/airflow/data/source_exports"))
            for entity in spec["entities"]:
                candidate = export_root / spec["source"] / f"{entity}.jsonl"
                if not candidate.is_file():
                    raise FileNotFoundError(f"Expected {spec['source']} extract is missing: {candidate}")
                artifacts.append({"entity": entity, "source_path": str(candidate)})
        else:
            raise ValueError(f"Unsupported {spec['source']} extraction mode: {source_mode!r}")

    (extract_dir / "extract_manifest.json").write_text(
        json.dumps({"batch_id": batch["batch_id"], "job": spec, "artifacts": artifacts}, indent=2),
        encoding="utf-8",
    )
    return artifacts
