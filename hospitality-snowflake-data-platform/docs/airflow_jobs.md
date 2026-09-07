# Airflow jobs

`job_catalog.py` is the authoritative inventory for 40 ingestion DAGs: 20 Oracle, 16 PostgreSQL, and 4 file jobs. `generated_ingestion_dags.py` materializes each as an independently schedulable Airflow DAG. `orchestration_dags.py` adds the daily ingestion master, three dbt layer jobs, the quality master, and the end-to-end pipeline.

Simulation mode discovers reviewed source exports under `airflow/data/source_exports/{oracle,postgres}`. File jobs discover generated feeds under `sources/files/generated`. Validation streams SHA-256 calculation in 1 MiB blocks, then Snowflake loading uses an internal stage and source-format-specific COPY statement.

