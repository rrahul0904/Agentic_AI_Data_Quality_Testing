# Beyond-Altimate roadmap

Wave 1 completes the local control-plane integration: deterministic discovery,
dbt/Airflow intelligence, quality/reconciliation evidence, asset graph,
permissions, ShiftForge invocation, and Snowflake-free E2E fixtures.

Next waves are deliberately incremental:

1. SQLGlot rule expansion, multi-model column lineage, and schema-aware metadata search.
2. Warehouse adapters for Snowflake, PostgreSQL, Oracle, DuckDB, and usage history.
3. Cross-warehouse row/hash/schema diff, quality trends, anomaly detection, and asset health.
4. dbt test generation, Airflow failure/SLA/backfill analysis, and governed remediation proposals.
5. ShiftForge canonical IR, more target adapters, FinOps, RBAC, PII access analysis, MCP, and TUI.

External credentials and services remain optional; every unavailable integration is
reported as `SKIP` rather than inferred as successful.
