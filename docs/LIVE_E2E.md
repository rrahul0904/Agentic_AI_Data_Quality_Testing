# Live E2E verification

Local proving-ground execution is intentionally separate from live external acceptance. A deterministic scenario may prove orchestration, evidence, RCA, approval, verification and certification logic, but it never counts as a real Snowflake, Airflow or LLM invocation.

## Snowflake

Configure `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, and either `SNOWFLAKE_PASSWORD` or `SNOWFLAKE_PRIVATE_KEY_PATH`. `SNOWFLAKE_ROLE` is optional.

Run `make snowflake-live-e2e`.

The check performs a real login/query, creates session-scoped temporary RAW-like objects, uploads a CSV through a temporary stage, executes a real `COPY INTO`, records Snowflake query IDs, and reconciles row count and amount.

## dbt on Snowflake

Set the Snowflake variables above plus `ADE_DBT_LIVE_MUTATION_APPROVED=true`, then run `make dbt-live-e2e`.

The gate creates an isolated temporary schema, executes dbt seed/build against real Snowflake, materializes a real incremental `merge` model, changes upstream seed data, runs a selective `dbt build --select fact_payment`, executes dbt tests, verifies the final count/amount in Snowflake, marks the isolated asset CERTIFIED, and drops the schema.

## Airflow


Deploy the repository's `hospitality_agentic_failure_probe` DAG. Configure `ADE_AIRFLOW_BASE_URL`, authentication, and explicitly set `ADE_AIRFLOW_LIVE_MUTATION_APPROVED=true`.

Run `make airflow-live-e2e`.

The check triggers the dedicated probe once with an intentional failure, verifies the failed DAG run, then triggers it again without the defect and verifies recovery. It never targets a business DAG.

## Real LLM agent

Configure a supported provider credential plus `ADE_LIVE_AGENT_MODEL`, then run `make agent-live-e2e`. The live model receives only `sql_classify`, must invoke it, receives the governed deterministic result, and must finish a second provider turn.

## GitHub Actions

`.github/workflows/live-e2e.yml` is manually dispatched and intentionally fails closed if required secrets are absent. Final COMPLETE status requires this live workflow to be green.

## Advanced Snowflake/Cortex capabilities

The advanced capability wave has a separate protected workflow:

`.github/workflows/ade-advanced-live-certification.yml`

Dispatch it manually against the GitHub environment `ade-advanced-live`. The workflow installs the Snowflake CLI only for the live job and writes structured evidence to:

`artifacts/advanced-live-certification.json`

Supported components are:

- `semantic`: DESCRIBE a real Snowflake semantic view and ingest its dimensions/facts/metrics/verified queries into a temporary ADE semantic registry.
- `analyst`: send a real Cortex Analyst request against one or more configured semantic views.
- `cortex-agent`: describe a real Cortex Agent object.
- `cortex-agent-run`: execute a real Cortex Agent request.
- `model-registry`: list real Snowflake Model Registry models and optionally versions for one configured model.
- `ai-workflow`: execute a read-only ADE workflow using current Snowflake AI functions against literal test input.
- `notebook`: execute a configured Snowflake notebook through `snow notebook execute`.
- `streamlit`: generate and deploy an isolated ADE Streamlit certification app.
- `app-runtime`: generate and deploy an isolated App Runtime app and optionally probe its `/healthz` endpoint.

The default dispatch is read-only:

`semantic,model-registry,ai-workflow`

The following components are treated as externally mutating and fail closed unless the manual dispatch sets `allow_mutations=true`:

- `cortex-agent-run`
- `notebook`
- `streamlit`
- `app-runtime`

Missing credentials, object identifiers, privileges, CLI availability, or explicit mutation approval are reported as `BLOCKED_EXTERNAL`. They are never converted into a PASS.

Required credential secrets for the protected environment are:

- `ADE_SNOWFLAKE_ACCOUNT`
- `ADE_SNOWFLAKE_USER`
- `ADE_SNOWFLAKE_PASSWORD`
- `ADE_SNOWFLAKE_ACCOUNT_URL` and `ADE_SNOWFLAKE_TOKEN` when Cortex REST APIs are selected

Non-secret database/schema/warehouse/object identifiers should be stored as GitHub environment variables using the names documented in `.env.example`.

Local CI certifies request construction, policy boundaries, adapters, generated project manifests, notebook/file fingerprints, hosted runner behavior and regression safety. It does **not** substitute for this live workflow.
