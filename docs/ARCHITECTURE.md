# Agentic Data Engineering OS architecture

## System layers

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ User interfaces                                                         │
│ Next.js Web │ Textual TUI │ CLI │ FastAPI │ GitHub/GitLab CI reviews   │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Governance and orchestration                                            │
│ ToolRegistry │ actor modes │ risk/approval │ AgentRuntime │ jobs        │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Deterministic workflow/domain layer                                     │
│ discovery │ review │ test generation │ Data Diff │ replay │ conformance │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Data-engineering core                                                   │
│ SQLGlot │ dbt artifacts │ Airflow AST │ project graph │ DQ │ metadata  │
│ lineage │ reconciliation │ FinOps │ governance │ migration             │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ External boundaries                                                     │
│ warehouse connectors │ model providers │ GitHub/GitLab │ Airflow REST  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Major packages

- `api` — FastAPI surface; routes call governed tools rather than bypassing policy.
- `tui` — Textual shell and slash-command adapter.
- `cli.py` / `entrypoint.py` — deterministic CLI plus TUI dispatch.
- `tools` — ToolRegistry, risk/capability contracts, and built-in tool registration.
- `runtime` — session-oriented agent execution and governed tool-call loop.
- `platform` — repository, dbt, Airflow, source, warehouse, and project-graph discovery.
- `dbt` — manifest understanding, validators, review, and deterministic test generation.
- `quality` — data quality, reconciliation support, and scalable warehouse Data Diff.
- `review` — deterministic dbt review plus GitHub/GitLab discovery/delivery adapters.
- `connectors` — warehouse contracts, capabilities, configuration, and live connectors.
- `providers` — model-provider normalization and registry.
- `tracing` / `security` — trace capture/replay and centralized secret redaction.
- `certification` — structural/live provider and warehouse certification.

## Discovery pipeline

`PlatformDiscovery` uses deterministic file/AST/YAML readers. It resolves Git metadata, plain SQL, dbt projects, Airflow DAG roots and warehouse hints; supports sibling dbt/Airflow roots and multiple/nested dbt projects; skips dependency/cache/generated directories; statically parses Airflow instead of importing DAG modules; emits structured malformed-dbt diagnostics; and sanitizes credential-bearing remotes.

## Deterministic versus LLM-backed logic

**Deterministic logic is authoritative for:** discovery, SQL parsing, dbt/Airflow graph extraction, review findings, Data Diff, reconciliation, risk/approval checks, test proposal construction, trace/redaction, provider/connector capability state, and certification status.

**LLM-backed logic is optional for:** natural-language planning and synthesis through `AgentRuntime`. An LLM cannot turn an unavailable external integration into a verified one and cannot bypass ToolRegistry mutation policy.

## Review orchestration

GitHub: `PR metadata → paginated files → deterministic dbt review → idempotent comment → review verdict`.

GitLab: `MR metadata → changes/diff fallback → deterministic review → paginated notes → create/update/dedupe`.

Adapters validate base URLs, classify external failures, and use `SKIP_EXTERNAL` when the selected live token is absent.

## Data Diff

- **PROFILE** pushes aggregates and moves no raw rows.
- **JOIN_DIFF** uses warehouse FULL OUTER JOIN when both sides share a connector; cross-warehouse fallback is explicitly bounded.
- **HASH_DIFF** profiles key ranges/signatures, recursively partitions mismatches, and transfers bounded row hashes.
- **CASCADE** starts with profile evidence and escalates only when required.

Partition strategies include numeric range, timestamp range, lexicographic range, hash bucket, and compound-key hash bucket. NULL keys use an explicit partition. Duplicate key/hash multiplicity uses multisets. Output keys are deterministically ordered.

## Trace, redaction, replay

Central redaction covers sensitive mapping keys, bearer/basic authorization, provider/Git tokens, AWS access-key identifiers, JWT-like values, credential-bearing database URLs, query-string secrets, assignments, and private keys. The TUI also sanitizes user echo, expected errors, JSON rendering, and agent event text. Replay regression tests ensure stored evidence does not reconstruct redacted secrets.

## Provider and warehouse boundary

Live connector construction is configuration-dependent and fails closed with explicit unavailable states. Model providers normalize request/tool/usage behavior behind a shared protocol. Structural certification does not imply live connectivity.

## Interface relationship

CLI/API call ToolRegistry; TUI uses `AgenticService`; Web consumes FastAPI; review automation uses deterministic review plus explicit delivery adapters. Surface differences are tracked in `docs/CROSS_SURFACE_PARITY.md`.

## Parity and release certification

Parity dimensions are independent: implemented, unit verified, behaviorally verified, and live verified. External dependencies without live evidence are `SKIP_EXTERNAL`, not `PASS`.

The terminal CI `release-closure` job depends on all required integrated-platform jobs and emits exact-head machine evidence only after they succeed.
