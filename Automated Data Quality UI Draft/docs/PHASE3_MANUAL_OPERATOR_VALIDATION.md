# Manual operator validation: one table end to end

This checklist is for a human operator using the local demo. Use a non-production project and one explicitly selected source table. Review every exact plan before approval. Stop on an unexpected scope or connector error. Do not use this checklist as authorization to change source data.

## Before starting

- Start using the no-seed command in [the operations runbook](../../Automated%20Data%20Quality%20Testing/docs/LOCAL_DEMO_OPERATIONS_RUNBOOK.md); confirm the preflight report and UI/API addresses.
- Check `/healthz` (process), `/readyz` (internal API/database/worker), then explicitly check the selected connector readiness. These are separate signals.
- Confirm the project and environment in the page header. Record the selected source table’s canonical identity and the current workspace revision.
- In Project/Discovery, record live available table count separately from saved selections. Select exactly one source table. Do not click “Add all tables.”

## One-table evidence path

1. **Onboarding/discovery:** verify the selected PostgreSQL source is exact. Inspect candidate Airflow DAG, dbt models, dbt tests, and Snowflake target individually. Confirm the evidence path for each; reject ambiguous or name-only matches. Record the discovery timestamp and accepted object IDs.
2. **Catalog:** verify accepted objects for the selected scope. Confirm models and test definitions have different kinds. Check that count changes are due to this selected table only.
3. **Lineage:** inspect source → ingestion → dbt model(s) → warehouse target links. Tests appear separately as quality definitions. Runtime state must remain `NOT_RUN` until adapter evidence is observed and exactly correlated.
4. **Quality Rules:** inspect the exact plan ID/revision, draft/approved status, selected/enabled counts, unresolved assumptions, mapping key, thresholds, and available adapter. A draft requires review; do not approve it just to progress this checklist.
5. **Run Jobs preview:** choose one explicit operation or named sequence. Review numbered steps, source/target scope, dependencies, selector kind (model vs test), parameters and plan hash. A one-DAG trigger is not end-to-end. Stop if any unnamed dependency was silently added. This checklist’s verification-only pass ends here: do not approve or execute unless the operator separately decides to run it.
6. **Monitoring/history:** inspect already persisted runs. Confirm exact external IDs and per-step statuses. Treat Airflow success, dbt success, Snowflake load, and data quality as separate claims. “Not checked” is valid when no quality result exists.
7. **Reconciliation:** inspect saved history first. Any new comparison is a separate read-only action that can scan real data and incur database load; choose key/bounds and confirm whether scan completion is partial before running it. Link a run ID only when that exact pipeline run exists.
8. **Ask AI:** ask a scoped question referring to the selected table or persisted run. Verify the answer cites the right evidence IDs/timestamps and labels stale history. Compare its claims to Catalog/Lineage/Monitoring; AI cannot create evidence or approve a mapping.

## Record and stop conditions

Capture page, project/environment/revision, exact table identity, relevant IDs, timestamps, status and any correlation/request ID. Stop for wrong project/environment, table ambiguity, stale artifacts, missing privileges, unexpected writes, UI errors, or a discrepancy between pages. Report it without retrying an action that could trigger an external job. After each separately authorized execution, monitor its persisted run before proposing the next step.

This checklist does not establish all-table coverage, production safety, multi-tenant isolation, or terabyte-scale performance.
