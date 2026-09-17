# RGA-style Synthetic Data Pack

This domain pack extends the existing hospitality Snowflake testbed without changing the hospitality generator.
It creates **synthetic Life & Health reinsurance test data only**; it is not based on proprietary RGA data and contains no real PII.

## Scope

The current vertical slice models:

- cedants
- reinsurance treaties
- insurance products
- insured lives
- policies and coverages
- underwriting cases
- gross and ceded premiums
- claims, claim payments, and reserves
- monthly exposure

The same YAML domain contract drives data generation, Snowflake RAW DDL, Snowflake load SQL, dbt sources/staging generation, and downstream analytical contracts so the layers cannot silently drift.

## End-to-end contract

```text
RGA synthetic domain YAML
        |
        +--> deterministic CSV generation + checksums/manifests
        |
        +--> Snowflake database/schema/RAW-table DDL
        |
        +--> internal-stage PUT + COPY INTO SQL
        |
        +--> dbt RAW sources -> STAGING -> CORE -> MART
        |
        +--> MART.REINSURANCE_PERFORMANCE
        |
        +--> Snowflake Semantic View YAML
        |       +--> verify-only SQL
        |       +--> create-or-alter deploy SQL
        |
        +--> paired direct-SQL vs Semantic View benchmark workload
        |
        +--> manual Airflow orchestration with gated semantic deployment
```

## Quick start

```bash
python scripts/rga_testbed/generate_data.py --preset tiny --seed 42
python scripts/rga_testbed/validate_dataset.py --input artifacts/rga_testbed
python scripts/rga_testbed/generate_snowflake_ddl.py
python scripts/rga_testbed/generate_load_sql.py
python scripts/rga_testbed/generate_dbt_project.py
python scripts/rga_testbed/generate_semantic_view.py
python scripts/rga_testbed/generate_benchmark_pack.py
python scripts/rga_testbed/generate_airflow_dag.py
```

For a bounded developer run that overrides only policy volume:

```bash
python scripts/rga_testbed/generate_data.py --preset tiny --policies 10000 --seed 42
```

## Scale presets

| Preset | Policies | Intended use |
| --- | ---: | --- |
| tiny | 500 | unit/integration tests |
| small | 50,000 | local functional tests |
| medium | 1,000,000 | warehouse performance tests |
| large | 10,000,000 | large-scale Snowflake benchmark |
| stress | 100,000,000 | distributed generation / stress target |

Monthly exposure can produce roughly 12x the active-policy volume, so the `stress` preset is a target profile and should be generated with distributed or partitioned execution rather than a single laptop process.

## Business invariants

The generator enforces or derives:

- every policy belongs to a valid cedant and treaty;
- every policy references a synthetic insured life and product;
- premiums are positive and ceded premium is treaty-share based;
- claims occur after policy issue;
- claim report dates are on or after event dates;
- ceded claim amounts do not exceed gross claim amounts;
- paid claims create payment rows;
- open claims create reserve rows;
- active policies create monthly exposure rows.

## Snowflake objects

`generate_snowflake_ddl.py` creates:

- `RGA_SYNTHETIC_TESTBED` database by default;
- `RAW`, `STAGING`, `CORE`, `MART`, `SEMANTIC`, and `AUDIT` schemas;
- CSV file format and internal stage;
- one RAW table for each domain entity;
- audit manifest table for generation metadata.

`generate_load_sql.py` creates deterministic PUT/COPY commands for every domain entity. Loads are fail-closed with `ON_ERROR='ABORT_STATEMENT'`, include generation IDs, capture `METADATA$FILENAME`, and do not force reload previously loaded files.

## dbt analytical layer

`generate_dbt_project.py` creates a complete dbt project with:

- RAW source declarations for every RGA synthetic entity;
- one STAGING view per source entity;
- `DIM_CEDANT`, `DIM_TREATY`, and `DIM_POLICY`;
- `FCT_PREMIUM`, `FCT_CLAIM`, and `FCT_EXPOSURE`;
- `MART.REINSURANCE_PERFORMANCE` at cedant + treaty + month grain;
- uniqueness/not-null contracts for core analytical keys.

The mart deliberately aggregates premium, claim, and exposure streams independently before joining them, preventing the fact-to-fact fan-out that can silently inflate financial measures.

## Governed semantic layer

`generate_semantic_view.py` generates a native Snowflake Semantic View contract for `MART.REINSURANCE_PERFORMANCE` plus separate verify and deploy SQL.

The first governed metrics include:

- total gross premium;
- total ceded premium;
- total gross claims;
- total ceded claims;
- total exposure;
- claim count;
- ceded loss ratio;
- ceded premium rate.

Verification uses `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` in verify-only mode. Deployment uses create-or-alter semantics so compatible semantic-view materializations can be preserved.

## Performance benchmark pack

`generate_benchmark_pack.py` emits paired queries that calculate the same business questions directly from the MART and through the Semantic View. Initial workload pairs cover monthly loss ratio by cedant, ceded premium by treaty, and claims/exposure trends. The manifest declares concurrency checkpoints of 1, 5, 10, 25, and 50 so live Snowflake testing can compare latency and workload behavior without changing the business definition.

## Guarded live execution

`execute_snowflake_sql.py` is the explicit live-account boundary. It refuses to execute any SQL file unless `--confirm` is supplied, supports credential-free `--dry-run` hashing/evidence, tags live sessions with `RGA_SYNTHETIC_PIPELINE`, and always closes the Snowflake connection. Credentials stay in environment variables and are never written into generated SQL or manifests.

Example dry-run:

```bash
python scripts/rga_testbed/execute_snowflake_sql.py \
  --sql-file snowflake/rga_testbed/001_raw_tables.sql \
  --confirm --dry-run
```

## Airflow orchestration

`generate_airflow_dag.py` generates the manual `rga_synthetic_semantic_pipeline` DAG. It orchestrates:

1. synthetic data generation;
2. Snowflake/dbt/semantic/benchmark contract generation;
3. Snowflake bootstrap;
4. RAW loading;
5. dbt build;
6. server-side Semantic View verification;
7. optional Semantic View deployment.

The DAG has no schedule, disables catchup, allows only one active run, and defaults `deploy_semantic_view` to `false`. Deployment must be explicitly enabled when triggering the DAG.

## Current verification boundary

Repository CI certifies deterministic generation, file validation, Snowflake DDL/load SQL generation, dbt scaffold generation, Semantic View contract generation, benchmark-pair generation, generated Airflow syntax, executor refusal without confirmation, and executor dry-run behavior. **Live Snowflake object creation, dbt execution against Snowflake, Semantic View server-side verification, and live concurrency/credit measurements remain external-account verification steps and are not claimed by local CI.**

Next slices: CDC/change-event fixtures, live dbt/Snowflake evidence, semantic-query concurrency runner with query-history metrics, Cortex Agent/MCP integration, and Power BI/Excel consumer validation.
