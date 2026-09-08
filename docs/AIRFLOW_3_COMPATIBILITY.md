# Airflow 3 Compatibility

The platform recognizes `airflow.sdk`, Assets, AssetAlias, AssetWatcher/event-driven scheduling, dynamic mapping, deferrable operators, DAG bundles and Deadline Alerts. Legacy Dataset and SLA usage is surfaced as migration evidence rather than conflated with Airflow 3 concepts.

CI runs an Airflow-3 semantic fixture with `ADE_AIRFLOW_VERSION=3.3.0` without importing user DAG code.
