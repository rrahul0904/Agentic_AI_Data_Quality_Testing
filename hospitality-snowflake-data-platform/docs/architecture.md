# Architecture decisions

The platform separates immutable ingestion from business transformations. Airflow owns movement and batch evidence; Snowflake RAW owns replayable source payloads; dbt owns typing, conformance, dimensional logic, and analytics. This prevents extraction code from becoming a second transformation engine.

Every artifact is associated with a batch ID and SHA-256 digest before upload. Raw data is append-first. Corrections are represented through source update timestamps, soft-delete markers, or a new event. dbt staging selects the latest record per business key with a configurable late-arrival lookback.

The local Oracle simulation is a deliberate portability boundary. It preserves Oracle names, types, table inventory, extraction filenames, and orchestration semantics without requiring a large licensed image. A live adapter can replace export generation without changing downstream contracts.

