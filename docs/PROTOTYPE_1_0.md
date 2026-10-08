# ADE Prototype 1.0

## Goal

Prototype 1.0 turns the broad ADE capability set into one demonstrable product journey:

1. understand a project,
2. start or detect an incident,
3. collect evidence,
4. establish root cause and impact,
5. propose bounded remediation,
6. cross the human approval boundary,
7. execute the approved action,
8. verify and recertify,
9. retain an investigation receipt.

The focused UI is available at `/prototype`.

## What this slice includes

- project health and discovered dbt/Airflow/tool counts from the existing overview API;
- guided investigation scenarios backed by the certified supervisor runtime;
- root-cause confidence, first divergence, blast radius, and immutable evidence display;
- remediation details aligned with the existing investigation contract;
- explicit approval and execute/verify actions through the authenticated web-to-API proxy;
- recent investigation receipts for replay/review;
- a visible truth boundary separating repository/product-flow readiness from cloud-runtime readiness.

## What this slice does not claim

This branch does not claim a hosted production deployment or cloud-native persistence.

The current certified API constructs:

- `SQLiteControlPlaneRepository` from `ADE_DATABASE_PATH`;
- `InvestigationStore` from `ADE_INVESTIGATION_DATABASE`;
- quality state from `ADE_QUALITY_DATABASE`;
- a filesystem project root from `ADE_PROJECT_ROOT`.

Those assumptions are acceptable for local and single-node deployments but remain the next bounded migration before a horizontally scalable hosted control plane.

## Next bounded implementation target

Introduce persistence and artifact interfaces without weakening existing deterministic behavior:

- retain SQLite/filesystem adapters for local/demo mode;
- add a PostgreSQL control-plane/investigation adapter for hosted mode;
- add object storage for evidence/artifact payloads where filesystem durability is currently assumed;
- fail closed when hosted mode is requested without configured durable backing services;
- add parity tests proving SQLite and PostgreSQL adapters preserve approval, evidence immutability, incident transitions, and certification semantics.

Only after those tests pass should a hosted single-tenant deployment be treated as Prototype 1.0 cloud certification.
