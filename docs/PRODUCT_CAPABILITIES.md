# Product Capabilities

**Agentic Data Engineering OS** is a local-first, evidence-driven control plane for modern data engineering.

This document describes the product as its own platform. It intentionally avoids reverse-engineering history, comparison matrices, and implementation-wave terminology.

## Capability map

| Domain | Implemented product behavior | External dependency for live evidence |
| --- | --- | --- |
| Discovery | Git, SQL, dbt, Airflow, mixed repositories, configuration hints and inventory | No |
| SQL | Review, classify, format, fingerprint, translate, optimize, diff, lineage and policy checks | Optional warehouse |
| dbt | Parse, lineage, impact, tests, docs, incremental analysis, runtime commands, test generation and review | Warehouse for live execution |
| Airflow | DAG/task graphs, Assets, retries, backfills, capacity, security, RCA and Airflow 3 readiness | Live Airflow for runtime evidence |
| Lineage | Cross-system asset graph, column lineage, paths, impact and blast radius | No for repository-derived evidence |
| Data Quality | Persistent checks, health scores, anomalies and evidence | Optional warehouse |
| Reconciliation | Counts, keys, duplicates, nulls, freshness and aggregates | Optional live source/target |
| Data Diff | Schema/key/join/hash/aggregate/profile/cascade, partitioning and pushdown | External warehouses for live cross-platform use |
| Investigation | 12-role evidence-grounded incident investigation and recovery planning | LLM optional |
| Git Review | GitHub PR and GitLab MR discovery, deterministic review and idempotent delivery | Credentials for real delivery |
| Providers | Hosted and local model-provider control plane | Credentials or local model server |
| MCP | Discovery, catalog, auth, tools/resources, invocation and OAuth | MCP server as needed |
| Skills | Built-in and installable deterministic workflows | No |
| Training | Local project-knowledge ingestion/search/context | No |
| Sessions | Persistent messages, state, todos, reminders and retry plans | No |
| Replay | Read-only trace/session reconstruction | No |
| FinOps | Query history, cost/usage analysis, idle resources and recommendations | Live warehouse for real costs |
| Governance | PII classification/lineage, policy, RBAC and access analysis | Live warehouse for deep grants/access |
| Migration | Scan, plan, convert, validate, compile and test | Optional source/target |
| Interfaces | Next.js web console, Textual TUI, CLI, FastAPI and Git automation | Depends on invoked operation |

## Core engineering areas

### Repository discovery

Discovery is designed to work before cloud credentials are configured. It identifies supported repository structure, dbt projects and artifacts, Airflow DAG trees, SQL files, warehouse hints, tests, models and local metadata.

### SQL intelligence

The SQL subsystem provides deterministic parsing, safety/performance review, dialect translation, optimization, formatting, fingerprinting, SQL diff, schema awareness, column lineage, impact analysis and PII-aware policy checks.

### dbt engineering

The dbt subsystem supports project parsing, model/source/test inventory, upstream/downstream lineage, impact, compiled SQL review, incremental analysis, snapshots, macros, failed-model/test analysis, coverage, documentation gaps, state comparison, validation, compile/run/test/build/seed/snapshot orchestration, schema-test generation, unit-test generation and PR review.

### Airflow engineering

Airflow support includes DAG/task inventory, dependency graphs, Assets, event-driven scheduling, retries, backfill planning, pools/capacity, mapped tasks, deferrables, Task SDK compatibility, bundles, deadlines, XCom, security, secret-risk analysis, root cause, upgrade analysis and runtime readiness.

### Cross-system lineage

The shared graph connects source systems, Airflow ingestion, warehouse landing/RAW layers, dbt staging/intermediate models, facts/dimensions and marts.

### Data quality, reconciliation and Data Diff

The platform stores deterministic quality evidence and supports row-count/key/null/duplicate/freshness/aggregate reconciliation. Data Diff adds schema, join, hash, profile and cascade strategies with partitioning, bounded detail retrieval and warehouse pushdown.

### Agentic investigation

The investigation team consists of Supervisor, Metadata, Business Context, Lineage, Transformation, Mapping, Quality/Test, Execution Planning, Evidence, Root Cause, Impact and Remediation roles. Agents reason over deterministic evidence and remain separated from governed execution.

### Git review automation

GitHub and GitLab review orchestration supports PR/MR discovery, changed-file resolution, deterministic dbt review, recommended tests, risk analysis, idempotent comments/notes, GitHub verdict delivery and configurable GitLab API URLs.

### Providers and MCP

The provider layer supports 22 hosted/local configurations. MCP supports server lifecycle/configuration, discovery, tools/resources, authentication and OAuth-oriented flows through the same governed execution boundary.

### Skills, training, sessions and replay

The platform includes 32 built-in skills, local project training/search, persistent sessions and memory primitives, and read-only trace/session replay.

### FinOps and governance

FinOps normalizes query/cost/usage evidence and recommendations. Governance covers PII classification/lineage, downstream exposure, SQL policy, RBAC inventory, object access and privilege-risk analysis.

## Supported data platforms

Runtime connectors currently cover DuckDB, SQLite, PostgreSQL, Redshift, MySQL, SQL Server, Oracle, ClickHouse, Trino, MongoDB, Snowflake, BigQuery and Databricks.

Connectors default to read-oriented behavior. Production mutation must be exposed separately through governed ToolRegistry operations.

## Product interfaces

Agentic Data Engineering OS exposes the control plane through:

- Next.js web operator console
- Textual terminal UI
- CLI
- FastAPI `/api/v1`
- GitHub/GitLab automation

The product direction is cross-surface consistency: useful platform capabilities should be available to operators rather than hidden only as internal functions.
