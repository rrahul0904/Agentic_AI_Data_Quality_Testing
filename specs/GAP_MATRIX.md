# Gap matrix

| Capability | Status | Evidence / next step |
|---|---|---|
| Root tests and lint | DONE | 101 tests; Ruff clean |
| LDH recovery and static quality | DONE | v0.2, 10 tests, quality 4/4 |
| ShiftForge recovery and baseline conversion | DONE | 6 tests; engine preserved |
| ShiftForge structured adapter | DONE | Root adapter and integration tests |
| Hospitality source inventories | DONE | 144 Oracle / 157 PostgreSQL / 18 feeds |
| Hospitality reservation dbt slice | DONE | 70 models; six critical assets; parse passes |
| Hospitality Airflow framework | DONE | Local runner, audit, quality, reconciliation, aliases; DagBag clean |
| Tool registration | DONE | 40+ registry definitions including migration and SQL tools |
| CLI/API exposure | DONE | CLI subcommands and `/tools` endpoint |
| Actor permissions | DONE | Analyst/Plan deny mutation-risk tools |
| dbt manifest graph | DONE | Summary, traversal, lineage, impact, tests, failures |
| Airflow intelligence | PARTIAL | Static inventory/task/dependency analysis; runtime failure/SLA analysis pending |
| Cross-system asset graph | DONE | Source/Airflow/RAW/dbt/mart graph and impact |
| Reconciliation | DONE | Row count, keys, nulls, duplicates, freshness, aggregates |
| Local quality store | DONE | SQLite quality and reconciliation evidence |
| SQL AST review | DONE | SQLGlot findings for safety/performance baseline |
| Column lineage | PARTIAL | Projection-level first version; multi-model expansion pending |
| Warehouse facade | PARTIAL | Snowflake typed connector and common facade; other live adapters pending |
| Metadata index | DONE | SQLite asset/column search and PII flags |
| Integration E2E | DONE | 7 local vertical-slice tests; 101 root tests total |
| Demo / Makefile / CI | DONE | Local demo, developer commands, GitHub Actions workflow |
| Deep FinOps / RBAC / MCP / TUI | NOT STARTED | Subsequent waves |
| Live Snowflake / Docker / Oracle | BLOCKED EXTERNAL | Credentials/daemon/service unavailable |
