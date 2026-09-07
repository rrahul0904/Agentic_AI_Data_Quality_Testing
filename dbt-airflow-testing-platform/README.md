# ADE Test Control Tower

**v0.2.0** — a UI-based tool for creating dbt and Airflow test projects,
capturing their lineage, and running one job/DAG or several at once, with
results reported side by side.

![status](https://img.shields.io/badge/status-v0.2_draft-orange)

- What this is, the data model, and honest known limitations:
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Exact setup/run steps, plus every real bug hit and fixed while building
  this: [docs/RUNBOOK.md](docs/RUNBOOK.md)

## Quickstart

```bash
scripts/setup_backend_venv.sh
scripts/run_backend.sh    # :8000 -- open this in a browser
```

Then, from the UI:

1. **+ New dbt Project** — name it, choose "Local dbt-core" + DuckDB (no
   credentials needed) to try it immediately, or "dbt Cloud" + your account
   ID/API token to run existing dbt Cloud jobs.
2. Add a job (a `--select` string) or several, tick the ones to run, **Run
   Selected**. A freshly created local project is dbt's own starter project
   — one of its two models fails a test out of the box, which is dbt
   demonstrating a real failure, not a bug here.
3. **+ New Airflow Project** — name it; this provisions a dedicated Airflow
   instance just for it (~30s). Upload a DAG, **Sync**, tick it, **Run
   Selected DAGs**.

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the single-project manual setup
(v0.1) if you'd rather skip the UI wizard for a fixed project.

## Status

v0.2.0 — validated end to end on this machine: real dbt project provisioning
and lineage capture, real per-project Airflow instances (two provisioned
and run simultaneously to confirm isolation), real multi-job and multi-DAG
runs, all through the actual UI. dbt Cloud integration is implemented
against the documented API but not exercised against a live account (no
credentials available here) — see "Known limitations" in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
