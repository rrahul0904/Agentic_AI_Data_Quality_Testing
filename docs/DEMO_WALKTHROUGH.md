# Demo Walkthrough — Agentic Data Engineering OS v0.4

## Setup

```bash
git clone https://github.com/rrahul0904/Agentic_AI_Data_Quality_Testing.git
cd Agentic_AI_Data_Quality_Testing
./scripts/setup-demo.sh
source .venv/bin/activate
make demo-ui
```

The demo uses **LOCAL SIMULATION**. Snowflake credentials, a live Oracle service, and Docker are not required. Unavailable live integrations are reported as `SKIP`, never `PASS`.

## Startup

- Operator console: http://127.0.0.1:3000
- FastAPI: http://127.0.0.1:8001
- API docs: http://127.0.0.1:8001/docs

`make demo-ui` seeds deterministic SQLite quality evidence, starts FastAPI and Next.js, verifies both endpoints, and keeps them running until Ctrl+C.

## Walkthrough

1. **Overview** — show runtime-derived Oracle/Postgres/file, Airflow, dbt, quality, migration, and live-integration state.
2. **Assets** — search `reservation`; rows come from the shared asset graph.
3. **Lineage** — trace `fact_reservation`, then `stg_oracle_reservation`; show impact severity.
4. **SQL Intelligence** — run the preloaded SELECT-star/CROSS-JOIN SQL; inspect rule findings and column-lineage status.
5. **dbt** — show manifest counts, test coverage, untested models, and documentation gaps.
6. **Airflow** — show the static AST inventory; DAG modules are not imported or executed.
7. **Data Quality** — show the seeded intentional row-count failure and clean PASS checks.
8. **Reconciliation** — compare 10,000 vs 9,998 (FAIL), then 10,000 vs 10,000 (PASS).
9. **Migration** — inspect real ShiftForge BigQuery → Redshift inventory/findings/blockers.
10. **Warehouses** — inspect adapter/driver/credential/simulation state; Snowflake is SKIP without credentials.
11. **Runs / Evidence** — show evidence-backed product state.
12. **Agent** — ask `What depends on stg_oracle_reservation?` and show the exact deterministic tool used.

## Known limitations

- Snowflake query history, FinOps, RBAC, and live warehouse metrics are still partial.
- Full multi-model column lineage is not complete.
- Airflow runtime root-cause analysis remains static/fixture-backed until a live Airflow service is configured.
- MCP, skills/providers, trace playback, production TUI, and autonomous remediation remain future waves.
