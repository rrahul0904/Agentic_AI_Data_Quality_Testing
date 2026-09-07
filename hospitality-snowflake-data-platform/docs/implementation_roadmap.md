# Implementation roadmap

## Implemented in wave 1

- 144-table Oracle and 157-table PostgreSQL physical DDL catalogs
- deterministic relational CDC export generators and 18 multi-scale file feeds
- 40 ingestion DAGs and 6 orchestration DAGs
- Snowflake schemas, warehouses, file formats, internal stage, raw/audit/quarantine tables, stream, and roles
- 41 dbt SQL models, 4 snapshots, reusable macros, source freshness, and core KPI tests
- 11 dashboard queries, streaming file checks, Docker Compose, Make targets, and local tests

## Next hardening wave

1. Add native chunked extraction adapters using OracleHook and PostgresHook with persisted high-watermarks.
2. Add named per-feed raw tables or header-driven CSV object construction instead of positional CSV payloads.
3. Expand restaurant, spa, events, refunds, reviews, promotions, support, fraud, and maintenance facts and marts.
4. Persist COPY validation errors and every quality result in the Snowflake audit schemas.
5. Add dbt run-artifact ingestion, alert routing, SLA dashboards, and OpenLineage emission.
6. Run Docker/Airflow integration tests and document row-count, duration, and warehouse-credit evidence.

