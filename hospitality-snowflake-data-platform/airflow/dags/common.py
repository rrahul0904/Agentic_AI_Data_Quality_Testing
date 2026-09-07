"""Runtime callables shared by ingestion DAGs.

Tasks emit explicit batch artifacts. A missing source or Snowflake connection fails the
task; the pipeline never reports a synthetic success.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from file_schemas import FILE_SCHEMAS, csv_payload_expression


def create_batch_id(source: str, dag_id: str, **_: Any) -> str:
    return f"{source}-{dag_id}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


def discover_or_extract(job: dict[str, Any], ti: Any, **_: Any) -> list[str]:
    batch_id = ti.xcom_pull(task_ids="create_batch_id")
    landing_root = Path(os.environ.get("LOCAL_LANDING_DIR", "/opt/airflow/data/landing"))
    batch_dir = landing_root / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    artifacts: list[str] = []
    if job["source"] == "files":
        generated = Path(os.environ.get("GENERATED_FILE_DIR", "/opt/airflow/sources/files/generated"))
        for entity in job["entities"]:
            candidate = generated / entity
            if not candidate.is_file():
                raise FileNotFoundError(f"Required source feed is missing: {candidate}")
            artifacts.append(str(candidate))
    else:
        mode = os.environ.get(f"{job['source'].upper()}_MODE", "simulated").lower()
        if mode == "database":
            from airflow.models import Variable
            from source_extractors import extract_entity

            for entity in job["entities"]:
                candidate = batch_dir / f"{entity}.jsonl"
                watermark = Variable.get(f"watermark__{job['source']}__{entity}", default_var=None)
                extract_entity(job, entity, candidate, watermark)
                artifacts.append(str(candidate))
        elif mode == "simulated":
            extract_root = Path(os.environ.get("SOURCE_EXPORT_DIR", "/opt/airflow/data/source_exports"))
            for entity in job["entities"]:
                candidate = extract_root / job["source"] / f"{entity}.jsonl"
                if not candidate.is_file():
                    raise FileNotFoundError(f"Expected {job['source']} extract is missing: {candidate}")
                artifacts.append(str(candidate))
        else:
            raise ValueError(f"Unsupported {job['source']} extraction mode: {mode!r}")
    manifest = batch_dir / "extract_manifest.json"
    manifest.write_text(json.dumps({"batch_id": batch_id, "job": job, "artifacts": artifacts}, indent=2), encoding="utf-8")
    return artifacts


def validate_artifacts(ti: Any, **_: Any) -> dict[str, Any]:
    artifacts = ti.xcom_pull(task_ids="extract.discover_or_extract")
    results = []
    for value in artifacts:
        path = Path(value)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Artifact is absent or empty: {path}")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        rows = 0
        with path.open("rb") as handle:
            if path.suffix.lower() in {".json", ".jsonl", ".csv"}:
                rows = sum(1 for _ in handle) - (1 if path.suffix.lower() == ".csv" else 0)
        if path.suffix.lower() == ".csv":
            import csv

            with path.open(newline="", encoding="utf-8") as handle:
                actual_columns = tuple(next(csv.reader(handle)))
            expected_columns = FILE_SCHEMAS.get(path.name)
            if expected_columns and actual_columns != expected_columns:
                raise ValueError(f"Schema mismatch for {path.name}: expected {expected_columns}, got {actual_columns}")
        results.append({"path": str(path), "bytes": path.stat().st_size, "rows": rows, "sha256": digest})
    return {"artifacts": results, "validated_at": datetime.now(UTC).isoformat()}


def load_to_snowflake(job: dict[str, Any], ti: Any, **_: Any) -> int:
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    batch_id = ti.xcom_pull(task_ids="create_batch_id")
    validation = ti.xcom_pull(task_ids="validate.validate_artifacts")
    hook = SnowflakeHook(snowflake_conn_id="snowflake_hospitality")
    loaded = 0
    hook.run(
        """
        MERGE INTO HOSPITALITY_DW.AUDIT.BATCH_CONTROL target
        USING (SELECT %s BATCH_ID, %s DAG_ID, %s SOURCE_SYSTEM) source
        ON target.BATCH_ID = source.BATCH_ID
        WHEN NOT MATCHED THEN INSERT
          (BATCH_ID, DAG_ID, SOURCE_SYSTEM, STARTED_AT, BATCH_STATUS)
          VALUES (source.BATCH_ID, source.DAG_ID, source.SOURCE_SYSTEM, CURRENT_TIMESTAMP(), 'RUNNING')
        """,
        parameters=(batch_id, job["dag_id"], job["source"]),
    )
    for artifact in validation["artifacts"]:
        path = Path(artifact["path"])
        suffix = path.suffix.lower()
        if suffix in {".json", ".jsonl"}:
            file_format = "HOSPITALITY_DW.RAW.FF_JSON"
            payload = "$1"
        elif suffix == ".parquet":
            file_format = "HOSPITALITY_DW.RAW.FF_PARQUET"
            payload = "$1"
        else:
            file_format = "HOSPITALITY_DW.RAW.FF_CSV"
            payload = csv_payload_expression(path.name)
        entity_name = path.name if job["source"] == "files" else path.stem
        entity = entity_name.replace("'", "''")
        if job["source"] == "oracle":
            pk_expression = f'$1:"{entity}_ID"::varchar'
            created_expression = "$1:SOURCE_CREATED_AT::timestamp_tz"
            updated_expression = "$1:SOURCE_UPDATED_AT::timestamp_tz"
            deleted_expression = "coalesce($1:IS_DELETED::boolean, false)"
        elif job["source"] == "postgres":
            pk_expression = f'$1:"{entity}_id"::varchar'
            created_expression = "$1:source_created_at::timestamp_tz"
            updated_expression = "$1:source_updated_at::timestamp_tz"
            deleted_expression = "coalesce($1:is_deleted::boolean, false)"
        else:
            pk_expression = "NULL"
            created_expression = "NULL"
            updated_expression = "NULL"
            deleted_expression = "FALSE"
        stage_prefix = f"{job['source']}/{batch_id}/{entity}"
        hook.run(
            f"PUT 'file://{path}' @HOSPITALITY_DW.RAW.RAW_INGESTION_STAGE/{stage_prefix} "
            "AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
        )
        hook.run(
            f"""
            COPY INTO HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS
              (RAW_RECORD_ID, SOURCE_SYSTEM, SOURCE_TABLE, SOURCE_FILE_NAME, SOURCE_PRIMARY_KEY,
               INGESTION_BATCH_ID, INGESTED_AT, SOURCE_CREATED_AT, SOURCE_UPDATED_AT,
               RECORD_HASH, RAW_PAYLOAD, IS_DELETED)
            FROM (
              SELECT UUID_STRING(), '{job['source']}', '{entity}', METADATA$FILENAME, {pk_expression},
                     '{batch_id}', CURRENT_TIMESTAMP(), {created_expression}, {updated_expression},
                     SHA2(TO_VARCHAR({payload}), 256), {payload}, {deleted_expression}
              FROM @HOSPITALITY_DW.RAW.RAW_INGESTION_STAGE/{stage_prefix}
                (FILE_FORMAT => '{file_format}')
            )
            ON_ERROR = CONTINUE
            """
        )
        target_count = hook.get_first(
            """SELECT COUNT(*) FROM HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS
               WHERE INGESTION_BATCH_ID = %s AND SOURCE_TABLE = %s""",
            parameters=(batch_id, entity_name),
        )[0]
        hook.run(
            """
            INSERT INTO HOSPITALITY_DW.AUDIT.LOAD_HISTORY
              (LOAD_ID, BATCH_ID, DAG_ID, SOURCE_SYSTEM, SOURCE_OBJECT, TARGET_OBJECT,
               LOAD_STATUS, SOURCE_ROW_COUNT, TARGET_ROW_COUNT, STARTED_AT, COMPLETED_AT)
            SELECT UUID_STRING(), %s, %s, %s, %s, 'RAW.RAW_INGESTION_EVENTS',
                   'LOADED', %s, %s, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
            """,
            parameters=(
                batch_id, job["dag_id"], job["source"], artifact["path"],
                artifact.get("rows") or None, target_count,
            ),
        )
        loaded += target_count
        if job["load_strategy"] in {"timestamp_incremental", "high_watermark"}:
            watermark = hook.get_first(
                """SELECT MAX(SOURCE_UPDATED_AT)::varchar
                   FROM HOSPITALITY_DW.RAW.RAW_INGESTION_EVENTS
                   WHERE INGESTION_BATCH_ID = %s AND SOURCE_TABLE = %s""",
                parameters=(batch_id, entity_name),
            )[0]
            if watermark:
                from airflow.models import Variable

                Variable.set(f"watermark__{job['source']}__{entity_name}", watermark)
                hook.run(
                    """
                    MERGE INTO HOSPITALITY_DW.AUDIT.TABLE_WATERMARKS target
                    USING (SELECT %s SOURCE_SYSTEM, %s SOURCE_OBJECT, %s WATERMARK_VALUE, %s BATCH_ID) source
                    ON target.SOURCE_SYSTEM = source.SOURCE_SYSTEM AND target.SOURCE_OBJECT = source.SOURCE_OBJECT
                    WHEN MATCHED THEN UPDATE SET WATERMARK_VALUE = source.WATERMARK_VALUE,
                      LAST_SUCCESSFUL_BATCH_ID = source.BATCH_ID, UPDATED_AT = CURRENT_TIMESTAMP()
                    WHEN NOT MATCHED THEN INSERT
                      (SOURCE_SYSTEM, SOURCE_OBJECT, WATERMARK_COLUMN, WATERMARK_VALUE,
                       LAST_SUCCESSFUL_BATCH_ID, UPDATED_AT)
                      VALUES (source.SOURCE_SYSTEM, source.SOURCE_OBJECT, 'SOURCE_UPDATED_AT',
                              source.WATERMARK_VALUE, source.BATCH_ID, CURRENT_TIMESTAMP())
                    """,
                    parameters=(job["source"], entity_name, watermark, batch_id),
                )
    hook.run(
        """UPDATE HOSPITALITY_DW.AUDIT.BATCH_CONTROL
           SET BATCH_STATUS = 'SUCCESS', COMPLETED_AT = CURRENT_TIMESTAMP()
           WHERE BATCH_ID = %s""",
        parameters=(batch_id,),
    )
    return loaded


def record_quality(ti: Any, **_: Any) -> None:
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    validation = ti.xcom_pull(task_ids="validate.validate_artifacts")
    if not validation or not validation.get("artifacts"):
        raise ValueError("No validated artifacts were handed to the quality gate")
    batch_id = ti.xcom_pull(task_ids="create_batch_id")
    target_rows = ti.xcom_pull(task_ids="load.load_to_snowflake") or 0
    status = "PASS" if target_rows > 0 else "FAIL"
    SnowflakeHook(snowflake_conn_id="snowflake_hospitality").run(
        """
        INSERT INTO HOSPITALITY_DW.AUDIT.DATA_QUALITY_RESULTS
          (RESULT_ID, BATCH_ID, CHECK_NAME, CHECK_LAYER, TARGET_OBJECT,
           EXPECTED_VALUE, ACTUAL_VALUE, CHECK_STATUS, SEVERITY, DETAILS, CHECKED_AT)
        SELECT UUID_STRING(), %s, 'raw_batch_nonempty', 'RAW', 'RAW.RAW_INGESTION_EVENTS',
               OBJECT_CONSTRUCT('minimum_rows', 1), OBJECT_CONSTRUCT('actual_rows', %s),
               %s, 'ERROR', OBJECT_CONSTRUCT('validated_artifacts', %s), CURRENT_TIMESTAMP()
        """,
        parameters=(batch_id, target_rows, status, len(validation["artifacts"])),
    )
    if target_rows <= 0:
        raise ValueError(f"Snowflake raw batch {batch_id} did not load any rows")
