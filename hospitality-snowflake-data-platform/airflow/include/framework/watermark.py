"""Read and advance extraction watermarks only after a successful quality gate."""

from __future__ import annotations

from typing import Any

from .audit import execution_mode, get_local_watermark, set_local_watermark
from .metadata import normalize_job

INCREMENTAL_STRATEGIES = {"timestamp_incremental", "high_watermark"}


def read_watermark(job: dict[str, Any], **_: Any) -> dict[str, str | None]:
    spec = normalize_job(job)
    values: dict[str, str | None] = {}
    if spec["load_strategy"] not in INCREMENTAL_STRATEGIES:
        return values
    if execution_mode() == "local":
        return {entity: get_local_watermark(spec["source"], entity) for entity in spec["entities"]}

    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    hook = SnowflakeHook(snowflake_conn_id="snowflake_hospitality")
    for entity in spec["entities"]:
        row = hook.get_first(
            """SELECT WATERMARK_VALUE FROM HOSPITALITY_DW.AUDIT.TABLE_WATERMARKS
               WHERE SOURCE_SYSTEM = %s AND SOURCE_OBJECT = %s""",
            parameters=(spec["source"], entity),
        )
        values[entity] = row[0] if row else None
    return values


def update_watermark(job: dict[str, Any], ti: Any, **_: Any) -> dict[str, Any]:
    spec = normalize_job(job)
    if spec["load_strategy"] not in INCREMENTAL_STRATEGIES:
        return {"updated": 0, "reason": "load strategy is not watermark based"}

    batch = ti.xcom_pull(task_ids="create_batch")
    copy_result = ti.xcom_pull(task_ids="copy_raw")
    updates = [load for load in copy_result["loads"] if load.get("watermark_end")]
    if execution_mode() == "local":
        for load in updates:
            set_local_watermark(spec["source"], load["entity"], load["watermark_end"], batch["batch_id"])
        return {"updated": len(updates), "mode": "local"}

    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    hook = SnowflakeHook(snowflake_conn_id="snowflake_hospitality")
    for load in updates:
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
            parameters=(spec["source"], load["entity"], load["watermark_end"], batch["batch_id"]),
        )
    return {"updated": len(updates), "mode": "snowflake"}
