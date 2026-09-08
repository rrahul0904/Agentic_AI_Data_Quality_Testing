# Agentic AI Data Quality Testing

**Agentic Data Engineering OS** is a local-first control plane for deterministic data-platform discovery, SQL intelligence, dbt and Airflow lineage, impact analysis, data-quality evidence, source-target reconciliation, warehouse readiness, and migration engineering.

```text
                         Operator Console
                               |
                         FastAPI / v1
                               |
                         ToolRegistry
              +----------------+----------------+
              |                |                |
          SQL / dbt        Airflow / DQ      ShiftForge
              |                |                |
              +----------------+----------------+
                               |
                     Cross-system asset graph
                               |
              Oracle + Postgres + Files
                               |
                           Snowflake
```

## Working operator-console demo

The v0.4 demo uses real repository metadata and deterministic local evidence. It **does not require Docker, Snowflake credentials, or a live Oracle service**.

```bash
git clone https://github.com/rrahul0904/Agentic_AI_Data_Quality_Testing.git
cd Agentic_AI_Data_Quality_Testing
./scripts/setup-demo.sh
source .venv/bin/activate
make demo-ui
```

Open:
- Operator console: `http://127.0.0.1:3000`
- FastAPI: `http://127.0.0.1:8001`
- API docs: `http://127.0.0.1:8001/docs`

The console exposes **Overview, Assets, Lineage, SQL Intelligence, dbt, Airflow, Data Quality, Reconciliation, Migration, Warehouses, Runs/Evidence, and a deterministic Agent panel**. FinOps and Governance are visibly marked partial rather than filled with invented live data.

See `docs/DEMO_WALKTHROUGH.md` for the presentation flow.

## Enterprise proving ground

The hospitality workload currently contains 144 Oracle logical tables, 157 PostgreSQL logical tables, 18 file feeds, 40 metadata-driven ingestion jobs, 55 Airflow DAGs including aliases, 70 dbt models, 4 snapshots, parsed dbt tests, static Snowflake DDL, and deterministic dirty-data fixtures.

Counts shown in the product are calculated by backend tools at runtime; the frontend does not hardcode them.

## Components

- `src/agentic_data_platform` — governed Python control plane, v1 API, ToolRegistry, permissions, SQLGlot intelligence, dbt/Airflow intelligence, cross-system graph, warehouse facade, quality store, and reconciliation.
- `apps/web` — dense Next.js operator console driven by the v1 API.
- `local-data-harness` — recovered Node harness with static dbt/Airflow/SQL/PII/Snowflake quality tools.
- `shiftforge` — standalone deterministic dbt migration/conversion engine integrated through structured Python calls.
- `hospitality-snowflake-data-platform` — enterprise reference workload.
- `integration/e2e-tests` — Snowflake-free vertical-slice verification.

## Verification

```bash
make unit-test
make integration-test
make lint
make quality
make shiftforge-test
make frontend-typecheck
make frontend-build
```

The CLI engineering demo remains available with `make demo`.

## Local versus live

The demo labels simulated paths as `LOCAL SIMULATION`. Live Snowflake and Oracle checks remain `SKIP` until credentials/services are configured. The platform never converts an unavailable live integration into a fake PASS.

## Safety

Deterministic tools are the source of truth. Analyst and Plan modes cannot invoke mutation-risk tools; Builder operations remain governed by risk, environment, and explicit approval. Operator-console convenience endpoints invoke ToolRegistry in Analyst mode rather than bypassing it.

## Current limits

Full multi-model lineage, deep Snowflake FinOps/RBAC/query-history intelligence, large-scale live cross-warehouse data diff, advanced Airflow runtime root-cause analysis, MCP/skills/provider integrations, trace playback, production TUI, and autonomous remediation remain roadmap work.

Track parity in `specs/ALTIMATE_PARITY_MATRIX.md` and `specs/BEYOND_ALTIMATE_ROADMAP.md`. Registered deterministic tools are summarized in `specs/TOOL_CATALOG.md`.


## Acceptance and verification

The `altimate-full-parity` branch exposes a deterministic Data Engineering OS rather than a narrative-only agent. The implementation includes SQL/dbt/lineage/data-diff/quality/migration/FinOps/governance/session/provider/MCP/tracing capabilities plus a deep Airflow 2/3 control plane.

Current product-level targets:
- 22 first-class model-provider configurations, with live auth reported honestly.
- 13 warehouse targets including MongoDB; external live connections are optional.
- 32 built-in skills: the 21 pinned Altimate-compatible skills plus 11 Airflow/pipeline operations skills.
- Airflow 3 Assets, Task SDK compatibility, mapping, deferrables, bundles, deadlines, security, XCom, capacity, OpenLineage and version-aware REST operations.
- A dense operator console whose pages use real `/api/v1` responses rather than roadmap placeholders.

Run the bounded local acceptance suite with:

```bash
make verify
```

Run the master deterministic demo with:

```bash
bash scripts/demo-full-platform.sh
```

Live Snowflake, Oracle, cloud Airflow, GitHub/GitLab delivery and cloud LLM integrations are never fabricated. Where credentials/services are absent, the corresponding adapter remains implemented and locally tested while runtime status is `SKIP_EXTERNAL`.
