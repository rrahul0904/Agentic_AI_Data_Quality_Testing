# Snowflake Pipeline Testing

Agentic Data Engineering OS includes a read-only Snowflake ingestion testing surface spanning staged files, file formats, Snowpipe, Streams, COPY history, schema drift, latency, reconciliation, target-table data quality, and deterministic root-cause analysis.

## Verification model

The normal product surface is deliberately read-only. It can inspect `SHOW`, `DESC`, `LIST`, `INFER_SCHEMA`, `SYSTEM$PIPE_STATUS`, `SYSTEM$STREAM_HAS_DATA`, `COPY_HISTORY`, `VALIDATE_PIPE_LOAD`, `VALIDATE(...)`, stream rows, and target-table aggregates. It does not execute `COPY`, `ALTER PIPE`, `CREATE STREAM`, `TRUNCATE`, `DELETE`, or other Snowflake mutations.

Evidence order:

```text
stage files
  -> file-format contract
  -> Snowpipe control/load errors
  -> stage-to-load latency
  -> Stream health/backlog
  -> schema drift
  -> target-table DQ
  -> load reconciliation
  -> first-divergence RCA
```

## Stage and file-format testing

- stage inventory
- bounded staged-file listing
- minimum file count
- zero-byte detection
- extension validation
- optional file-age SLA
- optional regex pattern
- file-format property contract checks

```bash
ade snowflake-test stages --args '{"schema":"HOTEL.RAW"}'
ade snowflake-test stage-files --args '{"stage_name":"HOTEL.RAW.LANDING","expected_extensions":[".csv"],"max_age_minutes":30}'
ade snowflake-test file-format --args '{"file_format_name":"HOTEL.RAW.RES_CSV","expected":{"TYPE":"CSV","FIELD_DELIMITER":",","SKIP_HEADER":1}}'
```

## Snowpipe and Streams

Snowpipe checks cover inventory, `SYSTEM$PIPE_STATUS`, and `VALIDATE_PIPE_LOAD`. Stream checks cover inventory, staleness, `SYSTEM$STREAM_HAS_DATA`, and pending insert/delete/update markers.

```bash
ade snowflake-test pipe-status --args '{"pipe_name":"HOTEL.RAW.RES_PIPE"}'
ade snowflake-test pipe-validate --args '{"pipe_name":"HOTEL.RAW.RES_PIPE","hours":24}'
ade snowflake-test stream-status --args '{"stream_name":"HOTEL.RAW.RES_STREAM"}'
ade snowflake-test stream-backlog --args '{"stream_name":"HOTEL.RAW.RES_STREAM","max_pending_rows":10000}'
```

## COPY analysis and history

Static analysis needs no Snowflake credentials and flags implicit error policy, partial-load policies, skipped-file policies, `FORCE=TRUE`, `PURGE=TRUE`, file-format configuration, and validation mode.

```bash
ade snowflake-test copy-analyze --args '{"sql":"COPY INTO RAW.RESERVATION FROM @LANDING FILE_FORMAT=(TYPE=CSV) ON_ERROR=CONTINUE"}'
ade snowflake-test copy-history --args '{"table_name":"HOTEL.RAW.RESERVATION","hours":24}'
ade snowflake-test copy-validate --args '{"table_name":"HOTEL.RAW.RESERVATION","job_id":"_last"}'
```

## Schema drift

`INFER_SCHEMA` from staged files is compared with `DESC TABLE` for the target. The checker flags source columns absent from target, type-family mismatches, nullable-source to non-null-target risk, and required target columns absent from source.

```bash
ade snowflake-test schema-drift --args '{"stage_name":"HOTEL.RAW.LANDING","target_table":"HOTEL.RAW.RESERVATION","file_format_name":"HOTEL.RAW.RES_CSV","ignore_target_columns":["INGESTED_AT"]}'
```

## Ingestion latency

Stage `LAST_MODIFIED` values are matched to `COPY_HISTORY.LAST_LOAD_TIME` to calculate p50, p95, and p99 stage-to-load latency and identify files that are stuck beyond the configured SLA.

```bash
ade snowflake-test latency --args '{"stage_name":"HOTEL.RAW.LANDING","table_name":"HOTEL.RAW.RESERVATION","pipe_name":"HOTEL.RAW.RES_PIPE","max_latency_minutes":15,"hours":24}'
```

## Target DQ and reconciliation

Target checks include minimum rows, required-column nulls, single/compound-key duplicates, and freshness. Reconciliation compares parsed rows, loaded rows, rejected rows, failed files, and target row evidence for the bounded history window.

```bash
ade snowflake-test quality --args '{"table_name":"HOTEL.RAW.RESERVATION","key_columns":["RESERVATION_ID"],"not_null_columns":["RESERVATION_ID"],"freshness_column":"INGESTED_AT","max_age_minutes":15}'
ade snowflake-test reconcile --args '{"table_name":"HOTEL.RAW.RESERVATION","pipe_name":"HOTEL.RAW.RES_PIPE","hours":24,"expected_loaded_rows":10000,"max_rejected_rows":0}'
```

## Full health and deterministic RCA

`health` rolls up the complete evidence chain. `rca` returns the first failing or degraded component, measured evidence, and a bounded remediation recommendation. The first-divergence result is deterministic; it is not invented by an LLM.

```bash
ade snowflake-test rca --args '{"stage_name":"HOTEL.RAW.LANDING","file_format_name":"HOTEL.RAW.RES_CSV","pipe_name":"HOTEL.RAW.RES_PIPE","stream_name":"HOTEL.RAW.RES_STREAM","target_table":"HOTEL.RAW.RESERVATION"}'
```

## Deterministic failure lab

The local failure lab supplies repeatable negative fixtures for malformed CSV, invalid numeric values, invalid timestamps, missing required columns, extra source columns, required-key NULLs, duplicate business keys, and zero-byte files.

```bash
ade snowflake-test failure-lab --args '{}'
ade snowflake-test failure-lab --args '{"scenario":"invalid_timestamp","prefix":"qa"}'
```

The failure lab never uploads or stages a fixture. It returns fixture content, the expected first-divergence class, and the live-mutation boundary. Staging negative fixtures must happen only in an isolated Snowflake test environment through an explicitly approved external workflow.

## API

Every governed CLI operation has the same API counterpart under `POST /api/v1/snowflake-testing/{operation}`.

Operations: `copy-analyze`, `failure-lab`, `stages`, `stage-files`, `file-format`, `pipes`, `pipe-status`, `pipe-validate`, `streams`, `stream-status`, `stream-backlog`, `copy-history`, `copy-validate`, `schema-drift`, `latency`, `quality`, `reconcile`, `health`, and `rca`.

## Live certification

Configure `ADE_SNOWFLAKE_*` credentials plus the `ADE_LIVE_SNOWFLAKE_*` object and SLA variables documented in `.env.example`, then run:

```bash
make snowflake-pipeline-live-e2e
```

The live harness calls the same deterministic RCA path used by the product. If credentials or required object names are absent, it exits `BLOCKED_EXTERNAL`. A real Snowflake pipeline is not reported as `PASS` until this harness succeeds against those external objects.

The live certification is read-only and assumes the test stage, file format, pipe, stream, and target table already exist.
