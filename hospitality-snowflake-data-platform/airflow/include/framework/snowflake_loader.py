"""Snowflake staging/COPY implementation with an explicit local simulation path."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from include.configs.file_schemas import csv_payload_expression

from .audit import execution_mode
from .metadata import normalize_job


def _literal(value: str) -> str:
    return value.replace("'", "''")


def stage(job: dict[str, Any], ti: Any, **_: Any) -> dict[str, Any]:
    spec = normalize_job(job)
    batch = ti.xcom_pull(task_ids="create_batch")
    validation = ti.xcom_pull(task_ids="validate")
    if execution_mode() == "local":
        return {"mode": "local", "batch_id": batch["batch_id"], "artifacts": validation["artifacts"]}

    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    hook = SnowflakeHook(snowflake_conn_id="snowflake_hospitality")
    staged = []
    for artifact in validation["artifacts"]:
        path = Path(artifact["landed_path"])
        stage_prefix = f"{spec['source']}/{batch['batch_id']}/{path.name}"
        hook.run(
            f"PUT 'file://{_literal(str(path))}' "
            f"@HOSPITALITY_DW.RAW.RAW_INGESTION_STAGE/{_literal(stage_prefix)} "
            "AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        staged.append({**artifact, "stage_prefix": stage_prefix})
    return {"mode": "snowflake", "batch_id": batch["batch_id"], "artifacts": staged}


def _copy_expressions(source: str, entity: str, suffix: str) -> tuple[str, str, str, str, str]:
    if suffix in {".json", ".jsonl"}:
        file_format, payload = "HOSPITALITY_DW.RAW.FF_JSON", "$1"
    elif suffix == ".parquet":
        file_format, payload = "HOSPITALITY_DW.RAW.FF_PARQUET", "$1"
    else:
        file_format, payload = "HOSPITALITY_DW.RAW.FF_CSV", csv_payload_expression(entity)

    if source == "oracle":
        pk = f'$1:"{_literal(entity)}_ID"::varchar'
        created = "$1:SOURCE_CREATED_AT::timestamp_tz"
        updated = "$1:SOURCE_UPDATED_AT::timestamp_tz"
        deleted = "coalesce($1:IS_DELETED::boolean, false)"
    elif source == "postgres":
        pk = f'$1:"{_literal(entity)}_id"::varchar'
        created = "$1:source_created_at::timestamp_tz"
        updated = "$1:source_updated_at::timestamp_tz"
        deleted = "coalesce($1:is_deleted::boolean, false)"
    else:
        pk, created, updated, deleted = "NULL", "NULL", "NULL", "FALSE"
    return file_format, payload, pk, created, updated, deleted


def _copy_live(spec: dict[str, Any], batch: dict[str, Any], staged: dict[str, Any]) -> list[dict[str, Any]]:
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    hook = SnowflakeHook(snowflake_conn_id="snowflake_hospitality")
    loads = []
    for artifact in staged["artifacts"]:
        path = Path(artifact["landed_path"])
        entity = artifact["entity"]
        file_format, payload, pk, created, updated, deleted = _copy_expressions(
            spec["source"], entity, path.suffix.lower()
        )
        hook.run(
            f"""
            COPY INTO HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS
              (RAW_RECORD_ID, SOURCE_SYSTEM, SOURCE_TABLE, SOURCE_FILE_NAME, SOURCE_PRIMARY_KEY,
               INGESTION_BATCH_ID, INGESTED_AT, SOURCE_CREATED_AT, SOURCE_UPDATED_AT,
               RECORD_HASH, RAW_PAYLOAD, IS_DELETED)
            FROM (
              SELECT UUID_STRING(), '{_literal(spec['source'])}', '{_literal(entity)}', METADATA$FILENAME, {pk},
                     '{_literal(batch['batch_id'])}', CURRENT_TIMESTAMP(), {created}, {updated},
                     SHA2(TO_VARCHAR({payload}), 256), {payload}, {deleted}
              FROM @HOSPITALITY_DW.RAW.RAW_INGESTION_STAGE/{_literal(artifact['stage_prefix'])}
                (FILE_FORMAT => '{file_format}')
            )
            ON_ERROR = CONTINUE
            """
        )
        target_row = hook.get_first(
            """SELECT COUNT(*) FROM HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS
               WHERE INGESTION_BATCH_ID = %s AND SOURCE_TABLE = %s""",
            parameters=(batch["batch_id"], entity),
        )
        target_count = int(target_row[0] if target_row else 0)
        watermark_row = hook.get_first(
            """SELECT MAX(SOURCE_UPDATED_AT)::varchar
               FROM HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS
               WHERE INGESTION_BATCH_ID = %s AND SOURCE_TABLE = %s""",
            parameters=(batch["batch_id"], entity),
        )
        loads.append(
            {
                "entity": entity,
                "source_row_count": artifact["rows"],
                "target_row_count": target_count,
                "rejected_row_count": max(artifact["rows"] - target_count, 0),
                "target_object": "HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS",
                "watermark_end": watermark_row[0] if watermark_row else artifact.get("watermark_end"),
            }
        )
    return loads


def copy_raw(job: dict[str, Any], ti: Any, **_: Any) -> dict[str, Any]:
    spec = normalize_job(job)
    batch = ti.xcom_pull(task_ids="create_batch")
    staged = ti.xcom_pull(task_ids="stage")
    if staged["mode"] == "snowflake":
        loads = _copy_live(spec, batch, staged)
    else:
        loads = [
            {
                "entity": artifact["entity"],
                "source_row_count": artifact["rows"],
                "target_row_count": artifact["rows"],
                "rejected_row_count": 0,
                "target_object": "LOCAL.RAW_INGESTION_MANIFEST",
                "watermark_end": artifact.get("watermark_end"),
            }
            for artifact in staged["artifacts"]
        ]
        landing_root = Path(os.environ.get("LOCAL_LANDING_DIR", "/opt/airflow/data/landing"))
        manifest = landing_root / batch["batch_id"] / "raw_manifest.json"
        manifest.write_text(
            json.dumps({"mode": "local", "batch_id": batch["batch_id"], "loads": loads}, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "batch_id": batch["batch_id"],
        "mode": staged["mode"],
        "loads": loads,
        "target_row_count": sum(load["target_row_count"] for load in loads),
    }
