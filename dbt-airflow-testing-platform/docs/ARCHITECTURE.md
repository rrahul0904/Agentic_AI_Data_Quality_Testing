# ADE Test Control Tower — Architecture (v0.2.0)

> **Note:** as of v0.3.0-horizon-a, this document describes the v0.2
> multi-project platform this build sits on top of. For the deterministic
> Quality Rule Engine / Evidence / Certification layer now being added on
> top of it, see `docs/CURRENT_STATE.md` (baseline audit) and
> `docs/IMPLEMENTATION_STATUS.md` (honest capability matrix). The full
> target architecture is in the client-provided
> `AGENTIC_AI_DATA_QUALITY_TECHNICAL_ARCHITECTURE_V2.md`.

## What this is

A UI-based tool for creating and running **dbt** and **Airflow** test
projects. A user creates a named dbt project (local dbt-core, isolated
per-project venv, or a pointer to an existing dbt Cloud project) and/or a
named Airflow project (a dedicated, auto-provisioned Airflow instance); the
tool discovers that project's jobs/DAGs, captures their dependency graph,
and lets the user run one job/DAG or several at once, with results reported
side by side.

v0.1 hardcoded a single dbt project and a single Airflow DAG via `.env`.
v0.2 replaces that with a real multi-project model: any number of dbt
projects and Airflow projects, each independently provisioned, each with its
own jobs/DAGs and lineage, all run through the same `POST /api/runs`
orchestrator. Everything below was implemented and verified end-to-end on
this machine — provisioning a project for real, capturing real lineage,
running real jobs/DAGs, through the actual UI and API, not just described.

## The three decisions this design is built on

Made explicitly before building, because they determine the data model and
provisioning strategy:

1. **Isolated venv per dbt project.** Each local dbt project gets its own
   Python venv with its own dbt-core + adapter version. Different
   client/project dbt versions never collide; the cost is ~15s of
   provisioning time per project.
2. **Per-project execution mode for dbt.** A project is either "local"
   (we run `dbt build`/`dbt test` as a subprocess against its venv) or
   "dbt Cloud" (we call dbt Cloud's Administrative API to trigger/poll that
   project's existing dbt Cloud jobs — nothing runs locally). A project is
   one or the other, not both.
3. **A dedicated, auto-provisioned Airflow instance per Airflow project.**
   Creating an Airflow project doesn't connect to something that already
   exists — it installs and launches a brand new Airflow instance (its own
   venv, metadata DB, and webserver/scheduler/triggerer on a freshly
   allocated port) dedicated to that project. Heavier than connecting to an
   existing Airflow, but fully isolated: DAGs and runs from one project
   can't affect another.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Browser UI (static HTML/JS)                                            │
│  Dashboard (dbt projects | Airflow projects) -> Project detail          │
│  (jobs/DAGs + lineage graph + multi-select "Run") -> Run detail         │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │ HTTP
┌───────────────────────────────▼──────────────────────────────────────────┐
│  FastAPI backend (backend/app)                                          │
│  /api/dbt-projects, /api/airflow-projects, /api/runs                    │
└───────┬───────────────────────┬───────────────────────┬──────────────────┘
        │                       │                       │
┌───────▼────────┐    ┌─────────▼─────────┐   ┌─────────▼─────────┐
│ provisioning.py │    │ dbt_cloud_client   │   │ airflow_client     │
│ - venv + dbt    │    │ .py                │   │ .py                │
│   init (local)  │    │ trigger/poll a     │   │ trigger/poll a DAG │
│ - venv + full   │    │ dbt Cloud job run, │   │ run, list DAGs,    │
│   Airflow       │    │ fetch run_results  │   │ read task deps     │
│   instance      │    │ .json/manifest.json│   │ (for lineage)      │
│   (per project) │    │ artifacts          │   │                    │
└───────┬────────┘    └─────────┬─────────┘   └─────────┬─────────┘
        │                       │                       │
┌───────▼───────────────────────▼───────────────────────▼──────────────────┐
│  orchestrator.py: one TestRun = N dbt job runs (local subprocess or      │
│  dbt Cloud API) + M Airflow DAG runs, all concurrent (asyncio.gather)    │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │
┌───────────────────────────────▼──────────────────────────────────────────┐
│  SQLite (Postgres-ready): DbtProject/DbtJob, AirflowProject/AirflowDagRef,│
│  TestRun/DbtJobRun/DbtTestResult/AirflowDagRun/AirflowTaskResult,         │
│  Artifact (raw JSON evidence: run_results.json, dbt Cloud run JSON,      │
│  Airflow dagRun JSON)                                                     │
└────────────────────────────────────────────────────────────────────────┘
```

## Components

| Component | Location | Responsibility |
|---|---|---|
| UI | `backend/app/static/` | Hash-routed SPA (vanilla JS): dashboard, dbt/Airflow project detail (jobs/DAGs, lineage graph, multi-select run), run detail. No build step. |
| API | `backend/app/routers/{dbt_projects,airflow_projects,runs}.py` | CRUD + provisioning triggers + lineage + run creation. |
| Provisioning | `backend/app/services/provisioning.py` | Creates a venv (dbt-core+adapter, or full Airflow) per project; starts/stops a project's Airflow processes; finds a free port. |
| dbt runner | `backend/app/services/dbt_runner.py` | Local leg: `dbt build --select ...`, parses `run_results.json`/`manifest.json` into structured rows. `parse_run_results()` is shared with the dbt Cloud leg. |
| dbt Cloud client | `backend/app/services/dbt_cloud_client.py` | Cloud leg: trigger a job run via the Administrative API v2, poll to a terminal state, fetch that run's `run_results.json`/`manifest.json` artifacts for the same per-test detail a local run gets. |
| Airflow client | `backend/app/services/airflow_client.py` | Trigger/poll a DAG run, list a project's DAGs, read a DAG's task dependency graph — all via the REST API (`/api/v1`), works against any Airflow deployment that exposes it. |
| Lineage | `backend/app/services/lineage.py` | `dbt parse` (no warehouse access) -> `manifest.json` -> `{nodes, edges}`; Airflow `GET /dags/{id}/tasks`'s `downstream_task_ids` -> `{nodes, edges}`. Same shape for both, rendered by the same UI graph component. |
| Orchestrator | `backend/app/services/orchestrator.py` | One `TestRun` = N dbt job runs + M Airflow DAG runs, run concurrently, all results persisted, one overall PASSED/FAILED/ERROR computed. |

## Data model

```
DbtProject (execution_mode: local | cloud)
  ├── local: venv_path, project_dir, profiles_dir, adapter
  ├── cloud: dbt_cloud_host/account_id/project_id/api_token
  ├── lineage_json (cached manifest-derived graph)
  └── DbtJob[]  (kind: local_select [name + --select string] | cloud_job [synced from dbt Cloud])

AirflowProject
  ├── venv_path, airflow_home, webserver_port, base_url, admin credentials
  ├── webserver_pid, scheduler_pid, triggerer_pid  (for start/stop)
  └── AirflowDagRef[]  (dag_id, schedule, tags, lineage_json — discovered via /dags/sync)

TestRun (belongs to at most one DbtProject and/or one AirflowProject)
  ├── dbt_job_ids[] | dbt_adhoc_select   (which job(s) to run; empty = whole project, local only)
  ├── airflow_dag_ids[]                  (which DAG(s) to run)
  ├── DbtJobRun[]      (one per dbt job actually run -> DbtTestResult[])
  ├── AirflowDagRun[]  (one per DAG actually run -> AirflowTaskResult[])
  └── Artifact[]        (raw JSON evidence)
```

## One Test Run's lifecycle

1. `POST /api/runs` with `dbt_project_id`/`dbt_job_ids` and/or
   `airflow_project_id`/`airflow_dag_ids`. Row created `PENDING`, work runs as
   a background `asyncio` task.
2. Orchestrator resolves the job/DAG list, then runs **all of them
   concurrently** (`asyncio.gather`):
   - local dbt job -> `subprocess.run(dbt build --select ...)`, parse
     artifacts.
   - dbt Cloud job -> trigger via API, poll to terminal, fetch that run's
     artifacts for per-test detail.
   - Airflow DAG -> unpause it (see gotcha below), trigger via API, poll to
     terminal, read task instances.
3. Every job/DAG's results persist as its own `DbtJobRun`/`AirflowDagRun` row
   (so a multi-job run shows each job's results separately, not merged).
4. Overall status: `PASSED` only if every job/DAG passed (an unreachable
   Airflow project doesn't fail a dbt-only run, matching v0.1's fallback
   behavior); otherwise `FAILED`; `ERROR` if nothing could even run.

## Provisioning a project, concretely

**dbt (local mode):** create venv -> `pip install dbt-core dbt-<adapter>` ->
`dbt init <slug> --skip-profile-setup` (scaffolds a real starter project,
`my_first_dbt_model`/`my_second_dbt_model`, one of which fails a `not_null`
test out of the box — a genuine, not staged, first-run failure) -> write our
own `profiles.yml` for the chosen adapter -> `dbt parse` to capture initial
lineage. ~15s.

**dbt (cloud mode):** no local install; just validate the supplied
host/account/token against the Administrative API (`GET /accounts/{id}/`)
so a bad token fails fast at project-creation time, not at first run.

**Airflow:** create venv -> `pip install apache-airflow==X --constraint ...`
-> apply the macOS fork-safety entrypoint patch (see RUNBOOK) -> allocate a
free port -> `airflow db migrate` -> create an admin user with a generated
password -> start webserver/scheduler/triggerer as managed background
processes (PIDs stored on the `AirflowProject` row, so `/stop` and `/start`
work later) -> poll `/api/v1/health` until ready. ~25-30s. Verified by
provisioning two independent instances simultaneously (different ports, no
shared state) and confirming both stayed healthy.

## Known real gotchas found while building this (see docs/RUNBOOK.md for full detail)

Beyond the three macOS fork-safety issues from v0.1, three more were hit and
fixed while building the multi-project provisioning path:

1. **`dbt init --adapter` doesn't exist** in current dbt-core (1.10+) — the
   flag was removed. Provisioning uses `--skip-profile-setup` only and
   writes its own `profiles.yml`.
2. **A manually-triggered run of a *paused* DAG never executes** — it's
   created but the scheduler never picks it up (`queued` forever). Every
   freshly auto-provisioned Airflow project's DAGs start paused, so this
   hit immediately. Fixed by having `airflow_client.py` unpause a DAG right
   before triggering it.
3. **`SequentialExecutor` shells out to the bare `airflow` command** (PATH
   lookup, not `sys.executable`-relative) to run each task. A provisioned
   project's own venv wasn't on `PATH` for its own scheduler process, so
   every task sat in `queued` forever with `FileNotFoundError: 'airflow'`
   buried in the scheduler log. Fixed by prepending that project's
   `venv/bin` to `PATH` for its own processes — equivalent to what
   `source venv/bin/activate` does for a shell.

## Known limitations of v0.2

- No auth on the backend API (same as v0.1 — still fine for localhost, not
  for anything shared).
- dbt Cloud integration is implemented against the documented API surface
  but **not exercised against a live dbt Cloud account** (no credentials
  available in this environment) — validate `validate_credentials()` and a
  real job trigger against your own account before relying on it.
- Only two local adapters wired up (DuckDB, Snowflake); adding another is
  one entry in `settings.dbt_adapter_specs` plus a profile template in
  `provisioning.py` — same pattern, not yet done for BigQuery/Databricks/etc.
- A provisioned Airflow project's DAGs are whatever you upload via
  `POST /dags` — there's no "link this Airflow project to that dbt
  project's env vars" convenience yet, so an uploaded DAG that shells out to
  dbt needs its own env vars set correctly by hand (see the bundled
  `data_quality_pipeline_dag.py` for the pattern).
- Lineage graph layout (longest-path layering) is simple and can overlap
  labels on very wide/deep graphs; fine for the project sizes tested here.
- No project deletion in the UI yet (rows/venvs/instances accumulate).

## v0.3+ roadmap

- Link an Airflow project to a dbt project so uploaded DAGs can reference
  it out of the box (env var injection at start time).
- Project deletion (stop processes, remove venv/workspace, remove DB rows).
- Auth on the backend.
- More local adapters (BigQuery, Databricks, Postgres).
- A combined "run this dbt project and this Airflow project together"
  single-run view (today each project's page only runs its own kind).
