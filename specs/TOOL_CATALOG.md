# Deterministic Tool Catalog

The ToolRegistry is the execution boundary for Agentic Data Engineering OS v0.4. Analyst/Plan modes cannot invoke mutation-risk tools.

| Family | Registered tools |
| --- | --- |
| Platform | `platform_discover`, `platform_inventory`, `platform_health`, `platform_graph`, `platform_lineage`, `platform_impact`, `doctor` |
| dbt | `dbt_manifest_summary`, `dbt_node`, `dbt_upstream`, `dbt_downstream`, `dbt_lineage`, `dbt_impact`, `dbt_tests_for_node`, `dbt_failed_tests`, `dbt_test_coverage`, `dbt_documentation_gaps` |
| Airflow | `airflow_inventory`, `airflow_dag_details`, `airflow_task_graph`, `airflow_dependencies`, `airflow_connections_used`, `airflow_health`, `airflow_failure_summary` |
| Reconciliation | `reconcile_row_count`, `reconcile_primary_keys`, `reconcile_duplicates`, `reconcile_nulls`, `reconcile_freshness`, `reconcile_aggregate`, `reconciliation_history` |
| Quality | `quality_summary`, `quality_recent` |
| SQL & lineage | `sql_review`, `sql_lineage`, `sql_column_lineage`, `column_upstream`, `column_downstream` |
| Metadata | `metadata_search`, `metadata_column_search` |
| Warehouses | `warehouse_status` |
| Migration / ShiftForge | `migration_scan`, `migration_inventory`, `migration_convert_model`, `migration_convert_project`, `migration_validate`, `migration_plan`, `migration_show_findings`, `migration_show_blockers`, `migration_compile`, `migration_test` |

**Total registered tools: 51.** The number itself is not a target; add tools only for distinct deterministic capabilities or governance boundaries.
