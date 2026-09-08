# Release readiness

This file defines the release-closure contract. It intentionally does not hard-code a self-referential Git SHA. The terminal automatic CI stage generates `release-readiness.json` from the checked-out commit and embeds the exact SHA.

## Exact candidate SHA

Authoritative source: the `release-readiness-<sha>` artifact produced by `integrated-platform / Python 3.12 release certification` after the Python 3.11 compatibility stage and the complete 3.12 release verification succeed.

Reproduce identity locally:

```bash
git rev-parse HEAD
PYTHONPATH=src python scripts/generate_release_evidence.py --ci-status PASS_LOCAL
```

## Product version

Python package: `agentic-data-engineering-platform` 0.3.0. Web operator UI: 0.4.0.

## Local test status

Required aggregate: `make verify`. It covers lint, frontend typecheck/build, backend suites, Airflow/dbt/provider/agent tests, integration, parity/conformance, structural certification, benchmarks, demo smoke, and final audit.

## Automatic CI status

Only `integrated-platform` is required on every `main` push/PR. It is deliberately serialized into two hosted-runner stages:

1. **Python 3.11 compatibility** — complete Python tests plus Ruff.
2. **Python 3.12 release certification** — `make verify`, Node deterministic harness, explicit Airflow 3 checks, bounded Data Diff scale smoke, wheel install outside the repository, API/Web operator-console smoke, and exact-SHA artifact generation.

Workflow-level concurrency uses "latest commit wins" so superseded release candidates are cancelled rather than consuming the repository/account runner queue.

## Manual external/heavy certification workflows

These are opt-in and are not required for a local release when their real external dependencies are absent:

- `data-diff-benchmark` — manual full 10K→10M benchmark and optional external 100M+ certification.
- `live-review-e2e` — manual real GitHub/GitLab review delivery.
- `live-agentic-e2e` — manual real Snowflake/dbt/Airflow/LLM probes.

No manual workflow is upgraded to PASS unless it actually executes its corresponding external contract.

## Discovery matrix

Automated coverage includes plain Git/SQL, dbt, Airflow, dbt+Airflow sibling monorepos, multiple warehouse hints, empty/no-config repositories, malformed dbt diagnostics, multiple/nested dbt projects, no Git metadata, ignored directories, and audit-safe credential-shaped fixture behavior. Static Airflow parsing records parse errors instead of importing DAG modules.

## Data Diff benchmark

The recorded full local DuckDB baseline is in `docs/DATA_DIFF.md`. Automatic release CI runs the bounded 10K/100K scale smoke. The manually dispatched Data Diff workflow can run 10K→10M and, only when explicitly requested and configured, the external 100M+ certification.

100M+ is not certified unless `scripts/live_data_diff_100m.py` succeeds against qualifying external data and explicit expected-change counts.

## Provider certification

Structural: `PYTHONPATH=src python scripts/run_certification.py`.

Live: `PYTHONPATH=src python scripts/run_certification.py --live`.

External credentials/model absent → `SKIP_EXTERNAL`.

## Review integration certification

Contract/integration tests run in `make verify`.

Live: manually dispatch `live-review-e2e` with the required GitHub/GitLab secrets and targets.

No live token/target → no live PASS claim.

## TUI / CLI / API / Web

The release job covers TUI tests, CLI/fresh-clone/package behavior, FastAPI routes, Next.js typecheck/build, and a started API+Web smoke test against real local repository evidence.

## Security status

Required checks include final acceptance audit plus centralized redaction/replay regression tests. Concrete findings must be fixed at source; scanners are not weakened.

## External live validation

Expected without secrets/resources:

| Item | Truthful state |
|---|---|
| GitHub PR live delivery | `SKIP_EXTERNAL` / `NOT_RUN` |
| GitLab MR live delivery | `SKIP_EXTERNAL` / `NOT_RUN` |
| Snowflake live | `BLOCKED_EXTERNAL` / `SKIP_EXTERNAL` |
| external Airflow live | `BLOCKED_EXTERNAL` / `SKIP_EXTERNAL` |
| cloud LLM live | `BLOCKED_EXTERNAL` / `SKIP_EXTERNAL` |
| 100M+ Data Diff | `NOT_RUN` / `SKIP_EXTERNAL` |

An exact-head manual run may supersede these with `PASS` only when a real external call was executed.

## Reproducible commands

```bash
python -m pip install -e '.[dev]'
python scripts/parse_dbt.py
make verify
PYTHONPATH=src python benchmarks/data_diff/run.py
PYTHONPATH=src python scripts/run_certification.py
PYTHONPATH=src python scripts/run_conformance.py
PYTHONPATH=src python scripts/generate_parity_ledger_v2.py
```

Any implementation/docs/test/CI commit invalidates prior exact-head certification; the newest SHA must complete the automatic two-stage CI again.
