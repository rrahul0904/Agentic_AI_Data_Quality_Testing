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

The console exposes **Overview, Investigations, Agent, Assets, Lineage, SQL Intelligence, dbt, Airflow, Data Quality, Reconciliation, Migration, Warehouses, Runs/Evidence, Providers, Skills, Training, Governance, FinOps, and Settings/Doctor**. Investigations shows the 12-agent roster, delegation timeline, immutable evidence tiers, competing hypotheses, first divergence, blast radius, persisted mappings, selective recovery, human approval, verification, and per-asset certification. Credential-dependent values remain explicitly unavailable rather than being invented.

See `docs/DEMO_WALKTHROUGH.md` for the presentation flow.

## Enterprise proving ground

The hospitality workload currently contains 144 Oracle logical tables, 157 PostgreSQL logical tables, 18 file feeds, 40 metadata-driven ingestion jobs, **57 Airflow DAGs**, 70 dbt models, 4 snapshots, parsed dbt tests, static Snowflake DDL, deterministic dirty-data fixtures, business-level cross-DAG dependency chains, and a dedicated live failure/recovery probe DAG.

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
python scripts/parse_dbt.py
make test-unit
make test-integration
make test-airflow
make test-dbt
make test-providers
make test-agentic
make test-hospitality
make benchmark-agentic
make benchmark-airflow
make benchmark-lineage
make final-audit
```

The complete bounded acceptance suite is `make verify`. The flagship multi-agent flow is `make demo-agentic`; the Airflow control-plane demo is `make demo-airflow`.

## Local versus live

The deterministic proving ground is labeled `LOCAL_PROVING_GROUND` / `LOCAL_SIMULATION`; it is not presented as production execution. Live acceptance is implemented as separate fail-closed gates:

```bash
make snowflake-live-e2e
make dbt-live-e2e
make airflow-live-e2e
make agent-live-e2e
```

The GitHub workflow `.github/workflows/live-e2e.yml` performs a non-secret preflight and runs the external gates only when the required credentials and explicit mutation approvals are configured. Missing external configuration is reported as `BLOCKED_EXTERNAL`, never as PASS.

## Safety

Deterministic tools are the source of truth. Analyst and Plan modes cannot invoke mutation-risk tools; Builder operations remain governed by risk, environment, and explicit approval. Operator-console convenience endpoints invoke ToolRegistry in Analyst mode rather than bypassing it.

## Agentic investigation architecture

The investigation control plane has **12 explicit first-class roles**: Supervisor, Metadata, Business Context, Lineage, Transformation, Mapping, Quality/Test, Execution Planning, Evidence, RCA, Impact, and Remediation.

Agents reason and propose; governed deterministic tools measure, verify, and execute. The Supervisor branches dynamically from evidence—for example, a source→RAW divergence can skip Transformation analysis, while a dbt-layer divergence invokes it.

The deterministic failure corpus contains 18 scenarios. The verified implementation baseline produced 100% root-cause accuracy and 100% first-divergence accuracy with zero LLM tokens. Mutating recovery is separated from investigation by an explicit human-approval boundary, followed by selective execution, independent verification, and per-asset recertification.
## Acceptance and verification

The `altimate-full-parity` branch exposes a deterministic Data Engineering OS rather than a narrative-only agent. The implementation includes SQL/dbt/lineage/data-diff/quality/migration/FinOps/governance/session/provider/MCP/tracing capabilities plus a deep Airflow 2/3 control plane.

Current product-level targets:
- 22 first-class model-provider configurations, with live auth reported honestly.
- 13 warehouse targets including MongoDB; external live connections are optional.
- 32 built-in skills: the 21 pinned Altimate-compatible skills plus 11 Airflow/pipeline operations skills.
- Airflow 3 Assets, Task SDK compatibility, mapping, deferrables, bundles, deadlines, security, XCom, capacity, OpenLineage and version-aware REST operations.
- A dense operator console whose pages use real `/api/v1` responses with explicit unavailable states for credential-dependent services.

Run the bounded local acceptance suite with:

```bash
make verify
```

Run the master deterministic demo with:

```bash
bash scripts/demo-full-platform.sh
```

Live Snowflake, Oracle, cloud Airflow, GitHub/GitLab delivery and cloud LLM integrations are never fabricated. Where credentials/services are absent, the corresponding adapter remains implemented and locally tested while release status is `BLOCKED_EXTERNAL` or runtime status is `SKIP_EXTERNAL`, depending on the surface.
