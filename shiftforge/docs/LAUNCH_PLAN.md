# Launch plan

## Phase 0 — functional MVP (included in this repository)

- BigQuery→Redshift rule engine.
- dbt model discovery.
- Sort-key projection guardrail.
- Explicit hints for ambiguous source expressions.
- Dry-run/approval gate.
- Isolated dbt compile harness.
- JSON/Markdown migration report.
- REST API + lightweight review UI.
- Docker image and CI tests.

## Phase 1 — private beta

- Parse `manifest.json` when available to understand refs, sources, dependencies, macros, and materializations.
- Build before/after column contract checks from dbt contracts/catalog metadata.
- Add Redshift-specific data-type and incremental-materialization rules.
- Add `dbt parse`, `dbt compile`, and selected `dbt test` execution policies.
- Add Git diff generation and patch export.
- Add encrypted project/run storage and login.
- Add provider-neutral LLM remediation only for blocked rules.

## Phase 2 — launch

- GitHub/GitLab repository connection and pull-request output.
- Background job queue for 100–1000 model repositories.
- Migration dashboard: inventory, blocked models, rule frequency, compile status, parity status.
- BigQuery/Redshift metadata connections for schema and row/aggregate parity checks.
- Usage metering, plan limits, billing, audit events, retention controls.
- SOC2-oriented controls: secrets isolation, no-training guarantee in provider configuration, deletion/retention policies, signed artifacts.

## Launch gate

Do not market a model as "converted" until it passes syntax/compile validation and all required sort/dist keys are resolvable. Do not market a project as "migration ready" until schema/column parity and data parity checks are implemented.
