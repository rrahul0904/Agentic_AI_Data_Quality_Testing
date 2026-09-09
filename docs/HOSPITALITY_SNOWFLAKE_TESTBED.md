# Hospitality Snowflake live testbed

This testbed is a reproducible, testbed-only mutation surface for exercising the read-only ADE Snowflake pipeline tester against actual infrastructure. It supports deterministic local verification without credentials, manual Snowflake ingestion through an internal stage, and event-driven Snowpipe ingestion from Amazon S3. It never translates missing credentials or an unexecuted external check into `PASS`.

## Architecture

```text
deterministic generator ── CSV (12 entities) ─┐
                        └─ Parquet (8 entities) ├─ manifest + file validation
                                              │
          LOCAL                               ├─ internal stage → COPY INTO ─┐
          LIVE                                └─ S3 → external stage → pipes ├─ RAW
                                                                            │
                                               CDC tables ← Streams ←────────┤
                                                                            ▼
                                             dbt staging → core → marts
                                                                            │
                               DQ ← manifest-bounded reconciliation ←────────┤
                                                                            ▼
                                                    ADE deterministic RCA
```

The database defaults to `HOSPITALITY_TESTBED` and contains `RAW`, `CDC`, `STAGING`, `CORE`, `MARTS`, `QUALITY`, and `OPS`. The warehouse defaults to an auto-suspending X-Small `ADE_HOSPITALITY_TESTBED_WH`.

## Execution boundary

Checking out, importing, testing, or statically parsing this repository does not execute Snowflake DDL and does not load target tables. The complete DDL execution path is present in `bootstrap_snowflake.py`; it runs only when explicitly invoked without `--dry-run`. File movement occurs only through the explicit stage/upload commands, RAW loading only through `run_copy_loads.py` or configured Snowpipes, Stream consumption only through the dual-gated `consume_streams.py --execute`, and final-table builds only through `run_dbt.py`. Pull-request CI renders DDL and COPY SQL but has no external credentials. The live job is manual, opt-in, and protected by the `snowflake-hospitality-testbed` environment.

## Source ecosystem

The 12 CSV entities are hotels, rooms, room types, guests, reservations, reservation guests, payments, folio charges, cancellations, refunds, loyalty members, and property staff. The eight Parquet entities are stays, room inventory, daily rates, channel bookings, housekeeping events, web booking events, guest preferences, and property daily metrics.

Keys are coherent across hotel, room, room type, guest, reservation, payment, folio, stay, loyalty, channel, and staff records. Reservations include booking windows, seasonal pricing, cancellations, no-shows, completed stays, partial payments, refunds, and channel commissions. Generation is deterministic for a seed and reference date. The `large` preset writes facts in bounded batches rather than retaining two million reservations in memory.

Every file is registered in `data/hospitality/manifest.json` with its generation/load identity, format, target, schema, row and byte counts, time bounds, and SHA-256 checksum. Generated runtime data, state, and evidence are Git-ignored.

## Local deterministic verification

No external credentials are required:

```bash
python -m pip install -e '.[dev,testbed]'
python scripts/hospitality_testbed/generate_data.py --preset tiny --seed 42
python scripts/hospitality_testbed/validate_files.py
python scripts/hospitality_testbed/render_copy_commands.py --mode local
python scripts/hospitality_testbed/validate_pipeline.py
python scripts/hospitality_testbed/reconcile_pipeline.py --offline
make hospitality-failure-fixtures
make hospitality-test
```

Offline reconciliation certifies only `manifest → local files`. COPY, RAW, Stream, and mart counts remain `NOT_RUN`; this is intentionally not represented as external certification.

## Local/manual Snowflake mode

Set the `ADE_SNOWFLAKE_*` variables from `.env.example`, keeping the database name isolated. Then run:

```bash
export ADE_TESTBED_MODE=local
make hospitality-bootstrap-snowflake
make hospitality-stage-internal
make hospitality-copy-load
make hospitality-stream-check
make hospitality-dbt
make hospitality-reconcile
make hospitality-certify
```

`stage_internal_files.py` issues one `PUT` per manifest file, retaining the relative partition path. `render_copy_commands.py` emits one `COPY INTO` per manifest file with `FILES`, `FORCE=FALSE`, name-based mapping, and Snowflake file metadata. This prevents a later incremental batch from being reconciled against an unrelated cumulative table count.

## Live Snowpipe mode

The S3 bucket must be private. Configure an IAM role for the Snowflake storage integration, an SNS topic in the same region as the bucket, and S3 object-created notifications for the isolated prefix. Do not add long-lived AWS keys to the repository; `upload_to_s3.py` uses the standard boto3 credential chain.

Provisioning is a two-pass operation:

1. Set `ADE_TESTBED_AWS_ROLE_ARN`, bucket, prefix, region, and SNS ARN, then run `bootstrap_snowflake.py --mode live` with an administrative setup role. Live mode defaults `ADE_TESTBED_BOOTSTRAP_ROLE` to `ACCOUNTADMIN` because creating a storage integration is an account-level operation; override it with a delegated setup role that has the required privileges.
2. Run `DESC INTEGRATION ADE_HOSPITALITY_S3_INT` and add the returned Snowflake IAM user ARN and external ID to the AWS role trust policy.
3. Run `SELECT SYSTEM$GET_AWS_SNS_IAM_POLICY('<topic-arn>')` and merge the returned subscription grant into the SNS topic policy. Also allow the S3 bucket to publish to the topic.
4. Configure the S3 notification for `hospitality/` object-created events, then verify each pipe with `SYSTEM$PIPE_STATUS`.

Snowflake's current S3 Snowpipe flow and SNS policy requirements are documented in [Automating Snowpipe for Amazon S3](https://docs.snowflake.com/en/user-guide/data-load-snowpipe-auto-s3). Stage and pipe syntax are kept in `snowflake/testbed/03_stages_live.sql` and `snowflake/testbed/pipes/`.

Run the live path only after infrastructure is configured:

```bash
export ADE_TESTBED_MODE=live
make hospitality-e2e-live
make hospitality-certify
```

The six pipes cover reservations, payments, folio charges, cancellations, stays, and channel bookings; the other reference feeds use manifest-bounded COPY from the same external stage. Their COPY definitions avoid a SELECT transform and use `MATCH_BY_COLUMN_NAME` plus `INCLUDE_METADATA`, allowing the separate `VALIDATE_PIPE_LOAD` inspection to remain usable. Snowpipe uses `ON_ERROR=SKIP_FILE` because `ABORT_STATEMENT` is not supported in pipe COPY definitions. [`COPY_HISTORY`](https://docs.snowflake.com/en/sql-reference/functions/copy_history) and [`VALIDATE_PIPE_LOAD`](https://docs.snowflake.com/en/sql-reference/functions/validate_pipe_load) retain 14 days of Information Schema history.

Uploaded object keys preserve each entity prefix and add `generation_id=<id>` beneath it. This keeps every run distinct without changing pipe prefixes. `monitor_snowpipe.py` waits for every manifest-listed pipe file and fails on missing history, rejected rows, validation errors, or a non-running pipe; an empty history can never be reported as `PASS`.

## Streams and CDC

Standard (not append-only) Streams exist for reservations, payments, stays, cancellations, and folio charges so tests can observe `METADATA$ACTION` and `METADATA$ISUPDATE`. `monitor_streams.py` reads status/backlog but does not consume a Stream. Five Tasks are created suspended. Stream consumption is always explicit:

```bash
export ADE_TESTBED_MUTATION_APPROVED=true
python scripts/hospitality_testbed/consume_streams.py --execute
```

## dbt and Airflow

The nested dbt project under `hospitality-snowflake-data-platform/dbt/testbed` contains 20 staging models, 12 dimensional/core models, and eight marts. Six facts are incremental with merge keys and schema-change policies. Generic and singular tests cover keys, relationships, accepted statuses, dates, nonnegative amounts, capacity, refund bounds, and row conservation.

Airflow exposes 13 reusable-script DAGs and the TaskGroup-based `hospitality_end_to_end` DAG. Airflow is optional; `run_e2e.py` and the Make targets provide the same basic flow without a scheduler. All three dbt layer DAGs call `run_dbt.py`, which records the real build/test exit code and output in `artifacts/hospitality/dbt-results.json`.

## DQ, reconciliation, and ADE RCA

File validation covers zero bytes, parsing, Parquet readability, schema, row count, checksum, extension, and partition structure. Local DQ covers business-key nulls/duplicates, source relationships, reservation dates, nonnegative money, refund bounds, and room capacity. `run_snowflake_dq.py` executes the 18 configured DQ rules as real, read-only, generation-bounded queries across RAW, CORE, and MARTS and writes `snowflake-quality.json`; it never persists into Snowflake. Snowflake reconciliation binds all comparisons to `generation_id` and `load_id` and records generated, COPY parsed/loaded/rejected, and RAW counts independently.

`certify_with_ade.py` invokes the PR #6 read-only ADE surfaces for stage files, file format, pipe health, pipe load validation, Stream status/backlog, COPY history, schema drift, latency, target quality, reconciliation, health, and deterministic first-divergence RCA.

## Failure lab

The fixture generator covers malformed CSV, invalid timestamp, bad number, missing/extra columns, null required keys, duplicate keys, zero-byte files, corrupt Parquet, wrong delimiter/header, stale/unexpected files, schema drift, missing/partial batches, duplicate delivery, and late arrival. Generation is harmless and local:

```bash
make hospitality-failure-fixtures
```

Staging bad data is never automatic and requires both an explicit action and approval:

```bash
export ADE_TESTBED_MUTATION_APPROVED=true
python scripts/hospitality_testbed/stage_failure_fixture.py --scenario invalid_timestamp --stage --mode live
python scripts/hospitality_testbed/run_failure_certification.py --scenario invalid_timestamp --mode live
```

`certify_failure_accuracy.py` compares expected and observed first divergence. `run_failure_certification.py` appends real observations and refreshes the accuracy artifact. Unexecuted scenarios remain `NOT_RUN`; an accuracy percentage is emitted only after every configured scenario has actually been executed.

## Safety and teardown

All mutation clients set the `ADE_HOSPITALITY_TESTBED` query tag, validate identifiers, write redacted evidence, and target explicit manifest objects. Reset and teardown require `ADE_TESTBED_MUTATION_APPROVED=true` plus exact database confirmation. Production-looking database names and the shared `HOSPITALITY_DW` database are refused.

```bash
export ADE_TESTBED_MUTATION_APPROVED=true
python scripts/hospitality_testbed/reset_testbed.py --confirm-database HOSPITALITY_TESTBED
python scripts/hospitality_testbed/teardown_snowflake.py --confirm-database HOSPITALITY_TESTBED
```

Troubleshooting starts with `artifacts/hospitality/`: check file validation, rendered COPY commands, Snowpipe status, `COPY_HISTORY`, `VALIDATE_PIPE_LOAD`, Stream health, reconciliation, and the ADE RCA artifact in that order. Missing Snowflake/AWS credentials produce `BLOCKED_EXTERNAL`; a missing mutation approval produces `BLOCKED_APPROVAL`.
