# Deterministic Tool Catalog

The ToolRegistry is the execution boundary for Agentic Data Engineering OS v0.4. Analyst/Plan modes cannot invoke mutation-risk tools.

| Family | Registered tools |
| --- | --- |
| Platform | `platform_discover`, `platform_inventory`, `platform_health`, `platform_graph`, `platform_lineage`, `platform_impact`, `platform_root_cause`, `asset_health_score`, `pipeline_health_score`, `doctor` |
| dbt | `dbt_manifest_summary`, `dbt_node`, `dbt_upstream`, `dbt_downstream`, `dbt_lineage`, `dbt_impact`, `dbt_tests_for_node`, `dbt_failed_tests`, `dbt_test_coverage`, `dbt_documentation_gaps`, `dbt_incremental_analysis`, `dbt_snapshot_analysis`, `dbt_macro_analysis`, `dbt_failed_models`, `dbt_source_freshness`, `dbt_leaf_candidates`, `dbt_compiled_sql_review`, `dbt_state_compare` |
| Airflow | `airflow_inventory`, `airflow_dag_details`, `airflow_task_graph`, `airflow_dependencies`, `airflow_connections_used`, `airflow_health`, `airflow_failure_summary`, `airflow_retry_analysis`, `airflow_schedule_analysis`, `airflow_backfill_analysis`, `airflow_connection_analysis`, `airflow_pipeline_health`, `airflow_runtime_readiness`, `airflow_root_cause`, `airflow_failure_lab` |
| Reconciliation | `reconcile_row_count`, `reconcile_primary_keys`, `reconcile_duplicates`, `reconcile_nulls`, `reconcile_freshness`, `reconcile_aggregate`, `reconciliation_history` |
| Data diff | `data_diff_schema`, `data_diff_row_count`, `data_diff_keys`, `data_diff_hash`, `data_diff_rows`, `data_diff_aggregate`, `data_diff_report`, `data_diff_duckdb_demo` |
| Quality | `quality_summary`, `quality_recent` |
| SQL & lineage | `sql_review`, `sql_lineage`, `sql_column_lineage`, `column_upstream`, `column_downstream` |
| Metadata | `metadata_search`, `metadata_column_search` |
| Warehouses | `warehouse_status` |
| Migration / ShiftForge | `migration_scan`, `migration_inventory`, `migration_convert_model`, `migration_convert_project`, `migration_validate`, `migration_plan`, `migration_show_findings`, `migration_show_blockers`, `migration_compile`, `migration_test` |
| Proposal-only remediation | `propose_dbt_tests`, `propose_sql_repair`, `propose_airflow_retry`, `propose_quality_rule` |

**Total registered tools: 82.** The number itself is not a target; add tools only for distinct deterministic capabilities or governance boundaries.
