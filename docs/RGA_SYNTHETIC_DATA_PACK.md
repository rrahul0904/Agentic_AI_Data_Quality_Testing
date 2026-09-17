# RGA-style Synthetic Data Pack

This domain pack extends the existing Snowflake pipeline testbed without changing the hospitality generator. It creates **synthetic Life & Health reinsurance test data only**; it is not based on proprietary RGA data and contains no real PII.

## End-to-end architecture

```text
RGA synthetic domain YAML
        |
        +--> deterministic CSV generation + checksums/manifests
        |
        +--> Snowflake RAW DDL + internal stage + fail-closed COPY SQL
        |
        +--> dbt RAW sources -> STAGING -> CORE -> MART
        |
        +--> MART.REINSURANCE_PERFORMANCE
        |
        +--> Snowflake Semantic View
        |       +--> server-side verify SQL
        |       +--> gated deploy SQL
        |
        +--> Cortex Agent -> managed MCP server
        |
        +--> Power BI / Excel XMLA consumer contract (feature-gated)
        |
        +--> direct-MART vs Semantic View concurrency benchmark
        |
        +--> manual Airflow orchestration
```

## Domain scope

The current model covers cedants, treaties, products, insured lives, policies, coverages, underwriting, gross and ceded premiums, claims, claim payments, claim reserves, and monthly exposure. The same YAML domain contract drives generation and physical table definitions so schema and data cannot silently drift.

## Quick start

```bash
python scripts/rga_testbed/generate_data.py --preset tiny --seed 42
python scripts/rga_testbed/validate_dataset.py --input artifacts/rga_testbed
python scripts/rga_testbed/generate_snowflake_ddl.py
python scripts/rga_testbed/generate_load_sql.py
python scripts/rga_testbed/generate_dbt_project.py
python scripts/rga_testbed/generate_semantic_view.py
python scripts/rga_testbed/generate_ai_integration.py
python scripts/rga_testbed/generate_microsoft_consumer_pack.py
python scripts/rga_testbed/generate_benchmark_pack.py
python scripts/rga_testbed/generate_airflow_dag.py
```

For a bounded developer run:

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

Monthly exposure can produce roughly 12x active-policy volume. The stress preset is therefore a target profile for distributed or partitioned generation, not a single-laptop promise.

## Business invariants

The generator enforces or derives policy-to-cedant/treaty relationships, insured/product relationships, positive premium economics, treaty-share-based cession, underwriting outcomes, claim chronology, gross-vs-ceded claim bounds, claim payment/reserve behavior, and active-policy monthly exposure.

## Snowflake physical layer

`generate_snowflake_ddl.py` creates `RGA_SYNTHETIC_TESTBED` by default with `RAW`, `STAGING`, `CORE`, `MART`, `SEMANTIC`, `AI`, and `AUDIT` schemas, the CSV file format/internal stage, RAW tables, and generation-audit table.

`generate_load_sql.py` generates PUT/COPY commands for every source entity. Loads use `ON_ERROR='ABORT_STATEMENT'`, capture generation and source-file metadata, and use `FORCE=FALSE` to avoid intentional duplicate reload behavior.

## dbt analytical layer

`generate_dbt_project.py` creates RAW source declarations, one STAGING view per entity, `DIM_CEDANT`, `DIM_TREATY`, `DIM_POLICY`, `FCT_PREMIUM`, `FCT_CLAIM`, `FCT_EXPOSURE`, and `MART.REINSURANCE_PERFORMANCE` at cedant + treaty + month grain. Premium, claim, and exposure facts are independently aggregated before joining to prevent fact-to-fact fan-out from inflating financial measures.

## Governed Semantic View

`generate_semantic_view.py` creates the Snowflake Semantic View YAML plus separate verification and create-or-alter deployment SQL. Governed metrics include total gross/ceded premium, gross/ceded claims, exposure, claim count, ceded loss ratio, and ceded premium rate. Verified query examples are stored with the semantic definition.

## AI: Cortex Agent + MCP

`generate_ai_integration.py` creates a Cortex Agent whose `cortex_analyst_text_to_sql` resource points to the exact same RGA Semantic View. It also creates a Snowflake-managed MCP server exposing that Agent as `CORTEX_AGENT_RUN`. The generated MCP contract deliberately does **not** expose `SYSTEM_EXECUTE_SQL`, keeping external AI clients behind the governed Agent/Semantic View boundary.

## Power BI + Excel

`generate_microsoft_consumer_pack.py` generates a shared Microsoft consumer contract, XMLA setup template, and parity checklist. The live consumption path is explicitly marked `private_preview_feature_gate` because governed Power BI and Excel access to Snowflake Semantic Views depends on the Snowflake Semantic Views XMLA Endpoint powered by AtScale being enabled in the target account.

The acceptance rule is stricter than connectivity: Power BI and Excel must use the governed semantic model and match Snowflake/AI results at the same dimensional grain and security context. Recreating `CEDED_LOSS_RATIO` or `CEDED_PREMIUM_RATE` in local DAX or spreadsheet formulas does not count as semantic parity.

## Performance benchmark

`generate_benchmark_pack.py` emits paired direct-MART and Semantic View queries for the same business questions. `run_snowflake_benchmark.py` adds guarded live execution with concurrency and iteration controls. It records query IDs, client latency, and Snowflake Query History telemetry including server elapsed/execution/compilation time, bytes scanned, cache percentage, queue time, partitions scanned, local/remote spill, execution status, and errors.

The runner intentionally does **not** invent per-query Snowflake credit attribution. Warehouse credit analysis should be performed at an appropriate warehouse/time-window level during live benchmarking.

Dry-run example:

```bash
python scripts/rga_testbed/run_snowflake_benchmark.py \
  --manifest rga-snowflake-data-platform/benchmarks/manifest.json \
  --mode both --concurrency 10 --iterations 3 --dry-run
```

Live execution additionally requires `--confirm-live` and Snowflake environment credentials.

## Guarded Snowflake execution

`execute_snowflake_sql.py` is the general live-account boundary. It refuses SQL execution without `--confirm`, supports credential-free `--dry-run` hashing/evidence, applies the `RGA_SYNTHETIC_PIPELINE` query tag, and keeps credentials in environment variables.

## Airflow orchestration

`generate_airflow_dag.py` generates the manual `rga_synthetic_semantic_pipeline` DAG. The flow is generation -> contracts -> Snowflake bootstrap -> RAW load -> dbt build -> Semantic View verification -> optional Semantic View deployment. It has no schedule, no catchup, one active run, and semantic deployment defaults to false behind a serialization-safe named `ShortCircuitOperator` gate.

## Current verification boundary

Repository CI certifies deterministic generation, dataset integrity, Snowflake DDL/load SQL, dbt scaffolding, Semantic View contracts, governed Cortex Agent/MCP contracts, feature-gated Power BI/Excel consumer artifacts, benchmark planning/fail-closed behavior, generated Airflow syntax, and guarded Snowflake executor behavior.

**Not yet claimed:** live Snowflake object creation and RAW load, live dbt execution, server-side Semantic View deployment verification, live benchmark numbers, live Cortex Agent/MCP execution, or Power BI/Excel XMLA connection evidence. Those require the target Snowflake account, credentials, and for Microsoft clients the XMLA preview capability.

## Next engineering slices

- CDC/change-event and failure fixtures for policies, premiums, and claims;
- live Snowflake + dbt certification evidence;
- live concurrency runs at 1/5/10/25/50 users with Query History evidence;
- Cortex Agent/MCP runtime smoke tests;
- Power BI and Excel XMLA parity evidence once the endpoint is available.
