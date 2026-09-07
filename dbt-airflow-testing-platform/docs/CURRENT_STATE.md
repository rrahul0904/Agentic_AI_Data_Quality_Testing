# Current State Audit (Phase 0)

Baseline for the Agentic AI Data Quality & Pipeline Assurance Platform build,
against the existing **ADE Test Control Tower v0.2**. Read alongside
`docs/ARCHITECTURE.md` and `docs/RUNBOOK.md`, which document v0.2 in full.

## What is already real (verified end to end, not mocked)

- FastAPI backend, SQLAlchemy ORM, SQLite persistence (Postgres-compatible
  schema style — no SQLite-specific types used in models).
- Real `dbt-core` execution: per-project isolated venvs, `dbt init`
  scaffolding, `dbt build`, `run_results.json`/`manifest.json` parsing into
  structured rows (`services/dbt_runner.py`).
- Real `dbt Cloud` API client (Administrative API v2): trigger/poll a job
  run, fetch that run's artifacts for per-test detail
  (`services/dbt_cloud_client.py`) — implemented against the documented API,
  **not yet exercised against a live account** (no credentials available).
- Real Airflow execution: per-project auto-provisioned Airflow instances
  (own venv, metadata DB, webserver/scheduler/triggerer), driven entirely
  through Airflow's REST API (`services/airflow_client.py`,
  `services/provisioning.py`).
- Lineage extraction: dbt manifest → `{nodes, edges}`; Airflow DAG task
  dependencies → `{nodes, edges}` (`services/lineage.py`).
- Multi-project, multi-job/DAG orchestration:
  `TestRun`/`DbtJobRun`/`AirflowDagRun` with concurrent execution
  (`services/orchestrator.py`).
- DuckDB (fully working, zero-config) and Snowflake (profile template wired,
  not live-tested — no credentials) local-mode adapters.
- Static vanilla-JS UI: project creation wizards, lineage graph rendering,
  multi-select run triggering, run detail view.

## What is partial

- "Evidence" today is informal: raw JSON blobs in an `Artifact` table
  (`run_results.json`, Airflow `dagRun`/`taskInstances` JSON, dbt Cloud run
  JSON) plus structured `DbtTestResult`/`AirflowTaskResult` rows. There is no
  `Evidence`/`EvidenceBundle` model, no evidence typing, no provenance tiering,
  and nothing links a claim to its evidence — because there are no claims yet.
- "Quality checks" today ARE dbt tests and Airflow task outcomes — there is
  no platform-independent `QualityRule` model or SQL compiler. Every check
  is whatever the dbt project or DAG already encodes; the platform cannot
  today generate or execute a quality rule that dbt/Airflow don't already
  define.
- Lineage is dbt/Airflow-only; there is no `LineageNode`/`LineageEdge`
  canonical model spanning both, and no OpenLineage-compatible identifiers.

## What is prototype-only / does not exist yet

- Business Context Intelligence, Business Concepts, Quality Contracts.
- Evidence Intelligence, Claim/Evidence Grounding Gateway.
- Any agent (Context, Transformation, Quality, Evidence, RCA, or otherwise) —
  there is no LLM integration anywhere in the codebase today.
- Source-to-target reconciliation engine.
- Incident, Certification models.
- Cost Intelligence, Scale Intelligence, Optimization Engine, Quality
  Execution Planner.
- PostgreSQL, pgvector, object storage, Redis, Temporal — all SQLite +
  in-process asyncio today.
- Next.js frontend, SSO, Kubernetes/Terraform, OpenTelemetry/Prometheus/Grafana.

## What needs replacement vs. what can be reused

**Reuse as-is (adapter internals):** `dbt_runner.py`, `dbt_cloud_client.py`,
`airflow_client.py`, `provisioning.py`, `lineage.py`. These become the
concrete implementations behind new `DataPlatformAdapter`/`PipelineAdapter`
interfaces — not rewritten, wrapped.

**Extend, don't replace:** the `DbtProject`/`AirflowProject`/`TestRun`
family of models. New domain tables (contracts, rules, evidence, claims,
incidents, certifications) reference these by ID; they do not duplicate
project/job/DAG concepts.

**Net new:** everything in "prototype-only" above. This is the Horizon A
scope (see the plan/cost document) minus the pieces explicitly deferred to
Horizon B (Postgres/Temporal migration, full agent roster, cost/scale
engines, enterprise UI, deployment portability).

## Existing test coverage

v0.2 has no automated test suite (`pytest`, etc.) — validation to date has
been live, manual, end-to-end runs against real provisioned dbt/Airflow
instances (documented with exact commands and outcomes in
`docs/RUNBOOK.md`). Phase 1+ work below adds `pytest`-based unit tests as
it goes, per the master implementation prompt's testing requirements —
starting a test suite is itself part of this phase, not an assumption.
