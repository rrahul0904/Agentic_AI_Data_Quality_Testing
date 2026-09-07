# Deterministic tool catalog

The registry currently exposes discovery, dbt manifest graph, Airflow static
intelligence, reconciliation, cross-system graph, SQL review/lineage,
metadata search, doctor, and structured ShiftForge migration tools. Each tool
has a capability, risk, input schema, output schema, and handler. CLI, HTTP,
and agent callers use the same registry.

List the live catalog with `GET /tools` or `agentic-data-platform tool ...`.
