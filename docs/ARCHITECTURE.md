# Architecture

The Agentic Data Engineering OS uses deterministic domain engines behind a single governed ToolRegistry. CLI, API, web console, skills, jobs and agent runtime invoke the same tool contracts; none is a permission bypass.

Core layers are: source/warehouse connectors; SQL/dbt/Airflow parsers and analyzers; metadata/lineage/quality/reconciliation; FinOps/governance/review/migration; session/memory/training/provider/MCP runtime; evidence/tracing/jobs; and operator surfaces.

Mutating tools are explicit, carry mutating risk, require Builder mode and approval, and support dry-run where applicable. External credentials are never required for the local acceptance suite.
