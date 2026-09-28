# Phase 3 cross-page state and evidence contract

This contract defines what each UI surface may claim. Project scope always includes `project_id` and `environment`; a selected-source workflow additionally includes the canonical `source_table_scope_id`. A page may show project-wide data, but it must label it as project-wide rather than silently attributing it to the active source table.

## Shared vocabulary

| State | Meaning | Must not be presented as |
| --- | --- | --- |
| Available | A live connector catalog was reachable and returned objects at the recorded refresh time. | Saved, onboarded, accepted, or analyzed scope. |
| Onboarded | An operator explicitly saved the source-table selection. It survives connector downtime. | Proof the connector is currently reachable. |
| Accepted | Discovery assets passed the acceptance/scope contract for this project/environment. Canonical duplicates count once. | A source-rooted pipeline or runtime execution. |
| Analyzed flow | A deterministic, accepted source-rooted graph path in the exact analysis scope. | Every accepted relationship or a completed run. |
| Runtime verified | An adapter observation is correlated by exact IDs and scope. | An inferred link based on names, DAG success, model success, or a metadata-only probe. |
| Quality plan | A named plan revision with its own status, selected/enabled rules and run history. | A quality execution when merely drafted, approved, or queued. |
| Action run | Persisted execution for the exact immutable action plan and its steps/external IDs. | A quality-rule run, data load, or source-table-scoped event unless evidence explicitly binds it. |

## Page obligations

- Project/Overview, Discovery, Catalog, Lineage, Quality Rules, Run Jobs, and Monitoring must agree on project, environment, active source-table scope and counts returned by `/api/project-scope`: live available tables (or unknown), saved onboarded tables, accepted assets, source-rooted flows, and runtime-observed nodes/edges.
- Discovery may show candidate matches, but a match is not accepted mapping evidence until its declared dependency/evidence supports it. Name similarity alone is insufficient.
- Catalog distinguishes accepted assets from live inventory. Lineage distinguishes deterministic links from observed runtime links and reports refresh time plus why external execution records are not incorporated.
- Quality Rules identifies the exact current plan ID/revision/status and separates its current-revision runs from historical runs on older revisions. No current run does not mean no history.
- Run Jobs topology can include tests as context, visibly separate from dbt models. Only explicit numbered plan steps are executable. Preview is not approval; approval is not execution. Tests and models are distinct selector kinds.
- Monitoring reports external adapter status and quality status independently. A completed dbt model action does not imply Airflow, Snowflake load, or quality test success.
- Reconciliation history retains exact source/target, check basis/key, row counts, partial-scan state, timestamp, and run association. Unavailable live reads do not erase historical results.
- Ask AI answers only from scoped evidence, labels stale/historical observations, and distinguishes missing proof from a negative result. It should cite the persisted run or comparison ID and observed timestamp when available.

## Request/run correlation

Use the API `X-Request-ID` for a browser/API request and persist/log `run_id`, `plan_id`, worker ID, attempt, adapter kind, and external invocation/run ID as separate correlation fields. Do not log API keys, authorization headers, SQL credentials, prompt bodies, or connector payloads. Do not manufacture a single external ID for a multi-system workflow: each step owns its adapter and identifier.

## Test-only boundary

The Phase 3 golden path runs only against `fixture=phase4`, `fixture-project/fixture`, and `ADQ_UI_TEST_FIXTURES=1`. It supports read-only fixture GETs, a preview-only in-memory action plan, and a canned Ask AI response. It rejects reconciliation writes and every action operation except preview. It never approves or executes work and must not be enabled in a production deployment.
