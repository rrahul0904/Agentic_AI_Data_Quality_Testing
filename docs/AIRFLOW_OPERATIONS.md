# Airflow Operations

The version-aware AirflowAdapter supports health, DAGs, tasks, runs, task instances, logs, variables, connections, pools, Assets/events and import errors. Airflow 3 uses API-v2 semantics; legacy projects use API-v1 semantics.

Trigger, pause, unpause, clear and backfill are ToolRegistry mutations: Builder + explicit approval are mandatory. Live runtime absence is SKIP_EXTERNAL, not success.
