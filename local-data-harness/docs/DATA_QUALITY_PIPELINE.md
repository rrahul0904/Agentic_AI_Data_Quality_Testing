# Airflow + Snowflake + dbt Data Quality Pipeline

LDH v0.2 adds a layered testing model so the project remains useful with zero credentials while also supporting live integration checks.

## Layers

1. **Static gate** — Airflow Python compile/DAG conventions, dbt schema/test coverage, SQL quality rules, Snowflake config presence.
2. **Integration gate** — Airflow CLI DAG parsing, `dbt parse`, `dbt test`, and a read-only Snowflake health query.
3. **Execution gate** — builder mode can invoke `dbt build` and `airflow dags test`, because those can write or trigger external work.

## Commands

```bash
npm test
npm run quality
node src/cli/index.mjs quality --cwd examples/demo --level static
node src/cli/index.mjs quality --cwd examples/demo --level integration
node src/cli/index.mjs airflow --cwd examples/demo
node src/cli/index.mjs dbt-test --cwd /path/to/dbt/project
node src/cli/index.mjs snowflake --cwd /path/to/project
```

For builder-only execution:

```bash
node src/cli/index.mjs ask --mode builder --cwd /path/to/project "run dbt build"
node src/cli/index.mjs ask --mode builder --cwd /path/to/project "test airflow dag my_dag"
```

## Snowflake auth

LDH supports `SNOWFLAKE_CONNECTION_NAME` (for a Snowflake `connections.toml` definition) or environment variables. Secrets are passed to the Snowflake connector process through the environment and are not emitted in LDH results.

## Airflow DAG pattern

`examples/demo/airflow/dags/data_quality_pipeline.py` shows an Airflow DAG that runs `dbt test` and then a Snowflake connection health query through `SnowflakeHook`.

## Quality policy

Create `.ldh/quality.json`:

```json
{
  "require": { "airflow": true, "dbt": true, "snowflake": false },
  "requireLive": { "airflow": false, "dbt": false, "snowflake": false },
  "maxSqlIssues": 5
}
```

This lets local developer checks skip unavailable live systems while CI/prod can set `requireLive` to true.
