# Shared asset graph

`PlatformAssetGraph` builds source-table, source-file, Airflow DAG/task,
warehouse-table, dbt source/model/test/snapshot, and mart nodes from committed
DDL, Python AST, and dbt artifacts. Edges represent extraction, loading,
transformation, tests, containment, and dependencies. Lineage and impact are
bounded graph traversals and include affected marts/tests.
