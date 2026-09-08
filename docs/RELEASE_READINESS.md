# Release readiness

This file defines the release-closure contract. It intentionally does not hard-code a self-referential Git SHA. The terminal CI job generates `release-readiness.json` from the checked-out commit and embeds the exact SHA.

## Exact candidate SHA

Authoritative source: the `release-readiness-<sha>` CI artifact produced by `scripts/generate_release_evidence.py` after every required `integrated-platform` dependency succeeds.

Reproduce identity locally:

```bash
git rev-parse HEAD
PYTHONPATH=src python scripts/generate_release_evidence.py --ci-status PASS_LOCAL
```

## Product version

Python package: `agentic-data-engineering-platform` 0.3.0. Web operator UI: 0.4.0.

## Local test status

Required aggregate: `make verify`. It covers lint, frontend typecheck/build, backend suites, Airflow/dbt/provider/agent tests, integration, parity/conformance, structural certification, benchmarks, demo smoke, and final audit.

## CI status

Required exact-head workflows:

- `integrated-platform`
- `data-diff-benchmark`
- `live-review-e2e` — live calls may truthfully skip
- `live-agentic-e2e` — live calls may truthfully skip

`integrated-platform/release-closure` is terminal and only runs after required internal matrix jobs succeed.

## Discovery matrix

Automated coverage includes plain Git/SQL, dbt, Airflow, dbt+Airflow sibling monorepos, multiple warehouse hints, empty/no-config repositories, malformed dbt diagnostics, multiple/nested dbt projects, no Git metadata, ignored directories, and audit-safe credential-shaped fixture behavior. Static Airflow parsing records parse errors instead of importing DAG modules.

## Data Diff benchmark

The recorded full local DuckDB baseline is in `docs/DATA_DIFF.md`. Push CI runs 10K/100K; release benchmark path runs 10K→10M. 100M+ is not certified unless `scripts/live_data_diff_100m.py` succeeds against qualifying external data.

## Provider certification

Structural: `PYTHONPATH=src python scripts/run_certification.py`.

Live: `PYTHONPATH=src python scripts/run_certification.py --live`.

External credentials/model absent → `SKIP_EXTERNAL`.

## Review integration certification

Contract/integration: `pytest -q tests/review tests/test_dbt_pr_review.py`.

Live: `PYTHONPATH=src python scripts/live_review_e2e.py`.

No GitHub/GitLab live token/target → `SKIP_EXTERNAL`.

## TUI status

Dedicated tests cover command registration, governed service behavior, runtime events, and secret-safe expected error rendering. `agentic` launches through the installed entrypoint.

## CLI status

Fresh-clone CI installs the package and executes `agentic-data-platform --help`; discovery/domain commands are exercised by integration/demo suites.

## API status

FastAPI is launched during operator-console smoke CI and queried for overview, Airflow assets, providers, skills, and training. Domain routes include review, Data Diff, trace/session, providers, connections, and generic governed tool execution.

## Web status

CI runs `npm ci`, TypeScript typecheck, Next.js build, starts the built UI during demo smoke, and validates rendered operator-console content against the local API.

## Security status

Required checks include final acceptance audit plus centralized redaction/replay regression tests. Concrete findings must be fixed at source; scanners are not weakened.

## Fresh-clone and packaging status

Fresh-clone uses shallow checkout, editable install, CLI smoke, core integration tests, and full-platform demo. Packaging builds a wheel, installs it over the editable package, and imports/runs CLI outside the repository root.

## External live validation

Expected without secrets/resources:

| Item | Truthful state |
|---|---|
| GitHub PR live delivery | `SKIP_EXTERNAL` |
| GitLab MR live delivery | `SKIP_EXTERNAL` |
| Snowflake live | `BLOCKED_EXTERNAL` / `SKIP_EXTERNAL` |
| external Airflow live | `BLOCKED_EXTERNAL` / `SKIP_EXTERNAL` |
| cloud LLM live | `BLOCKED_EXTERNAL` / `SKIP_EXTERNAL` |
| 100M+ Data Diff | `NOT_RUN` / `SKIP_EXTERNAL` |

An exact-head run may supersede these with `PASS` only when a real external call was executed.

## Known limitations

- Web does not expose every low-level dbt unit-test generation/certification action.
- Shared provider protocol is synchronous even when registry metadata says an upstream provider supports streaming; certification reports this distinction.
- 100M+ Data Diff requires external qualifying tables.

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

Any implementation/docs/test/CI commit invalidates prior exact-head certification; the newest SHA must complete the full CI cycle again.
