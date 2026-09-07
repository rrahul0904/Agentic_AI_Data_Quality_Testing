# Runbook — local dev

## Starting the tool (v0.2: multi-project)

Only the backend needs to run manually now — creating a project through the
UI provisions everything else (a dbt venv, or a full dedicated Airflow
instance) for you.

```bash
cd dbt-airflow-testing-platform
scripts/setup_backend_venv.sh          # .venv: FastAPI + dbt-core + dbt-duckdb
scripts/run_backend.sh                 # :8000 -- open this in a browser
```

From the UI (`http://127.0.0.1:8000`):

1. **+ New dbt Project** — name it, pick "Local dbt-core" + an adapter
   (DuckDB needs no credentials; Snowflake reads `SNOWFLAKE_*` env vars) or
   "dbt Cloud" + your account ID/API token. Local mode scaffolds a real
   starter dbt project (`dbt init`) and captures its lineage — takes ~15s.
2. Open the project, add a job (a name + a `--select` string) or add
   several, tick the ones you want, **Run Selected** (or **Run Whole
   Project** for local mode). Watch results per job on the run page.
3. **+ New Airflow Project** — name it; this provisions a dedicated Airflow
   instance (own venv, metadata DB, webserver/scheduler/triggerer on a fresh
   port) — takes ~25-30s. Upload a DAG file, **Sync** a few seconds later to
   discover it (and capture its task dependency graph), tick it, **Run
   Selected DAGs**.

The bundled `airflow_dags/data_quality_pipeline_dag.py` is a ready-to-upload
example (extract → dbt seed → dbt run → dbt test → row-count/null-rate
checks → report) — see its module docstring for the env vars it expects if
you want it to actually reach a dbt project rather than just demonstrate
discovery/lineage/scheduling.

### What "first run fails" looks like, and why that's correct

A freshly created local dbt project (DuckDB) is dbt-core's own `dbt init`
starter project: `my_first_dbt_model` and `my_second_dbt_model`, one of
which fails a `not_null` test out of the box — that's dbt's own example of
what a failing test looks like, not something this tool broke. Point the
project at your own dbt project (or add jobs with your own `--select`
strings) to see real, meaningful results.

## Enabling the RCA agent (the first real LLM-backed agent)

Everything through the Revenue Quality Certification scenario is
deterministic -- no LLM involved. `services/rca_agent.py` is the first
actual agent, and it's *only* invoked when RCA finds more than one upstream
dataset failing at once (a lineage walk alone can't rank them). Without an
API key it degrades to an honest `UNVERIFIED` claim naming the ambiguous
candidates -- it never crashes and never guesses.

To enable it:

```bash
echo 'OPENAI_API_KEY=sk-...' >> backend/.env
# optional, defaults to gpt-4o-mini:
echo 'OPENAI_MODEL=gpt-4o-mini' >> backend/.env
```

Restart the backend, then force a genuinely ambiguous case against any
project with a `stg_orders -> int_revenue -> fact_revenue`-shaped lineage
(e.g. the Revenue Quality Certification project) by making two upstream
datasets fail at once:

```bash
PID=<your dbt_project_id>
for TABLE in stg_orders int_revenue; do
  RID=$(curl -sS -X POST http://127.0.0.1:8000/api/quality-rules -H "Content-Type: application/json" -d "{
    \"dbt_project_id\":\"$PID\",\"name\":\"forced fail $TABLE\",\"dimension\":\"volume\",\"rule_type\":\"custom_sql\",
    \"target_table\":\"$TABLE\",\"expression\":{\"sql\":\"SELECT 1 AS failing_count\"},\"tolerance_value\":0,\"severity\":\"P1\"
  }" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
  curl -sS -X POST "http://127.0.0.1:8000/api/quality-rules/$RID/execute" > /dev/null
  curl -sS -X POST "http://127.0.0.1:8000/api/certifications/evaluate?dataset_ref=$TABLE&dbt_project_id=$PID" > /dev/null
done
curl -sS -X POST "http://127.0.0.1:8000/api/rca?dbt_project_id=$PID&dataset_ref=fact_revenue" | python3 -m json.tool
```

With a real key configured, `generated_by` will read
`rca_agent:openai:<model>` instead of `deterministic_rca`, `evidence_links`
will contain only evidence IDs the model cited *and* that were verified to
actually exist, and a row appears in `llm_call_logs` with real token counts.

---

## Appendix: the v0.1 single-project manual setup

Before the multi-project model, one dbt project and one Airflow DAG were
wired up via `backend/.env`, with Airflow's three processes started by hand.
This still works if you want a single fixed project without the UI wizard:

```bash
scripts/setup_backend_venv.sh
scripts/setup_airflow_venv.sh    # .airflow_venv: apache-airflow + duckdb
scripts/init_airflow_db.sh       # migrate metadata DB, create admin/admin123,
                                  # symlink dbt_demo_project's DAG in, unpause it
cp backend/.env.example backend/.env
```

Then, three terminals:

```bash
scripts/run_airflow_webserver.sh   # :8080
scripts/run_airflow_scheduler.sh
scripts/run_backend.sh             # :8000
```

The demo seed data (`dbt_demo_project/seeds/raw_orders.csv`) has three rows
that intentionally violate a test each (null `customer_id`, an invalid
`status`, a negative `amount`), so a fresh run reports `FAILED` on both legs
the first time — that's correct, fail-closed reporting, not a bug.

---

## Real gotchas hit while building this, and why the fixes look the way they do

Everything below was hit for real, not anticipated in the abstract. If
you're deploying on Linux (a normal Airflow target), most of the
macOS-specific ones shouldn't apply.

### `airflow standalone` crash-loops with `SIGSEGV`

`airflow standalone` runs webserver + scheduler + triggerer as one command,
but the webserver (and the scheduler/triggerer's internal log-serving
side-processes) run under gunicorn, which forks worker processes. On this
machine, forking from Airflow's multi-threaded parent process reliably
`SIGSEGV`'d the child immediately, and gunicorn's arbiter just kept
respawning — an infinite crash loop burning CPU. Fixed by running
webserver/scheduler/triggerer as separate plain processes (see
`provisioning.py` / `run_airflow_webserver.sh` / `run_airflow_scheduler.sh`)
instead of via `airflow standalone`.

### Webserver: use `--debug`, not gunicorn

`airflow webserver --debug` uses Flask's single-process dev server instead
of gunicorn, sidestepping the fork issue above entirely. (Not for
production — a real deployment runs behind gunicorn/systemd on Linux, where
this isn't a problem.)

### Scheduler/triggerer: `--skip-serve-logs`

Independent of the webserver, the scheduler and triggerer each start their
own small gunicorn-based log server (so the webserver can fetch task logs
remotely). Those hit the same fork crash. `--skip-serve-logs` disables them;
we don't need remote log serving for a single-node `SequentialExecutor`
setup (task logs are still written to files under `<project>/logs/`).

### Individual tasks hang at 90%+ CPU forever (fork deadlock)

Airflow's `StandardTaskRunner` forks by default (`_start_by_fork`) and only
uses a plain subprocess (`_start_by_exec`) when a task has `run_as_user`
set — there's no Airflow config flag to force the exec path otherwise.
Forking a multi-threaded process (which the scheduler is) is exactly the
deadlock-prone pattern Python's own `DeprecationWarning` names, and here it
reliably deadlocked, pegging one process at high CPU forever.

Fixed by `scripts/patch_airflow_entrypoint.py`, applied once per provisioned
venv (both by `setup_airflow_venv.sh` for the v0.1 manual path and by
`provisioning.py` for every v0.2 auto-provisioned Airflow project). It
patches the venv's `bin/airflow` console-script entrypoint to flip
`airflow.settings.CAN_FORK = False` before dispatching to Airflow's CLI —
gated on `ADE_FORCE_EXEC_TASK_RUNNER=1` being set, so it's a no-op anywhere
that isn't (e.g. a Linux deployment).

This patches the entrypoint script itself rather than a `sitecustomize.py`
(the more usual Python-startup hook) because every Airflow process —
scheduler, triggerer, and the `airflow tasks run --local`/`--raw`
subprocesses that spawn the fork — goes through this same script.
`sitecustomize.py` was tried first and looked like it should work, but
Python only imports the *first* `sitecustomize` found on `sys.path`, and a
Homebrew-managed Python installs its own earlier on `sys.path` (inside the
interpreter's stdlib dir, ahead of any venv's `site-packages`) — it silently
shadowed ours, so the patch never ran. If you see this symptom again after
switching Python distributions, check
`python3 -c "import sitecustomize; print(sitecustomize.__file__)"` inside
the venv before assuming the entrypoint patch is broken.

### Airflow's REST API returns 401 with credentials you just created

By default Airflow's `[api] auth_backends` is
`airflow.api.auth.backend.session` only — session-cookie auth for the web
UI, not HTTP Basic. Both the v0.1 manual env (`scripts/ade_env.sh`) and
every v0.2 auto-provisioned instance (`provisioning.py`'s `_airflow_env`)
set `AIRFLOW__API__AUTH_BACKENDS=airflow.api.auth.backend.basic_auth` so
`airflow_client.py`'s Basic-auth requests are accepted.

### `dbt seed`/`dbt run` fail with "Cannot open file ... No such file or directory" when run from Airflow, but work fine from a terminal

`BashOperator` runs commands from a temp working directory by default, not
the dbt project directory — and a *relative* DuckDB path in `profiles.yml`
then resolves against that temp directory instead of the project. Fixed by
passing `cwd=PROJECT_DIR` explicitly to each `BashOperator` in
`airflow_dags/data_quality_pipeline_dag.py`.

### DuckDB: `Cannot open file ".../warehouse.duckdb": No such file or directory`

`dbt-duckdb` does not create missing parent directories for its database
file. The `warehouse/` directory must exist before the first `dbt` run;
`provisioning.py` creates it as part of `dbt init` scaffolding.

### `dbt init --adapter` doesn't exist (v0.2)

Current dbt-core (1.10+, what `dbt-core>=1.10` resolves to today) removed
the `--adapter` flag from `dbt init` entirely — confirmed directly against
the installed version (`dbt init --help`) after a provisioning run failed
with `Error: No such option '--adapter'`. `provision_dbt_local_project()`
now calls `dbt init <slug> --skip-profile-setup` only (no `--adapter`); the
adapter choice only matters for which `profiles.yml` template we write
afterward.

### A manually-triggered run of a *paused* DAG never executes (v0.2)

Every freshly auto-provisioned Airflow project's DAGs start paused (Airflow
default). Triggering a paused DAG via the REST API creates the `DagRun` row,
but the scheduler never picks it up — it sits in `queued` forever
(`last_scheduling_decision: null`). Confirmed by watching a triggered run
never progress, then finding it still `queued` after several minutes with no
scheduler log activity for it at all. Fixed by having
`AirflowClient.run_dag_to_completion()` call `set_dag_paused(dag_id, False)`
immediately before triggering — a quality-test run should just work
regardless of the DAG's pause state.

### `SequentialExecutor` can't find the `airflow` command (v0.2)

Even after unpausing, a v0.2 auto-provisioned project's tasks still sat in
`queued` forever. The scheduler log (not the task log — the task never
started) showed:

```
FileNotFoundError: [Errno 2] No such file or directory: 'airflow'
```

`SequentialExecutor.sync()` runs each task via
`subprocess.check_call(["airflow", "tasks", "run", ...], ...)` — the bare
command name, resolved via `PATH`, not `sys.executable`-relative. Our
provisioned scheduler process's environment didn't have that project's own
`venv/bin` on `PATH` (we invoke `venv/bin/airflow` by absolute path
ourselves everywhere, so this was never noticed until the executor tried to
shell out on its own). Fixed by prepending `venv/bin` to `PATH` in
`provisioning.py`'s `_airflow_env()` — equivalent to what
`source venv/bin/activate` does for a shell, applied to a subprocess's
environment instead.
