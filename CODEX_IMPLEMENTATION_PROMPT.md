# Codex Implementation Prompt — Agentic Data Engineering Platform

Repository: `rrahul0904/agentic-data-engineering-platform`

This is a standalone clean-room implementation. Do not modify or depend on `catalyst-etl`.

## Mission
Build an enterprise-grade, policy-governed Agentic Data Engineering Control Plane for discovery, pipeline generation, DDL/DML/dbt/PySpark engineering, testing, data quality, migration, reconciliation, schema evolution, approval-controlled execution and bounded repair across Snowflake, Databricks, BigQuery and cloud data services.

## Non-negotiable rules
1. AI proposes; deterministic systems verify.
2. No unrestricted model shell/database execution.
3. All mutations flow through typed connectors/tools and policy.
4. Destructive operations are denied by default.
5. Production mutations require explicit approval.
6. Verification fails closed.
7. Repair loops have explicit budgets.
8. Every run produces durable evidence.
9. Domain logic stays independent of agent framework vendors.
10. Build a control plane, not a chat wrapper.

## Current Wave 1
Inspect the existing implementation before changes. Preserve the durable repository layer, governed `ToolRegistry`, SQL analysis, platform-neutral migration spec, SQL Server→Snowflake demonstration translator, ordered verification gates, dbt manifest adapter, CLI and tests.

## Next Wave
Add real read-only/dry-run Snowflake, Databricks and BigQuery adapters; pluggable AST parser backend; dbt artifact/state comparison; lineage graph persistence; resumable migration waves; chunk/hash reconciliation; schema-evolution classification; REST API and lightweight control-plane UI. Keep all production mutation paths policy/approval gated and test every bypass boundary.
