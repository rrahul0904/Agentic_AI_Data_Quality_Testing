# Quality engine

Quality checks return explicit `PASS`, `FAIL`, or `ERROR` with observed and
expected values. Row counts, aggregates, nulls, duplicates, primary keys, and
freshness support absolute or percentage tolerances. Local evidence persists
to SQLite tables `quality_runs`, `quality_results`,
`reconciliation_results`, and `pipeline_runs`; Snowflake uses the equivalent
`AUDIT.DATA_QUALITY_RESULTS` contract.
