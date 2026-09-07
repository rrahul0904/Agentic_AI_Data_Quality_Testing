# ADE Test Control Tower — Full Project Specification

**Version at time of writing:** `0.6.0-horizon-a`
**Source of truth for status claims:** `docs/IMPLEMENTATION_STATUS.md` (capability matrix, test-by-test). This document is structural/reference; that one is the honest scorecard.
**Client-provided target spec (not yet fully built):** `~/Downloads/AGENTIC_AI_DATA_QUALITY_TECHNICAL_ARCHITECTURE_V2.md`, `~/Downloads/MASTER IMPLEMENTATION PROMPT...md`

---

## 1. Product summary

A control-plane tool that runs real dbt and Airflow pipelines, applies a
deterministic quality-rule engine to their output, and — only where a
deterministic lineage walk can't resolve an ambiguity — escalates to an
LLM agent to reason over the same evidence. Every conclusion an agent makes
is verified against real evidence before it's trusted; nothing is asserted
on an LLM's say-so alone.

Two build horizons, by design:
- **Horizon A** (this codebase, in progress): a real, working vertical
  slice. Everything in sections 2-9 below.
- **Horizon B** (not started, architecture-only): PostgreSQL/pgvector,
  Temporal, Kafka, a full Next.js enterprise UI, production warehouse
  adapters, the full ~11-agent roster, Kubernetes/multi-cloud deployment.
  Estimated separately (`~/Downloads/AGENTIC_AI_DQ_PLATFORM_PLAN_AND_COST_ESTIMATE.md`).

---

## 2. Architecture

```
Browser (vanilla JS SPA, backend/app/static/)
  Dashboard -> dbt/Airflow project detail -> Quality/Certifications/Incidents -> RCA investigate modal
        │ HTTP
        ▼
FastAPI backend (backend/app/main.py)
  routers: dbt_projects | airflow_projects | runs | quality | investigation
        │
        ├─ provisioning.py ──── creates per-project venvs (dbt-core+adapter)
        │                       and per-project Airflow instances (own
        │                       venv, metadata DB, webserver/scheduler/
        │                       triggerer on a free port)
        │
        ├─ dbt_runner.py / dbt_cloud_client.py / airflow_client.py
        │       real subprocess/API execution against dbt-core, dbt Cloud,
        │       and Airflow's REST API
        │
        ├─ lineage.py ──── dbt manifest / Airflow task graph -> {nodes,edges}
        │
        ├─ adapters/duckdb_adapter.py ──── real SQL execution against a
        │       project's DuckDB warehouse file (only live adapter)
        │
        ├─ quality_rule_engine.py ──── canonical QualityRule -> SQLGlot-
        │       compiled SQL -> executed via an adapter -> PASS/FAIL/ERROR
        │
        ├─ certification.py ──── derives CERTIFIED/AT_RISK/FAILED/UNKNOWN
        │       from rule results, project-scoped, fully explainable
        │
        ├─ grounding.py ──── deterministic claim-status machine (no LLM)
        │
        ├─ rca.py ──── walks captured lineage; 0 upstream failures ->
        │       UNVERIFIED, 1 -> deterministic grounded claim, >1 ->
        │       escalates to:
        │
        ├─ rca_agent.py + llm_gateway.py ──── the one real LLM agent;
        │       whitelist-verifies every dataset/evidence citation before
        │       trusting it; final status still computed by grounding.py
        │
        └─ remediation.py ──── propose -> human-approve -> apply (scoped,
                unique-match file patch, confined to the project directory)
        │
        ▼
SQLite (backend/data/testctl.db) — Postgres-compatible schema, not yet migrated
```

---

## 3. Data model

### Carried forward from v0.1/v0.2 (`backend/app/models.py`)

| Model | Purpose |
|---|---|
| `DbtProject` | A dbt workspace: `local` (own venv+adapter) or `cloud` (dbt Cloud API). |
| `DbtJob` | A saved `--select` string (local) or synced dbt Cloud job. |
| `AirflowProject` | A dedicated, auto-provisioned Airflow instance (own venv/metadata DB/processes). |
| `AirflowDagRef` | A DAG discovered inside an `AirflowProject`, with cached lineage. |
| `TestRun` | One orchestrated run: N dbt jobs + M Airflow DAGs, concurrent. |
| `DbtJobRun` / `DbtTestResult` | Per-job dbt execution + per-node test result. |
| `AirflowDagRun` / `AirflowTaskResult` | Per-DAG execution + per-task result. |
| `Artifact` | Raw JSON evidence blobs (`run_results.json`, Airflow API responses, etc.). |

### Added for the quality/agent layer (`backend/app/models_quality.py`)

| Model | Purpose |
|---|---|
| `BusinessConcept` | A named business definition (e.g. "Net Revenue"), criticality tier. |
| `QualityContract` | Versioned, owned contract for one dataset, links to a `BusinessConcept`. |
| `QualityRule` | Canonical, platform-independent rule: `dimension`, `rule_type`, `target_table`/`target_column`, `expression` (JSON, rule-type-specific), `tolerance_type/value`, `severity`. |
| `QualityRuleRun` | One execution of one rule: `status`, `measured_value`, `compiled_sql`, `dialect`. |
| `Evidence` | A small, typed, provenance-carrying fact (`evidence_type`, `source_type`, `dataset_ref`, `value`, `query_text`). |
| `AgentClaim` | A claim (from a deterministic walk or an LLM agent): `claim_type`, `statement`, `status`, `generated_by`. |
| `ClaimEvidenceLink` | Links a claim to evidence, `SUPPORTING`/`CONTRADICTORY`. |
| `LLMCallLog` | AI cost accounting: provider, model, tokens in/out, per claim. |
| `Incident` | Auto-created on a P1 rule failure. |
| `RemediationProposal` | `target_file`, `proposed_change` (JSON find/replace), `status` (PROPOSED→APPROVED→APPLIED). |
| `Certification` | Derived status for a dataset, scoped by `dbt_project_id` + `dataset_ref`, with an explainable `reason`. |

**Rule types implemented:** `not_null`, `unique`, `accepted_values`, `row_count_reconciliation`, `aggregate_reconciliation`, `custom_sql` (escape hatch — arbitrary SQL returning a `failing_count` column).

---

## 4. API reference

All routes are `/api/...`, FastAPI, OpenAPI docs auto-served at `/docs`.

**dbt projects** (`routers/dbt_projects.py`)
`POST /dbt-projects` · `GET /dbt-projects` · `GET /dbt-projects/{id}` · `POST /dbt-projects/{id}/jobs` · `POST /dbt-projects/{id}/sync-cloud-jobs` · `GET/POST /dbt-projects/{id}/lineage[/refresh]`

**Airflow projects** (`routers/airflow_projects.py`)
`POST /airflow-projects` · `GET /airflow-projects` · `GET /airflow-projects/{id}` · `POST /airflow-projects/{id}/start|stop` · `POST /airflow-projects/{id}/dags` (upload) · `POST /airflow-projects/{id}/dags/sync` · `GET /airflow-projects/{id}/dags/{dag_id}/lineage`

**Runs** (`routers/runs.py`)
`POST /runs` (dbt_project_id/dbt_job_ids + airflow_project_id/airflow_dag_ids) · `GET /runs` · `GET /runs/{id}`

**Quality** (`routers/quality.py`)
`POST/GET /business-concepts` · `POST/GET /quality-contracts[/{id}]` · `POST/GET /quality-rules[/{id}]` · `GET /quality-rules/{id}/compile?dialect=` · `POST /quality-rules/{id}/execute` · `GET /quality-rules/{id}/runs` · `POST /dbt-projects/{id}/quality/recheck` (execute all + recertify all, one call) · `GET /incidents` · `POST /certifications/evaluate` · `GET /certifications`

**Investigation** (`routers/investigation.py`)
`POST /rca?dbt_project_id=&dataset_ref=` · `GET /agent-claims[/{id}]` · `POST/GET /remediation-proposals` · `POST /remediation-proposals/{id}/approve` · `POST /remediation-proposals/{id}/apply`

---

## 5. Services reference

| File | Real / stub | What it does |
|---|---|---|
| `provisioning.py` | Real | Creates isolated dbt venvs and full Airflow instances; start/stop lifecycle. |
| `dbt_runner.py` | Real | `dbt build` subprocess, parses `run_results.json`/`manifest.json`. |
| `dbt_cloud_client.py` | Real, untested live | dbt Cloud Admin API v2 client — no credentials available to exercise it. |
| `airflow_client.py` | Real | Airflow REST API client (trigger/poll DAG runs, list DAGs, task deps). |
| `lineage.py` | Real | dbt manifest + Airflow task graph → `{nodes, edges}`. |
| `adapters/duckdb_adapter.py` | Real | Only live `DataPlatformAdapter`. |
| `adapters/base.py` | Interface only | Snowflake/BigQuery/Redshift/Databricks have no implementation. |
| `quality_rule_engine.py` | Real | SQLGlot compiler + rule evaluation logic. |
| `certification.py` | Real | Derives status from rule results, project-scoped. |
| `grounding.py` | Real | Deterministic claim-status machine — **not an LLM call, by design.** |
| `rca.py` | Real | Deterministic lineage-walk RCA; escalates to `rca_agent` on ambiguity. |
| `rca_agent.py` | Real, not live-called | The one LLM agent. Whitelist-verifies all citations. No `OPENAI_API_KEY` configured → never actually called OpenAI. |
| `llm_gateway.py` | Real, not live-called | Provider-neutral ABC + `OpenAIGateway`. Same caveat as above. |
| `remediation.py` | Real | Scoped find/replace, confined to project dir, approval-gated. |
| `orchestrator.py` | Real | Concurrent multi-job/multi-DAG `TestRun` execution (v0.2). |

---

## 6. UI structure (`backend/app/static/`)

Vanilla HTML/JS SPA, hash-routed, Tailwind via CDN, no build step, no
component library.

| Route | Shows |
|---|---|
| `#/` | Dashboard: dbt projects \| Airflow projects, create wizards |
| `#/dbt/{id}` | Jobs, lineage (hand-rolled SVG), Quality Rules table + execute, Certifications + Investigate (RCA modal) + Remediation propose/approve/apply |
| `#/airflow/{id}` | DAGs, lineage, upload/sync, start/stop, multi-select run |
| `#/runs`, `#/runs/{id}` | Run history and detail |
| `#/incidents` | Global incident list |

Assessment against the client spec's UI bar: avoids the explicitly-banned
anti-patterns (no gradients/fake scores/sparkles/marketing chrome), but is
not the "serious enterprise Next.js platform" the spec asks for — it's a
functional internal console, unstyled by any design system, with at least
one raw-JSON input field (`QualityRule.expression`) that assumes an
engineer, not a business user.

---

## 7. Directory layout

```
dbt-airflow-testing-platform/
├── backend/app/
│   ├── main.py, config.py, db.py
│   ├── models.py, models_quality.py, schemas.py, schemas_quality.py
│   ├── routers/{dbt_projects,airflow_projects,runs,quality,investigation}.py
│   ├── services/
│   │   ├── provisioning.py, dbt_runner.py, dbt_cloud_client.py, airflow_client.py
│   │   ├── lineage.py, quality_rule_engine.py, certification.py
│   │   ├── grounding.py, rca.py, rca_agent.py, llm_gateway.py, remediation.py
│   │   ├── orchestrator.py
│   │   └── adapters/{base,duckdb_adapter}.py
│   └── static/{index.html,app.js,styles.css}
├── backend/tests/            # 40 pytest tests
├── dbt_demo_project/          # v0.1 demo (dbt's own starter-project defect)
├── revenue_demo/               # spec's "Revenue Quality Certification" scenario
├── airflow_dags/               # example DQ pipeline DAG
├── scripts/                    # setup/run scripts + run_revenue_demo.py
└── docs/
    ├── ARCHITECTURE.md, CURRENT_STATE.md, RUNBOOK.md
    ├── IMPLEMENTATION_STATUS.md      ← honest capability matrix, read this first
    ├── PROJECT_OVERVIEW_FOR_HANDOFF.md
    └── FULL_PROJECT_SPEC.md          ← this file
```

---

## 8. Running it

```bash
scripts/setup_backend_venv.sh
scripts/run_backend.sh              # :8000
python3 scripts/run_revenue_demo.py # full scripted E2E demo
cd backend && pytest tests/ -q      # 40 tests
```

To enable the LLM agent: add `OPENAI_API_KEY` to `backend/.env` (see
`docs/RUNBOOK.md` → "Enabling the RCA agent" for the exact repro steps).

---

## 9. Explicit non-goals of this codebase (Horizon B, not started)

PostgreSQL/pgvector · Temporal · Kafka · object storage/Redis · Next.js/
React/TypeScript UI · Snowflake/BigQuery/Redshift/Databricks execution ·
MWAA/Composer/Astronomer · the other ~10 named agents · Context
Intelligence · Transformation Intelligence · hash/bucket reconciliation ·
Cost/Scale/Optimization/Change Intelligence · OIDC/SAML/RBAC · OpenTelemetry/
Prometheus/Grafana/Sentry · Kubernetes/Helm/Terraform · multi-tenancy ·
policy engine · project deletion.

These are documented as future scope in the cost-estimate document, not
silently dropped.
