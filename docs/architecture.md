# UMA — Unified Data Migration Accelerator

UMA is the migration-focused product identity for this control plane. Its primary lifecycle is source discovery → migration assessment → dependency-ordered waves → deterministic verification → scoped approval → governed execution → reconciliation → evidence.

# Target Architecture

```text
Intent/API/PR/Ticket
      |
      v
Planning + Context Graph
      |
      v
Artifact Generation (SQL/dbt/PySpark/tests)
      |
      v
Ordered Deterministic Verification
      | pass / fail
      v          v
Approval       Bounded Repair
      \          /
       v        v
 Policy-Governed Tool Registry
           |
           v
 Snowflake / Databricks / BigQuery / dbt / Spark
           |
           v
 Durable Evidence + Observability
```

## Core invariants
- LLM output is never proof of correctness.
- Mutations occur only through typed tools/connectors.
- Destructive actions default to denied.
- Production mutations require explicit approval.
- Verification fails closed.
- Repair loops are bounded.
- Every execution produces durable evidence.

## Wave 2 extension

The runtime now adds a typed read-only connector edge, a SQLite-compatible context graph, a pluggable SQL AST summary, and resumable migration waves. External mutations remain outside those components: they require an explicitly registered tool, deterministic verification, policy evaluation, and scoped approval.
