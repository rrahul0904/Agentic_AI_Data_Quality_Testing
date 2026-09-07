# Agentic AI Data Quality Testing

An integrated, local-first Agentic Data Engineering OS. The control plane
provides deterministic discovery, dbt/Airflow lineage and impact analysis,
quality evidence, reconciliation, SQL review, and governed tool execution.

```text
                 Agentic Data Engineering OS
                              |
          +-------------------+-------------------+
          |                   |                   |
       UMA / LDH          Hospitality          ShiftForge
      control plane       proving ground      migration engine
          |                   |                   |
          +-------------------+-------------------+
                              |
              Asset graph + quality evidence
                              |
            Snowflake / Postgres / Oracle / DuckDB
```

## Components

- `src/agentic_data_platform` — governed Python control plane (`ade` and
  `agentic-data-platform`), registry, permissions, dbt/Airflow intelligence,
  graph, quality store, SQLGlot review, and warehouse facade.
- `local-data-harness` — recovered Node v0.2 local harness with static dbt,
  Airflow, SQL, PII, Snowflake configuration, and quality tools.
- `shiftforge` — recovered standalone Python migration engine. It remains
  independently usable and is callable through the root structured adapter.
- `hospitality-snowflake-data-platform` — deterministic enterprise workload
  with 144 Oracle tables, 157 PostgreSQL tables, 18 feeds, 40 ingestion jobs,
  46 Airflow DAGs, and a 70-model/4-snapshot reservation-oriented dbt project.
- `integration/e2e-tests` — Snowflake-free vertical-slice tests.

## Quickstart

```bash
make unit-test
make integration-test
make lint
make demo
```

Useful direct commands:

```bash
PYTHONPATH=src python -m agentic_data_platform.cli platform inventory \
  --project hospitality-snowflake-data-platform
PYTHONPATH=src python -m agentic_data_platform.cli dbt lineage fact_reservation \
  --project hospitality-snowflake-data-platform
PYTHONPATH=src python -m agentic_data_platform.cli platform impact stg_oracle_reservation \
  --project hospitality-snowflake-data-platform
PYTHONPATH=src python -m agentic_data_platform.cli reconcile row-count \
  --source-value 10000 --target-value 9998
```

`/tools` and `/tools/{tool_name}` on the FastAPI application expose the same
structured deterministic tools used by the CLI. The default API data store is
local SQLite; set `ADE_DATABASE_PATH` to select another path.

## Local versus live

The hospitality framework supports local simulation and a Snowflake execution
mode. Local tests never claim Snowflake work. Docker, live Snowflake, and live
Oracle are optional and report `SKIP` when unavailable. Credentials are read
from the environment and are never returned or committed.

## Safety

Tools are the source of truth: the model does not invent query results, graph
edges, migration findings, or quality status. Analyst and Plan modes cannot
invoke mutation-risk tools. Builder operations remain governed by risk,
environment, and explicit approval.

## Current limits

The first SQLGlot lineage pass is projection-level; deeper multi-model column
lineage, FinOps, live warehouse history, full MCP/TUI surfaces, and autonomous
remediation are subsequent roadmap waves. See `specs/ALTIMATE_PARITY_MATRIX.md`
and `specs/BEYOND_ALTIMATE_ROADMAP.md`.
