# Integration surface

The `e2e-tests` suite exercises the local, Snowflake-free vertical slice across
the root control plane and the hospitality proving ground. It reads committed
DDL, Airflow source, dbt artifacts, and deterministic reconciliation fixtures.

Live Snowflake, Docker, and Oracle services are optional and are reported as
`SKIP` when their prerequisites are unavailable.
