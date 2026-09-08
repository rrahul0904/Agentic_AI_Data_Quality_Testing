# Agentic Data Engineering OS

**Agentic Data Engineering OS** is a local-first, evidence-driven operating system for modern data engineering.

It brings repository discovery, SQL intelligence, dbt engineering, Airflow analysis, cross-system lineage, data quality, source-target reconciliation, scalable Data Diff, migration engineering, governance, FinOps, AI-assisted investigation, GitHub/GitLab review automation, model-provider integrations, MCP, skills, training, traces, and session replay into one governed control plane.

> **Deterministic tools establish the facts. Agents reason over those facts.**

The platform is designed to remain useful even when no LLM, warehouse, or cloud service is configured. When an external dependency is unavailable, the platform reports that state explicitly instead of fabricating a successful result.

---

## Why this exists

Modern data platforms are fragmented across source databases, files, Airflow, dbt, warehouses, SQL, quality tooling, observability, Git, CI/CD, cloud providers, and AI assistants.

Agentic Data Engineering OS creates a single engineering layer across those systems so questions such as these can be investigated from one place:

- Which DAG loads this table?
- Which dbt model consumes it?
- What breaks if this column changes?
- Where did source and target data first diverge?
- Did a problem start in ingestion, mapping, transformation, or the warehouse?
- Which tests should be added for this change?
- What changed in this pull request?
- Can a backfill be planned safely?
- Did the migration preserve data and semantics?
- What is the blast radius of a failed pipeline?

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACES                                 │
│                                                                              │
│     Next.js Web Console     Textual TUI      CLI       FastAPI / API v1       │
│             │                   │             │               │               │
│             └───────────────────┴─────────────┴───────────────┘               │
│                                  │                                           │
│                     GitHub / GitLab Automation                               │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         AGENTIC CONTROL PLANE                                │
│                                                                              │
│ Investigation │ Planning │ Review │ Recovery │ Sessions │ Training │ Replay │
│ Providers     │ MCP      │ Skills │ Memory   │ Tracing  │ Certification     │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           GOVERNED TOOLREGISTRY                              │
│                                                                              │
│   Analyst        Plan        Builder        Admin        Approval Boundary    │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
           ┌───────────────────────┼─────────────────────────┐
           │                       │                         │
           ▼                       ▼                         ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌──────────────────────────┐
│ ENGINEERING         │  │ QUALITY / OPS       │  │ PLATFORM INTELLIGENCE    │
│                     │  │                     │  │                          │
│ SQL                 │  │ Data Quality        │  │ Discovery                │
│ dbt                 │  │ Data Diff           │  │ Asset Graph              │
│ Airflow             │  │ Reconciliation      │  │ Lineage                  │
│ Migration           │  │ FinOps              │  │ Impact Analysis          │
│ Metadata            │  │ Governance          │  │ Root Cause Analysis      │
│ PR Review           │  │ PII / RBAC          │  │ Recovery Planning        │
└──────────┬──────────┘  └──────────┬──────────┘  └─────────────┬────────────┘
           │                        │                           │
           └────────────────────────┼───────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                       DATA PLATFORM CONNECTORS                               │
│                                                                              │
│ Snowflake │ Oracle │ PostgreSQL │ Redshift │ BigQuery │ Databricks           │
│ MySQL │ SQL Server │ DuckDB │ SQLite │ ClickHouse │ Trino │ MongoDB          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Enterprise proving ground

The repository contains a realistic hospitality reservation data platform used as an end-to-end proving ground.

```text
Oracle + PostgreSQL + Files
             │
             ▼
        Apache Airflow
             │
             ▼
        RAW / Landing
             │
             ▼
             dbt
             │
             ▼
          Snowflake
             │
             ▼
     Analytics / Marts
```

Current repository-derived reference workload counts include:

| Component | Scale |
| --- | ---: |
| Oracle logical tables | 144 |
| PostgreSQL logical tables | 157 |
| File feeds | 18 |
| Metadata-driven ingestion jobs | 40 |
| Airflow DAGs | 57 |
| dbt models | 70 |
| dbt snapshots | 4 |

The workload also contains dbt tests, Snowflake DDL, deterministic dirty-data fixtures, multi-stage lineage, cross-DAG dependencies, failure scenarios, recovery probes, reconciliation examples, and business-level source-to-mart relationships.

---

## Core capabilities

### Repository discovery

Zero-config discovery inspects local repositories before cloud credentials are required.

It recognizes Git/SQL repositories, dbt projects, Airflow projects, mixed data-engineering repositories, warehouse hints, dbt artifacts, DAGs, models, tests, metadata, and configuration.

```bash
agentic-data-platform discover .
# or
ade discover .
```

Discovery is designed to fail gracefully for incomplete or malformed projects rather than requiring live Snowflake, Oracle, Airflow, or an LLM.

### SQL intelligence

The SQL subsystem provides deterministic parsing and analysis with support for:

- review and safety findings
- formatting
- classification
- fingerprinting
- translation
- rewrite and optimization
- SQL diff
- explain integration
- schema-aware analysis
- projection and column lineage
- upstream/downstream impact
- PII-aware policy checks

```bash
agentic-data-platform sql review \
  --args '{"sql":"SELECT * FROM raw.orders","dialect":"snowflake"}'
```

### dbt engineering

dbt is a first-class subsystem with support for:

- project parsing and manifest inspection
- model/source/test inventory
- upstream/downstream lineage
- impact analysis
- compiled SQL review
- incremental analysis
- snapshots and macros
- failed models and tests
- coverage and documentation gaps
- validation and state comparison
- compile, run, test, build, seed, snapshot
- schema-test generation
- dbt unit-test generation
- deterministic PR review and recommended tests

```bash
agentic-data-platform dbt summary
agentic-data-platform dbt lineage my_model
agentic-data-platform dbt impact my_model
agentic-data-platform dbt-run unit-test-generate --args '{"model":"my_model"}'
```

### Airflow engineering

Airflow intelligence covers modern Airflow 2/3 concepts including:

- DAG/task inventory
- task graphs and dependencies
- schedules and retry analysis
- backfill planning
- pipeline health and root-cause analysis
- connections, pools, queues and capacity
- mapped tasks and deferrable operators
- Assets and event-driven dependencies
- Task SDK compatibility
- bundles and deadlines
- XCom analysis
- security and secret-risk analysis
- upgrade analysis
- runtime readiness
- OpenLineage-oriented analysis

```bash
agentic-data-platform airflow inventory
agentic-data-platform airflow assets
agentic-data-platform airflow capacity
agentic-data-platform airflow retry-analysis
agentic-data-platform airflow root-cause
agentic-data-platform airflow upgrade
```

### Cross-system lineage and impact

The shared graph connects assets across source systems, orchestration, warehouse layers, dbt models, and marts.

```text
Oracle / PostgreSQL / Files
            ↓
        Airflow DAG
            ↓
      RAW warehouse
            ↓
       dbt staging
            ↓
    intermediate model
            ↓
       fact / dim
            ↓
          mart
```

The platform supports upstream/downstream traversal, column lineage, cross-system paths, change impact, blast-radius analysis, and dependency-aware root cause.

### Data quality

Quality capabilities include persistent evidence, summaries, recent results, asset-health scoring, pipeline-health scoring, dbt test evidence, dirty-data fixtures, anomaly signals, and controlled failure scenarios.

### Reconciliation

Built-in reconciliation includes:

- row counts
- primary keys
- duplicates
- nulls
- freshness
- aggregates
- tolerance-aware comparisons
- reconciliation history

```bash
agentic-data-platform reconcile row-count \
  --source-value 10000 \
  --target-value 9998
```

### Scalable Data Diff

Data Diff supports row-count, schema, key, join, hash, aggregate, profile, cascade, and partitioned comparison strategies.

The warehouse-driven implementation is designed to keep comparison work near the data and avoid unnecessarily materializing full datasets in Python.

A deterministic DuckDB benchmark exists for 10K, 100K, 1M, and 10M rows:

```bash
PYTHONPATH=src python benchmarks/data_diff/run.py
```

A separate 100M+ external harness exists in `scripts/live_data_diff_100m.py`. The repository does **not** claim a 100M+ PASS until that external benchmark is actually executed.

### Agentic investigation

The investigation system has 12 explicit roles:

1. Supervisor
2. Metadata
3. Business Context
4. Lineage
5. Transformation
6. Mapping
7. Quality / Test
8. Execution Planning
9. Evidence
10. Root Cause
11. Impact
12. Remediation

A typical flow is:

```text
Pipeline anomaly
      ↓
Supervisor
      ↓
Evidence-driven specialist delegation
      ↓
First divergence
      ↓
Competing hypotheses
      ↓
Root cause
      ↓
Blast radius
      ↓
Remediation proposal
      ↓
Human approval
      ↓
Selective recovery
      ↓
Independent verification
```

Agents reason over deterministic evidence. They do not replace the underlying tools.

### GitHub and GitLab review automation

The review layer supports:

- PR/MR discovery
- changed-file resolution
- deterministic dbt review
- change impact
- recommended tests
- risk analysis
- idempotent comment/note creation
- updates and deduplication
- GitHub verdict delivery
- configurable/self-hosted GitLab API URLs
- centralized output redaction

If live credentials are absent, external delivery reports `SKIP_EXTERNAL` rather than pretending a review was posted.

### Model providers

The provider control plane currently supports configurations for OpenAI, Anthropic, OpenRouter, Gemini, Vertex AI, AWS Bedrock, Azure OpenAI, Groq, Mistral, Together, xAI, DeepInfra, NVIDIA, Cerebras, Perplexity, Vercel AI Gateway, Cohere, Databricks AI Gateway, Snowflake Cortex, GitHub Copilot integration, Ollama, and LM Studio.

The provider layer normalizes models, messages, tools, authentication state, reasoning/streaming capabilities, request transformation, usage, output budgets, and errors.

### MCP

MCP is implemented as a governed control-plane subsystem with server registration, discovery, enable/disable, catalog/install, authentication state, tools, resources, invocation, OAuth initiation, OAuth callback, state validation, and ToolRegistry integration.

### Skills

The platform contains 32 built-in skills: 21 general data-engineering skills plus 11 Airflow/pipeline operations skills.

Skills orchestrate deterministic tools; they do not bypass permissions or replace the underlying engines.

### Training, memory and sessions

The runtime supports local project knowledge ingestion/search, persistent sessions, messages, state, todos, reminders, retry plans, compaction, nudges, memory primitives, and reusable context.

### Trace and session replay

Trace/session replay reconstructs recorded conversation, generation, tool, token, error and outcome evidence in read-only mode.

Replay does not silently re-execute the original tools.

### FinOps

FinOps includes normalized query-history analysis, expensive/error patterns, usage, cost summaries, idle resources, and warehouse-advisor recommendations.

Live costs require a supported real warehouse. Missing live evidence is reported explicitly.

### Governance, PII and RBAC

Governance capabilities include PII classification and propagation, PII lineage, downstream exposure, SQL policy checks, RBAC inventory, object-access analysis, excessive-privilege analysis, and sensitive-data access reporting.

### Migration engineering

The repository includes the deterministic ShiftForge migration/conversion engine. Migration functionality covers scan, inventory, planning, SQL/model conversion, findings, blockers, validation, compilation, and testing.

Current migration work includes BigQuery → Redshift and SQL Server → Snowflake paths.

---

## Supported data platforms

The runtime connector factory supports these primary targets:

| Platform |
| --- |
| DuckDB |
| SQLite |
| PostgreSQL |
| Redshift |
| MySQL |
| SQL Server |
| Oracle |
| ClickHouse |
| Trino |
| MongoDB |
| Snowflake |
| BigQuery |
| Databricks |

Warehouse connectors are read-oriented by default. Production mutation must be exposed separately through governed ToolRegistry operations.

---

## User interfaces

### Web operator console

`apps/web` contains the Next.js operator console.

Major product surfaces include:

- Overview
- Investigations
- Agent
- Assets
- Lineage
- SQL Intelligence
- dbt
- Airflow
- Data Quality
- Reconciliation
- Migration
- Warehouses
- Runs / Evidence
- Providers
- Skills
- Training
- Governance
- FinOps
- Traces
- Sessions
- Settings / Doctor

The frontend consumes real `/api/v1` responses and displays explicit unavailable states for credential-dependent services.

### Textual TUI

Launch the terminal UI with:

```bash
agentic
```

Navigation includes Project, SQL, dbt, Airflow, Warehouses, Lineage, Quality, Reconciliation, Migration, FinOps, Governance, Runs, Traces and Sessions.

Keyboard bindings:

```text
Ctrl+D  Discover
Ctrl+T  Traces
Ctrl+S  Sessions
Ctrl+Q  Quit
```

Useful slash commands include:

```text
/discover
/project
/connect
/providers
/models
/skills
/sql-review
/sql-translate
/query-optimize
/data-parity
/pii-audit
/cost-report
/lineage-diff
/dbt-develop
/dbt-test
/dbt-unit-tests
/dbt-docs
/dbt-analyze
/dbt-troubleshoot
/dbt-pr-review
/dbt-schema-verify
/airflow-analyze
/airflow-troubleshoot
/root-cause
/pipeline-health
/train
/teach
/training-status
/trace
/sessions
/mode
/help
/exit
```

### CLI

The package installs:

```text
ade
agentic
agentic-data-platform
```

Major CLI domains include SQL, lineage, schema, warehouse, dbt, Airflow, quality, reconciliation, Data Diff, review, connections, metadata, FinOps, governance, providers, MCP, skills, training, sessions, memory, traces and jobs.

### FastAPI

The API is exposed under:

```text
/api/v1
```

When running locally:

```text
FastAPI:  http://127.0.0.1:8001
API docs: http://127.0.0.1:8001/docs
```

---

## Quick start

```bash
git clone https://github.com/rrahul0904/Agentic_AI_Data_Quality_Testing.git
cd Agentic_AI_Data_Quality_Testing

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

For additional warehouse drivers:

```bash
python -m pip install -e '.[dev,warehouses]'
```

---

## Run the operator console

```bash
./scripts/setup-demo.sh
source .venv/bin/activate
make demo-ui
```

Open:

```text
Operator console: http://127.0.0.1:3000
FastAPI:          http://127.0.0.1:8001
API docs:         http://127.0.0.1:8001/docs
```

The local demo does not require Snowflake, Oracle, Docker, cloud Airflow, or cloud LLM credentials.

---

## Demos

Master platform demo:

```bash
bash scripts/demo-full-platform.sh
```

Agentic investigation:

```bash
make demo-agentic
```

Airflow:

```bash
make demo-airflow
```

---

## Verification

Run the primary bounded local verification suite with:

```bash
make verify
```

Individual targets include:

```bash
make lint
make test-unit
make test-integration
make test-airflow
make test-dbt
make test-providers
make test-agentic
make test-hospitality
make shiftforge-test
make frontend-typecheck
make frontend-build
make benchmark-lineage
make benchmark-airflow
make benchmark-agentic
make final-audit
```

GitHub Actions covers Python 3.11/3.12, frontend build/typechecking, Node tooling, the hospitality reference platform, ShiftForge, Airflow, dbt, providers, agents, integration tests, fresh-clone validation, Data Diff benchmarks, review automation, conformance/certification, security checks and final audit.

---

## Local vs live integrations

Local development intentionally works without production infrastructure.

External integrations that require real credentials or infrastructure include:

- Snowflake
- Oracle
- PostgreSQL / Redshift
- BigQuery
- Databricks
- cloud Airflow
- GitHub PR delivery
- GitLab MR delivery
- hosted AI providers
- live warehouse FinOps and RBAC
- 100M+ cross-warehouse Data Diff

The platform uses explicit states such as `SKIP_EXTERNAL`, `BLOCKED_EXTERNAL`, or `NOT_RUN_EXTERNAL` when those systems are unavailable.

---

## Safety model

Agentic Data Engineering OS separates reasoning from execution.

Operational modes include Analyst, Plan, Builder and Admin. Sensitive actions may require the correct mode, explicit approval, environment checks, risk checks and dry-run validation.

The goal is not unrestricted autonomy. The goal is **safe automation backed by evidence**.

---

## Repository structure

```text
Agentic_AI_Data_Quality_Testing/
│
├── apps/web/                         # Next.js operator console
├── src/agentic_data_platform/
│   ├── agents/                       # investigation and recovery agents
│   ├── api/                          # FastAPI v1
│   ├── certification/                # certification framework
│   ├── connections/                  # connection discovery/configuration
│   ├── connectors/                   # warehouse/data-platform adapters
│   ├── dbt/                          # dbt intelligence/runtime
│   ├── finops/                       # query/warehouse economics
│   ├── governance/                   # PII/RBAC/policy
│   ├── mcp/                          # MCP control plane
│   ├── metadata/                     # schema/search metadata
│   ├── migration/                    # migration orchestration
│   ├── platform/                     # discovery/graph/impact/RCA
│   ├── providers/                    # LLM provider control plane
│   ├── quality/                      # DQ, reconciliation, Data Diff
│   ├── review/                       # GitHub/GitLab data review
│   ├── runtime/                      # execution runtime and replay
│   ├── security/                     # redaction and safety
│   ├── session/                      # persistent sessions
│   ├── skills/                       # built-in/installable skills
│   ├── sql/                          # SQL intelligence
│   ├── tracing/                      # trace persistence
│   ├── training/                     # local project knowledge
│   ├── tui/                          # Textual operator UI
│   └── tools/                        # governed ToolRegistry
│
├── hospitality-snowflake-data-platform/  # enterprise reference workload
├── shiftforge/                            # deterministic migration engine
├── local-data-harness/                    # Node-based deterministic tools
├── dbt-airflow-testing-platform/
├── integration/
├── tests/
├── benchmarks/
├── scripts/
├── docs/
├── specs/
└── .github/workflows/
```

---

## Product direction

Agentic Data Engineering OS is intended to provide one engineering environment for:

```text
Discover
   ↓
Understand
   ↓
Develop
   ↓
Test
   ↓
Review
   ↓
Deploy
   ↓
Observe
   ↓
Investigate
   ↓
Recover
   ↓
Verify
```

across the complete data platform.

The goal is not another chatbot for data engineers. The goal is a **data-engineering operating system with agents inside it**.

See [docs/PRODUCT_CAPABILITIES.md](docs/PRODUCT_CAPABILITIES.md) for the capability map and [docs/RELEASE_STATUS.md](docs/RELEASE_STATUS.md) for the current verified engineering state.
