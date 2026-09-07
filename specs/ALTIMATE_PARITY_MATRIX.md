# Altimate-style parity matrix

This matrix tracks working capability, not directory or tool-count claims. Status is evidence-based: **DONE** means the implemented scope is tested; **PARTIAL** means a useful implementation exists but the broader production capability is unfinished.

| Capability | Reference capability | Our status | Implementation path | Verification | Priority | Beyond-Altimate direction |
|---|---|---|---|---|---|---|
| Repository discovery | Project inventory | DONE | `platform.discovery` | root + E2E tests | P0 | Cross-system source/Airflow/dbt/warehouse inventory |
| Operator console | Integrated product shell | DONE | `apps/web` + FastAPI v1 | TypeScript, production build, runtime smoke | P0 | Evidence-first data operations console |
| Governed tool execution | Deterministic tool registry | DONE | `tools.registry` + 82 registered tools | permission + API tests | P0 | Analyst/Plan/Builder safety boundaries |
| dbt graph | Lineage and impact | DONE | `dbt.manifest_graph` | root + E2E tests | P0 | State-aware change impact |
| Advanced dbt intelligence | Tests/docs/incrementals/snapshots/macros | PARTIAL | `dbt.advanced` | v0.4 tests | P0 | Generated tests/contracts + deep optimization |
| Airflow static intelligence | DAG/task inventory | DONE | `platform.airflow` | root + E2E tests | P0 | Cross-DAG lineage |
| Airflow operational intelligence | Retry/backfill/runtime/root cause | PARTIAL | `platform.airflow_ops` | v0.4 tests + failure lab | P0 | Live logs/SLA/scheduler correlation |
| Data quality evidence | Deterministic checks/history | PARTIAL | quality store + hospitality DQ | API/runtime smoke + tests | P0 | Drift/anomaly baselines + SLOs |
| Reconciliation | Source/target metrics | DONE | `quality.reconciliation` | root + E2E tests | P0 | Warehouse-executed reconciliation |
| Composite data diff | Schema/key/hash/row/aggregate diff | PARTIAL | `quality.data_diff` | unit tests + real DuckDB fixture | P0 | Chunked live cross-warehouse diff |
| SQL review | AST safety/performance rules | DONE | `sql.intelligence` | root + API tests | P1 | Cost-aware optimizer signals |
| Column lineage | Projection/value lineage | PARTIAL | `sql.intelligence.column_lineage` | root + API tests | P1 | Full multi-model, schema-backed lineage |
| Metadata index | Local searchable catalog | PARTIAL | `metadata.index` | root tests | P1 | Warehouse-scale autocomplete/search |
| Warehouse adapters | Common facade/connectivity state | PARTIAL | connectors + `warehouse_status` | root/API tests | P1 | Broad live adapter matrix |
| Snowflake metadata | Static + read-only foundation | PARTIAL | Snowflake connector/static DDL | root/LDH tests | P1 | Query/load history, tasks, dynamic tables |
| FinOps | Snowflake usage/cost | NOT STARTED | planned warehouse history adapters | — | P2 | Pipeline/model/DAG cost attribution |
| RBAC/security | Grants and role graph | NOT STARTED | planned Snowflake governance adapter | — | P2 | PII-aware privilege risk |
| Migration | BigQuery → Redshift | DONE | recovered ShiftForge | ShiftForge tests | P0 | Canonical migration IR |
| Migration integration | Control-plane invocation | DONE | `migration.shiftforge_adapter` | root/API tests | P0 | Multi-warehouse conversion + parity |
| PII/governance | PII detection | PARTIAL | recovered LDH tools | LDH tests | P2 | Policy-aware access/lineage graph |
| Observability | Quality/run evidence | PARTIAL | SQLite evidence stores | root/API tests | P2 | Tool traces, replay, token/cost accounting |
| Cross-system root cause | DQ/dbt/Airflow correlation | PARTIAL | `platform.root_cause` | v0.4 tests | P1 | Live warehouse/log evidence |
| Remediation | Safe repair proposals | PARTIAL | `remediation.proposals` | v0.4 tests | P1 | Approved Builder-mode application |
| MCP | MCP server/client | NOT STARTED | roadmap | — | P2 | External agent interoperability |
| Skills | Reusable orchestration skills | NOT STARTED | roadmap | — | P2 | Data-engineering skill library |
| Full provider layer | Multi-LLM providers | NOT STARTED | roadmap | — | P2 | Provider-agnostic agent execution |
| Production TUI | Full terminal operator experience | NOT STARTED | roadmap | — | P3 | CLI/TUI + web share one tool plane |

## v0.4 evidence boundary

The v0.4 demo proves a fresh runner can regenerate dbt artifacts, seed deterministic quality evidence, build the Next.js console, start FastAPI + the production web build, and query the real project inventory. It does **not** claim live Snowflake, live Oracle, or live Airflow runtime behavior when those services are absent.
