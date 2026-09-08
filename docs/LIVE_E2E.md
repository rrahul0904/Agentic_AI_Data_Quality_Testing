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
