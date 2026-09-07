# Altimate-style parity matrix

This matrix tracks working capability, not directory or tool-count claims.

| Capability | Altimate capability | Our status | Implementation path | Tests | Priority | Beyond-Altimate enhancement |
|---|---|---|---|---|---|---|
| Repository discovery | Project inventory | DONE | `platform.discovery` | `test_next_phase.py` | P0 | Cross-system inventory |
| dbt graph | Lineage and impact | DONE | `dbt.manifest_graph` + registry | `test_next_phase.py` | P0 | State-aware impact |
| Airflow intelligence | DAG/task inventory | PARTIAL | `platform.airflow` | `test_next_phase.py` | P0 | Failure and SLA analysis |
| Data quality | Deterministic checks | PARTIAL | hospitality framework + quality store | integration tests | P0 | Historical anomaly detection |
| Reconciliation | Source/target parity | DONE | `quality.reconciliation` | integration tests | P0 | Cross-warehouse diff |
| SQL review | AST safety rules | DONE | `sql.intelligence` | `test_next_phase.py` | P1 | Optimizer and cost signals |
| Column lineage | Projection lineage | PARTIAL | `sql.intelligence.column_lineage` | `test_next_phase.py` | P1 | Full multi-model lineage |
| Warehouse adapters | Snowflake read-only metadata | PARTIAL | `connectors.snowflake` | `test_wave2.py` | P1 | FinOps/RBAC/deep history |
| Migration | BigQuery to Redshift | DONE | recovered ShiftForge | ShiftForge tests | P0 | Canonical migration IR |
| Migration integration | Control-plane invocation | DONE | `migration.shiftforge_adapter` | `test_next_phase.py` | P0 | Multi-warehouse parity |
| PII/governance | PII detection | PARTIAL | recovered LDH tools | LDH tests | P2 | Policy-aware access graph |
| Observability | Trace/history | PARTIAL | SQLite evidence store | root tests | P2 | Replay and cost accounting |
| FinOps | Snowflake usage/cost | NOT STARTED | planned warehouse history adapters | — | P2 | Pipeline cost attribution |
| Autonomous remediation | Approved proposals | PARTIAL | bounded planner/repair agents | root tests | P2 | Safe automated remediation |
