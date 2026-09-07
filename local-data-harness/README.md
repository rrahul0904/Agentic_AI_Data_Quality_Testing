# Local Data Harness

A clean-room, local-first draft inspired by the architectural ideas in AltimateAI/altimate-code: an LLM agent wrapped around deterministic data-engineering tools.

## What works now

- CLI/REPL, HTTP API, and local browser UI
- zero-setup mock provider
- Ollama local model adapter
- SQL anti-pattern analysis
- draft table/column lineage
- PII scanning
- dbt discovery/manifest inspection
- local-stack discovery
- Builder / Analyst / Plan policy gates
- SQLite session/tool tracing
- runnable demo and tests

## Requirements

Node.js 22.5+ (Node 22 includes the built-in `node:sqlite` API used by this draft).

## Run in 60 seconds

```bash
cd local-data-harness
npm test
npm run demo
npm start
```

Inside the REPL:

```text
discover
analyze examples/demo/models/orders.sql
lineage examples/demo/models/orders.sql
dbt inspect
/tools
/sessions
```

## Run against the included demo workspace

```bash
node scripts/setup-demo.mjs
node src/cli/index.mjs --cwd examples/demo
```

Then ask:

```text
analyze models/orders.sql
lineage models/orders.sql
dbt inspect
discover
```

## Use Ollama locally

Install/run Ollama separately and pull a tool-capable model, for example:

```bash
ollama pull qwen3:8b
ollama serve
LDH_PROVIDER=ollama LDH_MODEL=qwen3:8b node src/cli/index.mjs --cwd examples/demo
```

No cloud API key is required.

## Headless API

```bash
node src/cli/index.mjs serve --cwd examples/demo --port 4096
# Open http://127.0.0.1:4096 in your browser
curl http://127.0.0.1:4096/health
curl -X POST http://127.0.0.1:4096/api/ask \
  -H 'content-type: application/json' \
  -d '{"prompt":"analyze models/orders.sql"}'
```

## Modes

- `analyst`: read-only tools; safest default.
- `plan`: same restrictive base for planning-only extensions.
- `builder`: allows workspace file writes and non-destructive local SQL writes.

Run with `--mode builder` when needed.

## Project structure

```text
src/
  cli/        REPL + HTTP server
  core/       agent loop + tool registry
  providers/  mock + Ollama
  storage/    local SQLite traces
  tools/      SQL, lineage, PII, dbt, files, discovery
examples/demo/
docs/
test/
```

See `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.

## v0.2 — Airflow + Snowflake + dbt quality testing

The harness now includes a unified data-quality gate with two levels:

```bash
# zero-credential local checks
npm run quality

# live/read-only integration checks when Airflow/dbt/Snowflake are configured
npm run quality:integration
```

New deterministic tools:

- `airflow_audit` — discovers DAGs, Python-compiles them, detects DAG IDs/schedules/catchup and dbt/Snowflake integration.
- `airflow_status` — probes the installed Airflow CLI and lists DAGs.
- `airflow_dag_test` — builder-only wrapper for `airflow dags test`.
- `dbt_quality_audit` — model/schema/test coverage plus `target/run_results.json` inspection.
- `dbt_parse`, `dbt_test`, `dbt_build` — real dbt CLI wrappers (`dbt_build` is builder-only).
- `snowflake_config_audit` — checks connection readiness without returning secrets.
- `snowflake_ping` — read-only connection health check.
- `snowflake_query` — bounded read-only Snowflake query execution.
- `quality_pipeline` — composes Airflow + dbt + Snowflake + SQL checks into one policy-driven gate.

Optional live stack setup:

```bash
./scripts/bootstrap-data-stack.sh
```

Then export the paths printed by the script and configure Snowflake via `SNOWFLAKE_CONNECTION_NAME` or the variables in `.env.example`.

See [`docs/DATA_QUALITY_PIPELINE.md`](docs/DATA_QUALITY_PIPELINE.md) for the architecture and CI policy.
