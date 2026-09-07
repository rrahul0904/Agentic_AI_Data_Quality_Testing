# Roadmap

## v0.1 — included
- local REPL/CLI and headless HTTP API
- mock provider for zero-setup operation
- Ollama provider for local LLM operation
- deterministic SQL review
- draft SQL lineage
- PII scan
- dbt project/manifest discovery
- local stack discovery
- mode-based permissions
- local SQLite tracing
- sample workspace + tests

## v0.2
- robust SQL AST parser (sqlglot/tree-sitter service or WASM parser)
- DuckDB + PostgreSQL adapters
- dbt Core command adapter and manifest graph
- richer lineage graph and impact analysis
- MCP server/client support
- terminal UI with streaming tool cards

## v0.3
- Snowflake/BigQuery/Redshift/Databricks adapters
- schema index and query history
- cost/FinOps rules
- data-diff engine
- policy/approval UI for writes
- plugin/skill SDK

## v1
- desktop/web UI
- multi-agent workflows
- GitHub/CI review mode
- local semantic catalog / RAG
- benchmark suite and security hardening

## Phase 2 — Data pipeline quality (implemented in v0.2 draft)

- [x] Airflow DAG static audit and Python compile validation
- [x] Airflow CLI status integration
- [x] Airflow `dags test` builder-only execution wrapper
- [x] dbt schema/data-test coverage audit
- [x] dbt parse/test/build wrappers and run-results parsing
- [x] Snowflake connection/config audit
- [x] Snowflake read-only ping/query bridge
- [x] Unified policy-driven quality gate
- [x] Example Airflow -> dbt test -> Snowflake health DAG
- [ ] dbt manifest graph and impact selection (`state:modified+`)
- [ ] Snowflake query-history/cost/regression checks
- [ ] OpenLineage event ingestion
- [ ] Airflow task-log ingestion and failure summarization
- [ ] Great Expectations/Soda/Elementary adapters
