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
  46 base Airflow DAGs plus reservation aliases, and a 70-model/4-snapshot
  reservation-oriented dbt project.
- `integration/e2e-tests` — Snowflake-free vertical-slice tests.

## Working local demo

The basic demo does **not** require Docker, Snowflake credentials, or a live
Oracle database. It runs the platform in local simulation mode and explicitly
reports unavailable live integrations as `SKIP`.

```bash
git clone https://github.com/rrahul0904/Agentic_AI_Data_Quality_Testing.git
cd Agentic_AI_Data_Quality_Testing

./scripts/setup-demo.sh
source .venv/bin/activate
make demo
```

The demo exercises:

1. environment doctor checks,
2. hospitality source/platform inventory,
3. static Airflow health,
4. dbt lineage for `fact_reservation`,
5. cross-system impact for `stg_oracle_reservation`,
6. an intentional source/target reconciliation failure,
7. the Local Data Harness quality gate,
8. a structured ShiftForge migration inventory,
9. final platform health.

For verification rather than presentation:

```bash
make unit-test
make integration-test
make lint
make quality
make shiftforge-test
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

The SQLGlot lineage implementation is a first production-oriented pass, but
full multi-model column lineage, deep Snowflake FinOps/RBAC/history,
large-scale warehouse-executed data diff, MCP/TUI/provider integrations, and
autonomous remediation are still roadmap work. See
`specs/ALTIMATE_PARITY_MATRIX.md` and `specs/BEYOND_ALTIMATE_ROADMAP.md`.
