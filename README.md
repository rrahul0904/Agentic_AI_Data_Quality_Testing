# Agentic Data Engineering OS

**Agentic Data Engineering OS** is a local-first, governed control plane for understanding and operating data-engineering projects. It combines deterministic repository discovery, SQL/dbt/Airflow intelligence, data quality and Data Diff, code-review automation, test generation, warehouse/provider adapters, trace/session replay, parity tracking, and agent workflows behind shared CLI, Textual TUI, API, Web, and CI surfaces.

The product deliberately separates **implemented**, **verified**, and **live certified**. External services are never reported as passed merely because a mocked or structural test succeeded.

## What it is

The system discovers a repository without requiring a project config, builds deterministic project and lineage evidence, and exposes governed tools through a common ToolRegistry. LLM-backed agent execution can orchestrate those tools, but deterministic analyzers and connectors remain the source of measured facts and mutation policy.

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Web UI │ Textual TUI │ CLI │ FastAPI │ GitHub/GitLab review flows │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Governed ToolRegistry + Agent / Workflow Runtime                    │
│ Discovery │ Review │ Test generation │ Diff │ Replay │ Parity      │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Deterministic data-engineering engines                              │
│ SQL │ dbt │ Airflow │ metadata │ lineage │ quality │ reconciliation│
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Warehouses / model providers / Git hosts                            │
│ DuckDB + external connectors │ LLM providers │ GitHub │ GitLab      │
└─────────────────────────────────────────────────────────────────────┘
```

See `docs/ARCHITECTURE.md` for package boundaries and deterministic-vs-LLM responsibilities.

## Core capabilities

Implemented repository capabilities include:

- zero-config project discovery through `agentic-data-platform discover .` and TUI `/discover`
- Git, plain SQL, dbt, Airflow, and dbt+Airflow monorepo discovery
- multiple/nested dbt project inventory, warehouse hints, ignored-directory handling, and malformed-project diagnostics
- static dbt and Airflow understanding without importing user DAG code during discovery
- SQL review, lineage, optimization, classification, formatting, translation, and governed execution tools
- scalable Data Diff with warehouse pushdown, bounded hash movement, range/hash partitioning, composite-key support, deterministic ordering, and NULL/duplicate-key regression coverage
- deterministic dbt review and incremental-aware dbt unit-test generation
- GitHub pull-request and GitLab merge-request discovery, review comment/note create/update/dedupe, pagination, and explicit external failure classification
- trace/session storage and replay with centralized secret redaction
- structural warehouse/provider certification and separate live certification harnesses
- behavioral conformance and Parity Ledger 2.0 evidence
- CLI, Textual TUI, FastAPI, and Next.js operator console
- governed agent workflows and CI review/integration gates

## Quickstart

Python 3.11 and 3.12 are supported by CI.

```bash
git clone https://github.com/rrahul0904/Agentic_AI_Data_Quality_Testing.git
cd Agentic_AI_Data_Quality_Testing

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

agentic-data-platform discover .
agentic --project .
```

Inside the TUI, type `/discover` to rescan the current project.

Start the API:

```bash
PYTHONPATH=src python -m uvicorn agentic_data_platform.api.app:app \
  --host 127.0.0.1 --port 8001
```

Start the Web UI in another terminal:

```bash
cd apps/web
npm ci
NEXT_PUBLIC_ADE_API_URL=http://127.0.0.1:8001 npm run dev
```

The operator console is at `http://127.0.0.1:3000`; FastAPI docs are at `http://127.0.0.1:8001/docs`.

## Review integrations

GitHub and GitLab integrations support deterministic changed-file discovery, review generation, idempotent comment/note updates, rerun deduplication, pagination, and classified auth/permission/rate/network/provider failures. GitLab accepts a validated self-hosted HTTP(S) API base URL.

Local and mocked integration tests do **not** imply a live delivery pass. The live harness is:

```bash
PYTHONPATH=src python scripts/live_review_e2e.py
```

Missing live credentials/targets return `SKIP_EXTERNAL`. See `docs/ENVIRONMENT.md`.

## Data Diff

The pushdown-first warehouse Data Diff engine profiles data remotely, recursively partitions mismatches, and transfers bounded row hashes rather than materializing complete remote tables in Python. Matching partitions can be eliminated by aggregate signatures.

Reference local DuckDB pushdown benchmark from the previously recorded full local run:

| Scale | Runtime | Partitions | Queries | Rows transferred | Raw rows transferred |
|---:|---:|---:|---:|---:|---:|
| 10K | ~0.121 s | 1 | 6 | 20,000 | 0 |
| 100K | ~0.422 s | 3 | 10 | 100,000 | 0 |
| 1M | ~2.758 s | 11 | 26 | 62,500 | 0 |
| 10M | ~28.725 s | 17 | 38 | 78,124 | 0 |

Peak process RSS for that run was approximately **158 MB**. These are local DuckDB benchmark figures, not a claim about every warehouse or runner.

The push workflow always executes a bounded 10K/100K smoke. The full 10K→10M suite is gated to manual dispatch or a release benchmark commit. The 100M+ harness is external and is **not** a passed certification unless it actually completes against qualifying data.

```bash
PYTHONPATH=src python benchmarks/data_diff/run.py
PYTHONPATH=src python scripts/live_data_diff_100m.py
```

## Certification status vocabulary

| State | Meaning |
|---|---|
| `VERIFIED` | exercised successfully with evidence |
| `PASS_LOCAL` | passed a local deterministic/integration gate |
| `PASS_CI` | passed CI against the exact recorded SHA |
| `SKIP_EXTERNAL` | external credentials/service are absent; no live pass claimed |
| `NOT_RUN` | runnable check was not executed |
| `BLOCKED_EXTERNAL` | external environment/configuration prevents execution |
| `FAIL` | executed check failed |

Structural certification is `make certification-local`; live certification is separate with `make certification-live`.

## Interfaces

- **CLI:** `agentic-data-platform`, `ade`, or explicit `agentic <command>`.
- **Textual TUI:** `agentic --project .`; slash commands include `/discover`, dbt/Airflow operations, traces, sessions, and quality/reconciliation flows.
- **API:** FastAPI `/api/v1` routes invoke governed tool contracts, including production Data Diff, review, providers, traces/sessions, and connections.
- **Web:** the Next.js operator console consumes real `/api/v1` responses. Some write/generation operations intentionally remain CLI/TUI/API-only; see `docs/CROSS_SURFACE_PARITY.md`.

## Verification

The canonical bounded local suite is:

```bash
make verify
```

Dedicated gates:

```bash
make conformance
make certification-local
make parity-v2
make test-ui
make final-audit
```

CI exercises Python 3.11/3.12, frontend typecheck/build, fresh-clone installation, dbt, Airflow, providers, integrations, review, TUI, security/redaction, packaging, conformance, certification, parity, benchmarks, and release evidence.

## External live validation

External systems remain fail-closed: GitHub PR delivery, GitLab MR delivery, Snowflake, external Airflow, LLM providers, and 100M+ Data Diff. Missing credentials/resources are represented as `SKIP_EXTERNAL`, `BLOCKED_EXTERNAL`, or `NOT_RUN`, never as `PASS`.

## Release readiness

`docs/RELEASE_READINESS.md` is the human-readable release contract. Exact-head machine evidence is generated by `scripts/generate_release_evidence.py` and uploaded by the terminal `release-closure` CI job only after all required integrated-platform jobs succeed.
