# Snowflake Pipeline Testing

Agentic Data Engineering OS includes a read-only Snowflake ingestion testing surface for Snowpipe, Streams, COPY INTO and post-load data quality.

## Scope

The first implementation verifies:

- Snowpipe inventory and `SYSTEM$PIPE_STATUS`
- `VALIDATE_PIPE_LOAD` error inspection for Snowpipe
- Stream inventory, staleness and `SYSTEM$STREAM_HAS_DATA`
- static `COPY INTO` command analysis
- `INFORMATION_SCHEMA.COPY_HISTORY`
- Snowflake `VALIDATE(...)` error inspection
- target-table minimum row count
- required-column null checks
- compound/single-key duplicate checks
- ingestion freshness
- rolled-up pipeline health

The testing surface does **not** execute COPY, ALTER PIPE, CREATE STREAM, TRUNCATE, DELETE or other mutations. It establishes evidence around an ingestion pipeline while preserving the platform's governed mutation boundary.

## CLI

Static COPY analysis needs no credentials:

```bash
ade snowflake-test copy-analyze --args '{"sql":"COPY INTO RAW.RESERVATION FROM @LANDING ON_ERROR=CONTINUE"}'
```

With Snowflake credentials configured:

```bash
ade snowflake-test pipes --args '{"schema":"HOTEL.RAW"}'
ade snowflake-test pipe-status --args '{"pipe_name":"HOTEL.RAW.RES_PIPE"}'
ade snowflake-test pipe-validate --args '{"pipe_name":"HOTEL.RAW.RES_PIPE","hours":24}'
ade snowflake-test streams --args '{"schema":"HOTEL.RAW"}'
ade snowflake-test stream-status --args '{"stream_name":"HOTEL.RAW.RES_STREAM"}'
ade snowflake-test copy-history --args '{"table_name":"HOTEL.RAW.RESERVATION","hours":24}'
ade snowflake-test copy-validate --args '{"table_name":"HOTEL.RAW.RESERVATION","job_id":"_last"}'
ade snowflake-test quality --args '{"table_name":"HOTEL.RAW.RESERVATION","key_columns":["RESERVATION_ID"],"not_null_columns":["RESERVATION_ID"],"freshness_column":"INGESTED_AT","max_age_minutes":15}'
ade snowflake-test health --args '{"pipe_name":"HOTEL.RAW.RES_PIPE","stream_name":"HOTEL.RAW.RES_STREAM","target_table":"HOTEL.RAW.RESERVATION","key_columns":["RESERVATION_ID"],"not_null_columns":["RESERVATION_ID"],"freshness_column":"INGESTED_AT","max_age_minutes":15}'
```

## API

The same governed tools are exposed through the domain API:

```text
POST /api/v1/snowflake-testing/copy-analyze
POST /api/v1/snowflake-testing/pipes
POST /api/v1/snowflake-testing/pipe-status
POST /api/v1/snowflake-testing/pipe-validate
POST /api/v1/snowflake-testing/streams
POST /api/v1/snowflake-testing/stream-status
POST /api/v1/snowflake-testing/copy-history
POST /api/v1/snowflake-testing/copy-validate
POST /api/v1/snowflake-testing/quality
POST /api/v1/snowflake-testing/health
```

## Live verification boundary

Without valid `ADE_SNOWFLAKE_*` credentials, live Snowflake tools return `SKIP_EXTERNAL`. Static COPY analysis remains locally verifiable.

A future live certification fixture should provision an isolated Snowflake database/schema with a stage, pipe, stream and target table, inject known good/bad files, then assert the exact evidence returned by these tools.
