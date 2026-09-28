# Phase 2: payments reconciliation diagnostic

Status: read-only finding; no reload, repair, grant, or pipeline execution performed  
Project / environment: `data-quality-testing-beta` / `development`

## Finding

The saved baseline `recon_a30705339c8149b2b718bf2e512fc8bd` was captured at **2026-09-23 16:54:21 UTC** and compared row counts only: PostgreSQL `hospitality_oltp.public.payments` had **35,000** rows and Snowflake `HOSPITALITY_RELIABILITY_LAB.RAW.PAYMENTS` had **33,416**, a difference of **1,584**. It has no key-level result or associated pipeline-run ID, so it is historical evidence, not proof of a particular load's outcome.

A bounded live recheck found **35,000** source rows and **33,424** target rows. Both sides had unique, non-null `payment_id`s; there were no duplicate-ID groups, no null IDs, and no target-only IDs. The key-set comparison found **1,576** source IDs absent from Snowflake. Every missing source row had `updated_at` after the Snowflake watermark `2026-09-23 18:30 UTC`; none was at or before that watermark.

The ingestion implementation in `runtime/hospitality-data-reliability-lab/airflow/include/hospitality_lab/ingestion.py` uses the window `updated_at > watermark AND updated_at <= logical_date`. The missing rows therefore were outside that run's eligible time window, rather than demonstrated dropped rows. The source timestamps for the missing records ranged from 2026-09-24 16:00 UTC through 2027-01-06 17:00 UTC. At 18:30 UTC the Airflow extract/load/watermark tasks were recorded complete, and the Snowflake watermark row reported `SUCCESS` with `LAST_ROW_COUNT=0`. Snowflake `COPY_HISTORY` showed eight rows loaded at 17:00 UTC and zero for later files through 18:30 UTC, consistent with the saved count changing from 33,416 to 33,424.

This supports a future-dated-record / watermark-window explanation for the observed gap. It does not establish why those source timestamps are in the future or whether that source fixture behavior is intended. Do not backfill or change the ingestion window without the data owner's approval and a separately reviewed plan.

## Reproduction (read-only)

Use the same database, schema, time cutoff, and environment recorded above. Save the query timestamp and connector/query IDs with the results.

```sql
-- PostgreSQL: counts at the saved comparison cutoff.
SELECT COUNT(*) AS total_rows,
       COUNT(DISTINCT payment_id) AS distinct_payment_ids,
       COUNT(*) FILTER (WHERE payment_id IS NULL) AS null_payment_ids,
       COUNT(*) FILTER (
         WHERE updated_at <= TIMESTAMPTZ '2026-09-23 16:54:21+00'
       ) AS rows_at_or_before_saved_cutoff,
       COUNT(*) FILTER (
         WHERE updated_at > TIMESTAMPTZ '2026-09-23 16:54:21+00'
       ) AS rows_after_saved_cutoff,
       MIN(updated_at) AS earliest_update,
       MAX(updated_at) AS latest_update
FROM public.payments;
```

```sql
-- Snowflake: current target identity and load-time bounds.
SELECT COUNT(*) AS total_rows,
       COUNT(DISTINCT PAYMENT_ID) AS distinct_payment_ids,
       COUNT_IF(PAYMENT_ID IS NULL) AS null_payment_ids,
       MIN(_SOURCE_UPDATED_AT) AS earliest_source_update,
       MAX(_SOURCE_UPDATED_AT) AS latest_source_update,
       MAX(_INGESTED_AT) AS latest_ingest_time
FROM HOSPITALITY_RELIABILITY_LAB.RAW.PAYMENTS;

-- Snowflake: current ingestion watermark.
SELECT LAST_SUCCESSFUL_WATERMARK, LAST_ROW_COUNT, LAST_SUCCESS_AT, STATUS
FROM HOSPITALITY_RELIABILITY_LAB.CONTROL.INGESTION_WATERMARKS
WHERE SOURCE_SYSTEM = 'hospitality_oltp' AND SOURCE_TABLE = 'PAYMENTS';

-- Snowflake: recent file outcomes (metadata only).
SELECT LAST_LOAD_TIME, STATUS, ROW_COUNT, ROW_PARSED, ERROR_COUNT
FROM TABLE(HOSPITALITY_RELIABILITY_LAB.INFORMATION_SCHEMA.COPY_HISTORY(
  TABLE_NAME => 'PAYMENTS',
  START_TIME => DATEADD('hour', -6, CURRENT_TIMESTAMP())
))
ORDER BY LAST_LOAD_TIME DESC
LIMIT 10;
```

For key-set reconciliation, fetch only `payment_id` and `updated_at` from PostgreSQL and `PAYMENT_ID` from Snowflake, with a fixed upper bound (50,000 rows was sufficient for this dataset). Compare IDs in memory; report counts, timestamp bounds, source-only IDs, target-only IDs, null IDs, and duplicate groups. Do not persist the extracted identifiers in logs or the issue report. Confirm that each source-only ID's `updated_at` is later than the target watermark. For larger tables, use a warehouse-native staged reconciliation design with explicit cost limits; do not transfer an unbounded key list to the UI.

## Remaining evidence gap

The authenticated Airflow runtime API could not be independently checked during this audit: API v2 returned **401 Not authenticated**, and the legacy v1 endpoint returned **404**. Local OpenLineage records supplied the matching run evidence, while Snowflake watermark and `COPY_HISTORY` records supplied the warehouse-side evidence. Configure read-only Airflow API authentication before using this procedure to certify task-instance state directly. No credentials should be copied into this document or logs.

## Safety and security

No Airflow, dbt, Snowflake load, Snowpipe, DML, DDL, grant, or data-repair operation was executed. A separate local diagnostic mistake exposed a credential in an internal tool output; the value is deliberately not reproduced. Rotate/revoke it in the owning provider and update the local secret store. That rotation is not performed by this read-only audit.
