# Snowflake design

Three auto-suspending X-Small warehouses isolate ingestion, transformation, and analyst workloads. Roles receive least-privilege access to their schemas and warehouses. The RAW landing table is clustered by source and ingestion date and stores source payloads as VARIANT for replayability.

Audit schemas capture batches, table loads, watermarks, quality results, errors, and dbt invocations. The raw append-only stream is reserved for downstream event-driven processing. Cost controls begin with 60-second auto-suspend and independent workload sizing.

