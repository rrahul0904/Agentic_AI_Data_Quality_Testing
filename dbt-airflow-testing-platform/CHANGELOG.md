# Changelog

## 0.4.0-horizon-a — Grounding Gateway, RCA, remediation, demo scenario (2026-09-04)

### Added
- `services/grounding.py`: deterministic Claim-Evidence Grounding Gateway
  (Architecture spec §11.3) — a status machine over evidence, not an LLM call.
- `services/rca.py`: evidence-grounded RCA that walks a project's real
  captured dbt lineage graph to the first upstream dataset with a failing
  certification, and grounds an `AgentClaim` in that dataset's actual
  failing-rule evidence (`generated_by="deterministic_rca"` — honestly not
  agent/LLM-generated yet).
- `services/remediation.py` + `/api/remediation-proposals` (create/approve/apply):
  controlled remediation (Level 3-4: generate patch, human-approved
  execution) — a narrowly-scoped, unique-match find/replace confined to the
  target dbt project's own directory.
- `/api/rca`, `/api/agent-claims` endpoints.
- `revenue_demo/`: the exact "Revenue Quality Certification" reference
  pipeline from Architecture spec §49 (raw_orders → stg_orders →
  int_revenue → fact_revenue, with the injected `WHERE status = 'COMPLETE'`
  defect) plus `quality_rules.json` (8 rules covering the spec's required
  quality-check list).
- `scripts/run_revenue_demo.py`: fully automates and asserts the entire
  scenario end to end against a running backend -- fail → evidence →
  certify FAILED → RCA (SUPPORTED) → propose/approve/apply remediation →
  rerun → certify CERTIFIED.
- `DbtProjectOut` now exposes `project_dir`/`venv_path`/`profiles_dir` so
  external tooling (the script above) doesn't need to guess internal
  on-disk layout.

### Fixed
- `evaluate_certification()` and the RCA lineage lookups matched rules by
  bare table name with no project scoping -- found by running the demo
  script against a second project that happened to share model names
  (`int_revenue`, `fact_revenue`) with an earlier one; certification
  reasons listed the same rule name twice, sourced from two unrelated
  projects. Fixed by adding `Certification.dbt_project_id` and threading
  project scope through certification and RCA; regression tests added.

### Verified end to end
`python3 scripts/run_revenue_demo.py` run from a clean project: real
defect → real FAIL on 3 of 8 rules (row coverage, net/gross revenue
reconciliation) → real FAILED certification → real SUPPORTED RCA claim
correctly localizing the defect to `int_revenue` → real approved-and-applied
one-line fix → real rebuild → real PASS on all 8 rules → real CERTIFIED
certification. 34 pytest tests passing (10 new: grounding status machine,
RCA lineage walk, certification/RCA project-scoping regressions).

## 0.3.0-horizon-a — deterministic Quality Rule Engine (2026-09-04)

First slice of the Agentic AI Data Quality & Pipeline Assurance Platform
(per `AGENTIC_AI_DATA_QUALITY_TECHNICAL_ARCHITECTURE_V2.md` and the master
implementation prompt), built on top of v0.2 rather than replacing it. See
`docs/CURRENT_STATE.md` for the Phase 0 audit and `docs/IMPLEMENTATION_STATUS.md`
for the full honest capability matrix.

### Added
- Domain model (`models_quality.py`): `BusinessConcept`, `QualityContract`,
  `QualityRule`, `QualityRuleRun`, `Evidence`, `AgentClaim`,
  `ClaimEvidenceLink`, `Incident`, `RemediationProposal`, `Certification` --
  Postgres-compatible schema, still running on SQLite.
- `services/adapters/base.py`: `DataPlatformAdapter`/`PipelineAdapter` ABCs
  (Master Prompt §14/§15).
- `services/adapters/duckdb_adapter.py`: real, live-tested `DataPlatformAdapter`
  implementation connecting to a local dbt project's own warehouse file.
- `services/quality_rule_engine.py`: canonical `QualityRule` → SQLGlot-compiled,
  dialect-portable SQL (`compile_rule`), plus real deterministic execution
  and PASS/FAIL/ERROR interpretation (`execute_rule`) -- six rule types:
  not_null, unique, accepted_values, row_count_reconciliation,
  aggregate_reconciliation, custom_sql.
- `services/certification.py`: derives CERTIFIED/AT_RISK/FAILED/UNKNOWN from
  rule results with an explainable reason -- never an arbitrary AI score.
- `/api/business-concepts`, `/api/quality-contracts`, `/api/quality-rules`
  (create/list/compile/execute/runs), `/api/incidents`,
  `/api/certifications` routers.
- `backend/tests/`: 24 pytest tests (rule compilation, execution
  interpretation with a fake adapter, certification derivation, a real
  DuckDB adapter against a temp warehouse) -- first automated test suite in
  this codebase.

### Verified live (not just unit tests)
Created a real business concept → contract → 3 rules against the existing
"XYZ Company" DuckDB project; compiled to DuckDB SQL and previewed a
Snowflake-dialect transpile of the same rule; executed all 3 for real
(including a genuine ERROR when a dependent table didn't exist yet, and a
correct FAIL on a real null value dbt's own starter project ships with);
confirmed a P1 failure auto-creates an Incident and certification correctly
computes FAILED/AT_RISK with an explainable, rule-naming reason.

### Not yet real (see docs/IMPLEMENTATION_STATUS.md)
Context/Transformation/Evidence Intelligence, Grounding Gateway, all
agents, LLM Gateway, hash/bucket reconciliation, Cost/Scale/Optimization/
Change Intelligence, the Revenue Quality Certification demo scenario itself,
and everything in Horizon B (Postgres/Temporal/K8s/Next.js/SSO).

## 0.2.0 — multi-project platform (2026-09-03)

Replaces v0.1's single hardcoded dbt project + Airflow DAG with a real
multi-project model. Verified end to end on this machine, including two
Airflow instances provisioned and run simultaneously to confirm isolation.

### Added
- `DbtProject`/`DbtJob` and `AirflowProject`/`AirflowDagRef` data model: any
  number of independently-provisioned dbt and Airflow projects, each with
  its own jobs/DAGs.
- `services/provisioning.py`: creates an isolated venv (dbt-core + adapter)
  per local dbt project via real `dbt init`; creates a fully independent
  Airflow instance (own venv, metadata DB, webserver/scheduler/triggerer on
  a freshly allocated port) per Airflow project, with start/stop lifecycle
  management via stored PIDs.
- `services/dbt_cloud_client.py`: dbt Cloud Administrative API v2 client
  (list jobs, trigger/poll a job run, fetch that run's `run_results.json`/
  `manifest.json` artifacts for the same per-test detail a local run gets).
  Implemented against the documented API; not exercised against a live
  account (no credentials available).
- `services/lineage.py`: captures a dbt project's dependency graph (`dbt
  parse` -> manifest) and an Airflow DAG's task dependency graph (REST API),
  both as the same `{nodes, edges}` shape.
- Orchestrator rewritten to run an arbitrary number of dbt jobs and Airflow
  DAGs concurrently per `TestRun`, each persisted as its own job/DAG run
  with its own results (`docs/ARCHITECTURE.md` — "one Test Run's lifecycle").
- UI rewritten: hash-routed dashboard (dbt projects | Airflow projects),
  project creation wizards, project detail pages (jobs/DAGs with
  checkboxes, a hand-rendered SVG lineage graph, multi-select "Run"), run
  detail adapted for multiple job/DAG results.
- `/api/dbt-projects`, `/api/airflow-projects` routers (create, list, get,
  jobs/DAG sync, lineage, start/stop for Airflow projects, DAG upload).

### Fixed (found while building the above; see docs/RUNBOOK.md)
- `dbt init --adapter` no longer exists in current dbt-core (1.10+) —
  provisioning uses `--skip-profile-setup` only and writes its own
  `profiles.yml`.
- A manually-triggered run of a *paused* DAG (the default for every
  freshly auto-provisioned Airflow project) was created but never executed
  — the scheduler never picked it up. Fixed by unpausing before triggering.
- `SequentialExecutor` shells out to the bare `airflow` command (PATH
  lookup) to run each task; a provisioned project's own venv wasn't on
  `PATH` for its own scheduler process, so every task sat in `queued`
  forever. Fixed by prepending that project's `venv/bin` to `PATH`.
- A UI bug where the 3-second polling refresh silently reset in-progress
  job/DAG checkbox selections on a project detail page. Fixed by only
  auto-refreshing a project detail page while it's still `PROVISIONING`.

### Known limitations (tracked for v0.3, see ARCHITECTURE.md)
- No auth on the backend API.
- Only DuckDB and Snowflake wired up as local adapters.
- No "link this Airflow project to that dbt project" convenience — an
  uploaded DAG that shells out to dbt needs its own env vars set by hand.
- No project deletion in the UI.

## 0.1.0 — first draft (2026-09-02)

Initial working version. Verified end to end on this machine.

### Added
- FastAPI backend (`backend/app`) with a `TestRun` orchestrator that runs a
  dbt leg and an Airflow leg concurrently, persists both to SQLite, and
  computes an overall PASSED/FAILED/ERROR status.
- dbt leg: shells out to `dbt build`, parses `run_results.json` +
  `manifest.json` into structured per-node results.
- Airflow leg: talks to Airflow's stable REST API (`/api/v1`) to trigger a
  DAG run, poll it to completion, and read back task instance states.
- Demo dbt project (`dbt_demo_project/`, DuckDB-backed) with staging +
  marts models, schema tests, and one singular test. Seed data includes
  three intentionally-failing rows so a first run demonstrates real,
  fail-closed reporting.
- Demo Airflow DAG (`airflow_dags/data_quality_pipeline_dag.py`):
  extract → load (dbt seed) → run (dbt run) → test (dbt test) → row-count
  + null-rate checks → report.
- Static single-page UI (vanilla JS + Tailwind CDN): trigger a run, see a
  live-polling run list, drill into one run's dbt results table and Airflow
  task results table.
- Setup/run scripts (`scripts/`) and a runbook (`docs/RUNBOOK.md`)
  documenting three real macOS/sandboxed-process issues hit and fixed while
  validating this end to end (gunicorn fork SIGSEGV, task-runner fork
  deadlock, BashOperator working-directory mismatch).
- `docs/ARCHITECTURE.md` describing the system, its data model, deployment
  topology, known limitations, and the v0.2+ roadmap.

### Known limitations (tracked for v0.2, see ARCHITECTURE.md)
- No auth on the backend API.
- Single hardcoded dbt project + single Airflow DAG (no multi-project UI).
- Polling-based UI updates, no websocket/SSE push.
- `docker-compose.yml` designed but not exercised (no Docker daemon in this
  environment) — local dev instead validated directly against venvs.
