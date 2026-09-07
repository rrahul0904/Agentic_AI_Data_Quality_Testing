# Current-state audit

Audit date: 2026-09-07. This records the recovered baseline and the first
integrated implementation wave.

| Component | Verified state | Tests / evidence |
|---|---|---|
| Root UMA/control plane | 101 tests passing; registry, CLI/API, discovery, dbt/Airflow graph, quality store, SQL review, metadata index, ShiftForge adapter | `pytest tests integration/e2e-tests`, Ruff |
| Local Data Harness | Recovered v0.2; static dbt/Airflow/SQL/PII/Snowflake-quality tools | 10 npm tests, quality 4/4, demo pass |
| ShiftForge | Recovered standalone v0.1; deterministic BigQuery→Redshift engine and root structured adapter | 6 tests pass via `PYTHONPATH=src` |
| Hospitality | 144 Oracle tables, 157 PostgreSQL tables, 18 feeds, 40 ingestion jobs, 46 base DAGs plus reservation aliases, 70 dbt models, 4 snapshots, 49 parsed tests | hospitality tests pass; dbt parse pass with local placeholder env; Airflow DagBag 55 DAGs/0 errors |

## Implemented in the current wave

- ToolRegistry registration for platform, dbt, Airflow, reconciliation, graph,
  SQL, metadata, doctor, and migration operations.
- CLI (`ade` and `agentic-data-platform`) and FastAPI `/tools` interface.
- Analyst/Plan/Builder actor-mode enforcement.
- Tolerance-aware reconciliation and local SQLite quality evidence.
- Cross-system graph from source DDL, Airflow AST, dbt manifest, and logical RAW mappings.
- SQLGlot review rules and first-version projection/column lineage.
- Common read-only warehouse facade over existing typed connectors.
- Six reservation dbt assets, modular hospitality framework, local runner,
  reconciliation, failure callback, and reservation DAG aliases.
- Integration tests, demo script, root Makefile, CI workflow, parity matrix, and roadmap.

## External status

- Docker daemon: `SKIP` when unavailable.
- Snowflake live credentials: `SKIP` unless configured.
- Real Oracle service: `SKIP`; simulated Oracle remains local.

## Remaining gaps

Deep Snowflake FinOps/RBAC/history, full multi-model column lineage, advanced
quality anomaly detection, dbt test generation, Airflow operational failure
analysis, MCP/TUI/provider integrations, and autonomous remediation remain
subsequent roadmap waves.
