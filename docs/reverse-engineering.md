# Reverse-Engineering Benchmark Set

Clean-room behavioral/architectural references only; source is not copied into the product tree.

| Repository | Pattern studied |
|---|---|
| mouryapt/databricks-agentic-ai-pipeline-poc | specialist DQ/schema/pipeline agents |
| kunumi/agentic-data-engineering | contract-driven discovery→transformation workflow |
| tower/agentic-data-engineering | secure agent-first data tooling |
| NiclasOlofsson/dbt-core-mcp | dbt DAG and selective compile/run/test tool surface |
| maseed260/data-migration-agent | DDL translation + migration + reconciliation loop |
| camharris93/sediment | deterministic core, AI edges, bounded validation |
| vaquarkhan/data-engineering-agent-skills | lifecycle and multi-cloud skill taxonomy |
| rosettadb/dbt-studio | approval-oriented dbt engineering UX |
| AltimateAI/altimate-code | deterministic SQL/lineage/parity/safety intelligence |

## Product synthesis
Discover → plan → generate → deterministically verify → approve → execute through governed connectors → observe → bounded repair.
