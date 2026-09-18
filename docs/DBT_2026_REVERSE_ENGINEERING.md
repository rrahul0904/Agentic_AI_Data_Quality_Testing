# dbt 2026 Reverse-Engineering Wave

This document records the clean-room capability mapping implemented from the supplied dbt 2026 launch brief. ADE does **not** copy proprietary dbt/Fivetran implementation code and does not claim compatibility with private-beta internals. The goal is to implement the useful product patterns through ADE's existing governed, evidence-first architecture.

## Capability mapping

| Launch pattern | ADE implementation | Surface | Truth boundary |
| --- | --- | --- | --- |
| dbt v2 / Fusion SQL-aware engine | Existing SQL parser/review/lineage plus `dbt_next_engine_readiness` | Tool, API, CLI, web | ADE does not reimplement dbt's proprietary Rust engine. It consumes public dbt artifacts/runtime contracts. |
| dbt State | `state_plan` | Tool, API, CLI, web, MCP | Deterministic manifest diff classifies BUILD/SKIP and caller-evidenced CLONE/DEFER candidates. |
| Wizard | `wizard_plan` + existing governed ToolRegistry/AgentRuntime | Tool, API, CLI, web, desktop, MCP | Planner is deterministic by default; mutations remain handled by ADE's existing approval gates. |
| Wizard CLI | `ade dbt-next wizard-plan` | CLI | Uses the same tool implementation as API/UI. |
| Wizard Desktop | Native Electron dbt Next view | Desktop | Uses the same FastAPI control plane; full argument-level workbench remains available through the web console. |
| Wizard Explore | `explore_plan` | Tool, API, CLI, web, MCP | Resolves questions to governed metrics/dimensions/verified queries before SQL execution. |
| dbt Charts | `chart_validate` + `chart_compile` | Tool, API, CLI, web, MCP | YAML dashboards are versionable contracts; ADE does not claim dbt Charts rendering compatibility. |
| Lake Compute | `model_compute_plan`, `lake_compute_plan`, `lake_compute_run` | Tool, API, CLI, web, MCP | DuckDB/Parquet works locally; Iceberg requires an available DuckDB Iceberg extension. Cross-engine refs require materialized relation boundaries. |
| Context Layer | `context_bundle` + `context_search` | Tool, API, CLI, web, MCP | Combines dbt artifacts, semantic registry, selected files, and adapter-fed records. External connectors can feed records without being hard-coded here. |
| Agents Schema / AI context | `agents_schema` + ADE MCP v2 server | API, CLI, MCP | Read-only MCP server exposes governed dbt context, planning, semantic Explore, state, dashboard compilation and lake planning. |

## Architecture

```text
                         AI / MCP hosts
                              |
                        ADE MCP v2 server
                              |
              +---------------+----------------+
              |                                |
       governed context                    governed tools
              |                                |
    dbt artifacts + semantics       state / wizard / explore /
    + documents + records           charts / compute planning
              |                                |
              +---------------+----------------+
                              |
                       ADE ToolRegistry
                              |
                +-------------+-------------+
                |                           |
            FastAPI                        CLI
                |                           |
        Next.js workbench             ade dbt-next ...
                |
       Electron native workbench
                |
          approval/evidence layer
                |
    Snowflake / BigQuery / Redshift / Databricks
                |
           DuckDB / Parquet / Iceberg
```

## State planner contract

`dbt_next_state_plan` compares current and previous manifests.

- Changed/added models and transitive executable downstream models are **BUILD**.
- Unchanged nodes explicitly backed by `clone_available` are **CLONE**.
- Remaining unchanged nodes explicitly backed by `defer_available` are **DEFER**.
- Other unchanged executable nodes are **SKIP**.
- Removed nodes are surfaced as **REMOVED_REVIEW**.
- Every plan carries a deterministic fingerprint.

The planner does not pretend to know warehouse clone/defer availability. That evidence must be supplied by an adapter/caller.

## Multi-engine compute contract

`dbt_next_model_compute_plan` accepts a default engine and optional per-model overrides:

```json
{
  "manifest_path": "target/manifest.json",
  "default_engine": "warehouse",
  "model_engines": {
    "stg_large_iceberg": "lake",
    "mart_revenue": "warehouse"
  }
}
```

ADE explicitly reports each cross-engine dependency boundary. The contract is a materialized relation boundary; the implementation does not claim that `ref()` can magically cross engines without a relation visible to the downstream engine.

`dbt_next_lake_compute_run` is read-only. It supports Parquet directly through DuckDB and attempts `LOAD iceberg` only when an Iceberg source is requested. It never silently installs extensions.

## Governed Explore contract

Explore is deliberately two-stage:

1. Retrieve matching semantic metrics, dimensions and verified queries.
2. Return `READY` only when enough governed evidence exists; otherwise return `NEEDS_CLARIFICATION`.

This prevents the product from treating free-form LLM SQL as governed semantics.

## BI-as-code contract

Dashboard YAML is validated for:

- dashboard identity,
- at least one chart,
- unique chart names,
- metric(s) or read-only SQL per chart,
- rejection of mutating SQL.

Compilation emits portable downstream contracts for ADE web, Power BI, Excel and AI-agent consumers. Provider-specific publishing can be implemented as adapters without changing the source YAML.

## Context contract

The context bundle can combine:

- dbt models, metrics and semantic models from `manifest.json`,
- persistent ADE semantic resources and verified queries,
- explicitly selected local documents,
- adapter-fed unstructured records (for example Slack, Jira, call transcripts or policy documents).

Records are bounded before inclusion and the bundle receives a fingerprint. This keeps provenance visible and prevents an agent from silently treating arbitrary external text as dbt metadata.

## MCP server

Install the project and run:

```bash
ade-dbt-mcp
```

The server uses the current MCP v2 SDK and stdio transport by default. Configure it with:

- `ADE_MCP_PROJECT`
- `ADE_MCP_MANIFEST`
- `ADE_MCP_SEMANTIC_DATABASE`
- `ADE_MCP_CONTEXT_DOCUMENTS` (OS-path-separated list)

The MCP surface is intentionally read-only.

## User surfaces

### CLI

```bash
ade dbt-next engine-readiness --args '{}'
ade dbt-next state-plan --args '{"manifest_path":"target/manifest.json","previous_manifest_path":"state/manifest.json"}'
ade dbt-next wizard-plan --args '{"manifest_path":"target/manifest.json","question":"what changed downstream of revenue?"}'
ade dbt-next explore-plan --args '{"semantic_database":".ade/semantic.db","question":"revenue by region"}'
ade dbt-next chart-compile --args '{"path":"examples/dbt_next/executive_revenue.dashboard.yml"}'
ade dbt-next model-compute-plan --args '{"manifest_path":"target/manifest.json","model_engines":{"stg_large_iceberg":"lake"}}'
ade dbt-next lake-plan --args '{"source":"s3://bucket/table","source_type":"iceberg"}'
ade dbt-next agents-schema --args '{}'
```

### API

Discover the domain with `GET /api/v1/domains`, then invoke:

```text
POST /api/v1/dbt-next/<operation>
```

using the standard ADE `ToolInput` envelope.

### Web and desktop

The operator console contains a **dbt Next** workbench. The native Electron application contains a dbt Next planning view and can open the full console for every operation.

## Certification

The dedicated test slice is `tests/test_dbt_nextgen.py`. It certifies:

- state selection and downstream propagation,
- clone/defer classification,
- multi-engine boundary reporting,
- dashboard YAML validation and mutating-SQL rejection,
- structured/unstructured context search,
- semantic Explore grounding and verified-query use,
- API and CLI domain publication,
- MCP tool/resource discovery,
- tool-registry registration,
- lake compute planning and agent-schema publication.

Repository CI remains the authority for merge readiness.
